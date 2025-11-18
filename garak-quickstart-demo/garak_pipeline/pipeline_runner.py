"""Pipeline runner for Garak security scanning"""

import logging
import subprocess
import uuid
import asyncio
import json
import time
from typing import Dict, Optional, List
from datetime import datetime
from threading import Thread

import kfp
import requests
from pydantic import BaseModel, ConfigDict
from tqdm import tqdm

from .config import GarakConfig, KubeflowConfig, ScanConfig
from .progress_parser import ProgressParser
from .errors import GarakError
import os


logger = logging.getLogger(__name__)


class ScanJob(BaseModel):
    """Represents a Garak security scan job"""
    
    job_id: str
    status: str
    benchmark: str
    kubeflow_run_id: Optional[str] = None
    metadata: Dict = {}
    result: Optional[Dict] = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PipelineRunner:
    """Execute Garak security scans using Kubeflow Pipelines"""

    def __init__(self, kfp_config: KubeflowConfig, scan_config: ScanConfig):
        self.kfp_config = kfp_config
        self.scan_config = scan_config
        self.garak_config = GarakConfig()
        self.scan_jobs: Dict[str, ScanJob] = {}
        self._job_metadata: Dict[str, Dict] = {}
        self.s3_client = self._create_s3_client()

        # Initialize KFP client
        try:
            result = subprocess.run(
                ["oc", "whoami", "-t"],
                capture_output=True,
                text=True,
                check=True,
                timeout=5,
            )
            token = result.stdout.strip()
            if not token:
                raise RuntimeError(
                    "No token found. Please run `oc login` and try again."
                )

            # Pre-flight check
            response = requests.get(
                f"{self.kfp_config.pipelines_endpoint}/apis/v2beta1/healthz",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=5,
            )
            response.raise_for_status()

            self.kfp_client = kfp.Client(
                host=self.kfp_config.pipelines_endpoint,
                existing_token=token,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to get OpenShift token. Command failed with exit code {e.returncode}: {e.stderr.strip()}"
            ) from e
        except requests.exceptions.RequestException as e:
            raise RuntimeError(
                f"Failed to connect to Kubeflow Pipelines server at {self.kfp_config.pipelines_endpoint}, "
                "do you need a new token?"
            ) from e
        except Exception as e:
            raise RuntimeError("Failed to initialize Kubeflow Pipelines client.") from e

    def run_scan(self, benchmark: str) -> ScanJob:
        """
        Run a Garak security scan for a given benchmark
        
        Args:
            benchmark: Benchmark identifier (quick, standard, owasp_llm_top10, etc.)
            
        Returns:
            ScanJob object with job details
        """
        # Validate benchmark
        if benchmark not in self.garak_config.BENCHMARKS:
            available = list(self.garak_config.BENCHMARKS.keys())
            raise ValueError(
                f"Unknown benchmark '{benchmark}'. "
                f"Available benchmarks: {', '.join(available)}"
            )
        
        job_id = str(uuid.uuid4())
        job = ScanJob(
            job_id=job_id,
            status="submitted",
            benchmark=benchmark
        )
        
        # Submit to Kubeflow
        kubeflow_run_id = self._submit_to_kubeflow(benchmark, job_id)
        
        job.kubeflow_run_id = kubeflow_run_id
        self.scan_jobs[job_id] = job
        
        logger.info(
            f"Submitted Garak scan job {job_id} for benchmark '{benchmark}' "
            f"to Kubeflow with run ID {kubeflow_run_id}"
        )
        
        # Start log streaming in background
        self._start_log_streaming(job_id, kubeflow_run_id, benchmark)
        
        return job

    def _start_log_streaming(self, job_id: str, run_id: str, benchmark: str):
        """Start streaming logs in background thread"""
        try:
            # Initialize metadata
            self._job_metadata[job_id] = {
                "benchmark": benchmark,
                "created_at": datetime.now().isoformat(),
                "kfp_run_id": run_id
            }
            
            # Start async log streaming
            loop = asyncio.new_event_loop()
            thread = Thread(
                target=self._run_log_stream,
                args=(loop, job_id, run_id),
                daemon=True
            )
            thread.start()
        except Exception as e:
            logger.error(f"Failed to start log streaming: {e}")

    def _run_log_stream(self, loop: asyncio.AbstractEventLoop, job_id: str, run_id: str):
        """Run log streaming in asyncio event loop"""
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._stream_kfp_pod_logs(job_id, run_id))
        except Exception as e:
            logger.error(f"Log streaming error for job {job_id}: {e}")
        finally:
            loop.close()

    async def _stream_kfp_pod_logs(self, job_id: str, run_id: str):
        """Stream logs from KFP pod and parse progress in real-time"""
        from kubernetes import client, config, watch
        
        try:
            config.load_kube_config()
            v1 = client.CoreV1Api()
            
            namespace = self.kfp_config.namespace
            label_selector = f"pipeline/runid={run_id}"
            
            # Wait for pod to be ready
            pod_name = await self._wait_for_pod(v1, namespace, label_selector, job_id)
            if not pod_name:
                logger.warning(f"Job {job_id}: Pod not found")
                return
            
            # Wait for container
            if not await self._wait_for_container(v1, namespace, pod_name, job_id):
                return
            
            # Create progress parser
            parser = ProgressParser(job_id, self._job_metadata)
            
            # Stream logs
            await asyncio.to_thread(
                self._sync_stream_logs,
                v1,
                pod_name,
                namespace,
                "main",
                parser,
                job_id
            )
            
        except Exception as e:
            logger.error(f"Job {job_id}: Log streaming error: {e}")

    async def _wait_for_pod(self, v1, namespace: str, label_selector: str, job_id: str, timeout: int = 300) -> Optional[str]:
        """Wait for pod to be created"""
        start_time = datetime.now()
        
        while (datetime.now() - start_time).total_seconds() < timeout:
            try:
                pods = v1.list_namespaced_pod(namespace=namespace, label_selector=label_selector)
                
                for pod in pods.items:
                    if 'system-container-impl' not in pod.metadata.name:
                        continue
                    
                    node_name = pod.metadata.annotations.get('workflows.argoproj.io/node-name', '').lower()
                    
                    if '.garak-scan' in node_name and '.executor' in node_name:
                        if pod.status.phase.lower() in ['pending', 'running']:
                            logger.debug(f"Job {job_id}: Found pod: {pod.metadata.name}")
                            return pod.metadata.name
            except Exception as e:
                logger.debug(f"Job {job_id}: Searching for pod... {e}")
            
            await asyncio.sleep(5)
        
        return None

    async def _wait_for_container(self, v1, namespace: str, pod_name: str, job_id: str, timeout: int = 300) -> bool:
        """Wait for container to be ready"""
        start_time = datetime.now()
        
        while (datetime.now() - start_time).total_seconds() < timeout:
            try:
                pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                
                if pod.status.container_statuses:
                    for cs in pod.status.container_statuses:
                        if cs.name == "main" and (cs.state.running or cs.state.terminated):
                            return True
                
                if pod.status.phase.lower() == 'running':
                    return True
            except Exception as e:
                logger.debug(f"Job {job_id}: Waiting for container... {e}")
            
            await asyncio.sleep(5)
        
        return False

    def _sync_stream_logs(self, v1, pod_name: str, namespace: str, container_name: str, parser: ProgressParser, job_id: str):
        """Synchronously stream pod logs"""
        from kubernetes import watch as k8s_watch
        
        try:
            w = k8s_watch.Watch()
            
            for line in w.stream(
                v1.read_namespaced_pod_log,
                name=pod_name,
                namespace=namespace,
                container=container_name,
                follow=True,
                _preload_content=False
            ):
                parser.parse_line(line)
                
                # Check if job is done
                job = self.scan_jobs.get(job_id)
                if job and job.status in ["completed", "failed", "cancelled"]:
                    w.stop()
                    break
                    
        except Exception as e:
            logger.error(f"Job {job_id}: Stream error: {e}")

    def _submit_to_kubeflow(self, benchmark: str, job_id: str) -> str:
        """Submit pipeline to Kubeflow"""
        from .pipeline import garak_scan_pipeline
        
        benchmark_config = self.garak_config.BENCHMARKS[benchmark]
        
        # Build Garak command
        command = self._build_garak_command(benchmark_config)
        
        # Submit pipeline
        run_result = self.kfp_client.create_run_from_pipeline_func(
            pipeline_func=garak_scan_pipeline,
            arguments={
                "command": command,
                "job_id": job_id,
                "eval_threshold": self.scan_config.eval_threshold,
                "timeout_seconds": benchmark_config["timeout"],
                "max_retries": self.scan_config.max_retries,
                "use_gpu": self.scan_config.use_gpu,
                # "aws_secret_name": self.kfp_config.s3_secret_name,
            },
            run_name=f"garak-{benchmark}-{job_id[:8]}",
            namespace=self.kfp_config.namespace,
            experiment_name=self.kfp_config.experiment_name,
        )
        
        return run_result.run_id

    def _build_garak_command(self, benchmark_config: Dict) -> List[str]:
        """Build Garak command with all options"""
        
        # Base command
        command = ["garak"]
        
        # Model configuration
        if self.scan_config.model_type == "openai":
            command.extend([
                "--model_type", "openai.OpenAICompatible",
                "--model_name", self.scan_config.model_name,
            ])
            # Add generator options for OpenAI compatible endpoint
            generator_options = {
                "openai": {
                    "OpenAICompatible": {
                        "uri": self.scan_config.model_endpoint if self.scan_config.model_endpoint.rstrip("/").endswith("/v1") else f"{self.scan_config.model_endpoint.rstrip('/')}/v1",
                        "model": self.scan_config.model_name,
                        "api_key": "DUMMY",
                        "suppressed_params": ["n"]
                    }
                }
            }
            command.extend(["--generator_options", json.dumps(generator_options)])
        else:
            command.extend([
                "--model_type", self.scan_config.model_type,
                "--model_name", self.scan_config.model_name,
            ])
        
        # Execution parameters
        command.extend([
            "--parallel_attempts", 
            str(benchmark_config.get("parallel_attempts", self.garak_config.DEFAULT_PARALLEL_ATTEMPTS))
        ])
        command.extend([
            "--generations", 
            str(benchmark_config.get("generations", self.garak_config.DEFAULT_GENERATIONS))
        ])
        
        # Reproducibility
        if "seed" in benchmark_config:
            command.extend(["--seed", str(benchmark_config["seed"])])
        
        # Output processing
        if "deprefix" in benchmark_config:
            command.extend(["--deprefix", benchmark_config["deprefix"]])
        
        # Evaluation threshold
        if "eval_threshold" in benchmark_config:
            command.extend(["--eval_threshold", str(benchmark_config["eval_threshold"])])
        
        # Probe configuration
        if "probe_options" in benchmark_config:
            command.extend(["--probe_options", json.dumps(benchmark_config["probe_options"])])
        
        # Detector configuration
        if "detectors" in benchmark_config:
            command.extend(["--detectors", self._normalize_list_arg(benchmark_config["detectors"])])
        
        if "extended_detectors" in benchmark_config:
            command.extend(["--extended_detectors", self._normalize_list_arg(benchmark_config["extended_detectors"])])
        
        if "detector_options" in benchmark_config:
            command.extend(["--detector_options", json.dumps(benchmark_config["detector_options"])])
        
        # Buff configuration (input transformations)
        if "buffs" in benchmark_config:
            command.extend(["--buffs", self._normalize_list_arg(benchmark_config["buffs"])])
        
        if "buff_options" in benchmark_config:
            command.extend(["--buff_options", json.dumps(benchmark_config["buff_options"])])
        
        # Harness configuration
        if "harness_options" in benchmark_config:
            command.extend(["--harness_options", json.dumps(benchmark_config["harness_options"])])
        
        # AutoDAN generation
        if "generate_autodan" in benchmark_config:
            command.extend(["--generate_autodan", benchmark_config["generate_autodan"]])
        
        # Add probes/taxonomy based on benchmark type
        if benchmark_config["type"] == "taxonomy":
            command.extend(["--probe_tags", ','.join(benchmark_config["taxonomy_filters"])])
        elif benchmark_config["type"] == "probes":
            command.extend(["--probes", ','.join(benchmark_config["probes"])])
        
        return command
    
    def _normalize_list_arg(self, arg) -> str:
        """Normalize list argument to comma-separated string"""
        if isinstance(arg, str):
            return arg
        elif isinstance(arg, list):
            return ",".join(arg)
        else:
            return str(arg)

    def job_status(self, job_id: str) -> ScanJob:
        """Get status of a scan job with progress information"""
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")

        try:
            run_detail = self.kfp_client.get_run(job.kubeflow_run_id)
            
            # Update status
            if run_detail.state == "FAILED":
                job.status = "failed"
            elif run_detail.state == "SUCCEEDED":
                job.status = "completed"
                # Fetch results
                self._fetch_results(job)
            elif run_detail.state == "RUNNING" or run_detail.state == "PENDING":
                job.status = "in_progress"
            elif run_detail.state == "CANCELED":
                job.status = "cancelled"
            else:
                job.status = "unknown"
            
            # Get metadata
            metadata = self._job_metadata.get(job_id, {})
            
            # Calculate overall scan elapsed and ETA
            if job.status in ["in_progress", "submitted"]:
                created_at_str = metadata.get("created_at")
                if created_at_str and "progress" in metadata:
                    try:
                        from datetime import timezone
                        created_at = datetime.fromisoformat(created_at_str)
                        # Use timezone-aware datetime if created_at has timezone info
                        now = datetime.now(timezone.utc) if created_at.tzinfo else datetime.now()
                        overall_elapsed = int((now - created_at).total_seconds())
                        
                        # Overall scan elapsed
                        metadata["progress"]["overall_elapsed_seconds"] = overall_elapsed
                        
                        # Calculate overall ETA based on completed probes
                        completed = metadata["progress"].get("completed_probes", 0)
                        total = metadata["progress"].get("total_probes", 0)
                        
                        if completed > 0 and total > 0:
                            avg_time_per_probe = overall_elapsed / completed
                            remaining = total - completed
                            
                            # Add partial progress of current probe if available
                            if probe_prog := metadata["progress"].get("current_probe_progress"):
                                probe_pct = probe_prog.get("percent", 0) / 100.0
                                # Reduce remaining by current probe's progress
                                remaining = remaining - probe_pct
                            
                            overall_eta = int(avg_time_per_probe * remaining)
                            metadata["progress"]["overall_eta_seconds"] = overall_eta
                        
                    except Exception as e:
                        logger.warning(f"Error calculating scan times: {e}")
            
            job.metadata = metadata
            
        except Exception as e:
            logger.error(f"Failed to get job status: {str(e)}")

        return job

    def _fetch_results(self, job: ScanJob):
        """Fetch results from S3"""
        
        try:
            # Initialize S3 client
            bucket = os.getenv('AWS_S3_BUCKET', 'pipeline-artifacts')

            if not self.s3_client:
                self.s3_client = self._create_s3_client()
            
            # Fetch result file
            response = self.s3_client.get_object(
                Bucket=bucket,
                Key=f"{job.job_id}/scan_result.json"
            )
            job.result = json.loads(response['Body'].read())
            
            logger.info(f"Successfully fetched results for job {job.job_id}")
        except Exception as e:
            logger.warning(f"Failed to fetch results for job {job.job_id}: {e}")

    def _create_s3_client(self):
        try:
            import boto3
            self.s3_client = boto3.client('s3',
                                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                                region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1'),
                                endpoint_url=os.getenv('AWS_S3_ENDPOINT'),  # if using MinIO
                            )
        except ImportError as e:
            raise GarakError(
                "Boto3 is not installed. Install with: pip install boto3"
            ) from e
        except Exception as e:
            raise GarakError(
                f"Unable to connect to S3."
            ) from e
        return self.s3_client

    def job_result(self, job_id: str) -> Optional[Dict]:
        """Get the result of a completed scan job"""
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")
        print(job.model_dump())
        if job.status == "completed":
            return job.result
        elif job.status == "failed":
            raise RuntimeError(f"Job {job_id} failed")
        else:
            return None  # Job still running

    def job_cancel(self, job_id: str) -> None:
        """Cancel a running scan job"""
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")

        try:
            self.kfp_client.runs.terminate_run(job.kubeflow_run_id)
            job.status = "cancelled"
            logger.info(f"Cancelled Kubeflow run {job.kubeflow_run_id} for job {job_id}")
        except Exception as e:
            logger.error(f"Failed to cancel job: {str(e)}")
            raise RuntimeError(f"Failed to cancel job: {str(e)}") from e

    def wait_for_completion(self, job_id: str, poll_interval: int = 10) -> ScanJob:
        """
        Wait for job completion with tqdm progress bar
        
        Args:
            job_id: Job identifier
            poll_interval: Seconds between status checks
            
        Returns:
            Completed ScanJob
        """
        
        def format_time(seconds: int | None, hours_needed: bool = True) -> str:
            """Format seconds to HH:MM:SS or MM:SS"""
            if seconds is None:
                return "N/A"
            if hours_needed:
                hours = seconds // 3600
                minutes = (seconds % 3600) // 60
                secs = seconds % 60
                return f"{hours:02d}:{minutes:02d}:{secs:02d}"
            else:
                minutes = seconds // 60
                secs = seconds % 60
                return f"{minutes:02d}:{secs:02d}"
        
        status = self.job_status(job_id=job_id)
        
        pbar = tqdm(
            total=100,
            desc="Garak Scan",
            unit="%",
            bar_format='{desc}: {n:.1f}%|{bar}| {postfix}',
            ncols=150
        )
        
        last_percent = 0
        
        while status.status in ["submitted", "in_progress"]:
            progress = status.metadata.get("progress", {})
            current_percent = progress.get("percent", 0) if progress else 0
            
            # Phase 1: Validation/Setup (no progress yet)
            if status.status in ["submitted", "in_progress"] and not progress:
                pbar.set_description_str("Garak Setup")
                pbar.set_postfix_str("[INIT] Validating configuration and initializing Garak scan...")
            
            # Phase 2: Scanning (progress available but < 100)
            elif progress and current_percent < 100:
                pbar.set_description_str("Garak Scan")
                
                # Update overall progress bar
                pbar.update(max(0, current_percent - last_percent))
                last_percent = current_percent
                
                postfix_parts = []
                
                # Overall scan times
                overall_elapsed = progress.get("overall_elapsed_seconds", 0)
                overall_eta = progress.get("overall_eta_seconds")
                
                if overall_eta:
                    time_info = f"[{format_time(overall_elapsed)}<{format_time(overall_eta)}]"
                else:
                    time_info = f"[{format_time(overall_elapsed)}]"
                
                postfix_parts.append(time_info)
                
                current_probe = progress.get("current_probe", "N/A")
                # Shorten probe name to save bar space
                probe_short = current_probe.replace("probes.", "").split('.')[-1]
                
                # Overall metrics
                completed = int(progress.get("completed_probes", 0))
                total = int(progress.get("total_probes", 0))
                current_idx = min(completed + 1, total)
                postfix_parts.append(f"Current ({current_idx}/{total}): {probe_short}")
                
                # Probe-specific progress (if available)
                if probe_progress := progress.get("current_probe_progress"):
                    probe_pct = probe_progress.get("percent", 0)
                    attempts_cur = probe_progress.get("attempts_current", 0)
                    attempts_tot = probe_progress.get("attempts_total", 0)
                    probe_eta_s = probe_progress.get("probe_eta_seconds")
                    
                    # Probe-level detail
                    if probe_eta_s is not None:
                        probe_eta_str = format_time(probe_eta_s, hours_needed=False).split(':')[-2:]
                        probe_eta_display = f"{probe_eta_str[0]}:{probe_eta_str[1]}"
                    else:
                        probe_eta_display = "N/A"
                    postfix_parts.append(
                        f"({probe_pct}%, Attempts: {attempts_cur}/{attempts_tot}, ETA:{probe_eta_display})"
                    )
                
                pbar.set_postfix_str(" ".join(postfix_parts))
            
            # Phase 3: Postprocessing (progress at 100% but job still in_progress)
            elif progress and current_percent >= 100 and status.status == "in_progress":
                if last_percent < 100:
                    pbar.update(100 - last_percent)
                    last_percent = 100
                pbar.set_description_str("Garak Postprocessing")
                
                overall_elapsed = progress.get("overall_elapsed_seconds", 0)
                pbar.set_postfix_str(f"[PARSE] Parsing results and uploading reports... [{format_time(overall_elapsed)}]")
            
            time.sleep(poll_interval)
            status = self.job_status(job_id=job_id)
        
        pbar.n = 100
        pbar.close()
        
        if status.status in ['failed', 'completed', 'cancelled']:
            print("=" * 100)
            if status.status == 'completed':
                print(f"Job ended with status: {status.status} [SUCCESS]")
            elif status.status == 'failed':
                print(f"Job ended with status: {status.status} [FAILED]")
            elif status.status == 'cancelled':
                print(f"Job ended with status: {status.status} [CANCELLED]")
        
        return status

