import logging
import uuid
import json
import time
from typing import Dict, Optional, List
from datetime import datetime

import kfp
import requests
from pydantic import BaseModel, Field
import os
from .config import (
    BenchmarkConfig,
    BenchmarkRegistry,
    EvalConfig,
    KubeflowConfig,
)
from .errors import GarakError, GarakValidationError, GarakConfigError
from .utils import clean_ssl_verify, create_s3_client, check_and_create_bucket

logger = logging.getLogger(__name__)


class ScanJob(BaseModel):
    """Represents a Garak security scan job"""
    
    job_id: str
    status: str
    benchmark_id: str
    model_name: str
    kubeflow_run_id: Optional[str] = None
    created_at: str
    metadata: Dict = Field(default_factory=dict, description="Metadata about the scan job")
    result: Optional[Dict] = None


class PipelineRunner:
    """
    Run Garak security scans on Kubeflow Pipelines.
    
    Example:
        >>> runner = PipelineRunner(kfp_config)
        >>> 
        >>> # Run with predefined benchmark
        >>> job = runner.run_scan(EvalConfig(
        ...     model=ModelConfig(
        ...         model_endpoint="https://your-model/v1",
        ...         model_name="gpt-4",
        ...         api_key="your-api-key",
        ...     ),
        ...     benchmark="quick",
        ...     sampling_params={"temperature": 0.5, "max_tokens": 100},
        ... ))
        >>> 
        >>> # Run with inline benchmark
        >>> job = runner.run_scan(EvalConfig(
        ...     model=ModelConfig(
        ...         model_endpoint="https://your-model/v1",
        ...         model_name="gpt-4",
        ...         api_key="your-api-key",
        ...     ),
        ...     benchmark=BenchmarkConfig(
        ...         name="My Custom Scan",
        ...         probes=["dan.DAN", "encoding"],
        ...         timeout=3600,
        ...     ),
        ...     sampling_params={"temperature": 0.5, "max_tokens": 100},
        ... ))
    """

    def __init__(self, kfp_config: Optional[KubeflowConfig] = None):
        self.kfp_config = kfp_config or KubeflowConfig()
        self.scan_jobs: Dict[str, ScanJob] = {}
        self._s3_bucket: str = None
        self._s3_prefix: str = None
        self._parse_s3_config()
        self.s3_client = self._create_s3_client() # to fetch results from S3
        
        # Benchmark registry (predefined + registered)
        self.benchmarks = BenchmarkRegistry()

        # Initialize KFP client
        self.kfp_client = self._init_kfp_client()
    
    def _parse_s3_config(self):
        """Parse S3 bucket and prefix from results_s3_prefix.
        
        Raises:
            GarakConfigError: If results_s3_prefix is invalid or missing
        """
        results_s3_prefix = self.kfp_config.results_s3_prefix
        
        # Validate input
        if not results_s3_prefix or not results_s3_prefix.strip():
            raise GarakValidationError(
                "results_s3_prefix must be specified in kubeflow_config. "
                "Format: 'bucket/prefix' or 's3://bucket/prefix'"
            )
        
        results_s3_prefix = results_s3_prefix.strip()
        
        # Handle s3://bucket/prefix format
        if results_s3_prefix.lower().startswith("s3://"):
            results_s3_prefix = results_s3_prefix[len("s3://"):]
        
        # validate format after stripping s3:// prefix
        if not results_s3_prefix:
            raise GarakValidationError(
                "results_s3_prefix cannot be just 's3://'. "
                "Format: 'bucket/prefix' or 's3://bucket/prefix'"
            )
        
        # Split bucket and prefix
        parts = results_s3_prefix.split("/", 1)
        self._s3_bucket = parts[0].strip()
        self._s3_prefix = parts[1].strip().rstrip("/") if len(parts) > 1 else ""
        
        # validate bucket name is not empty
        if not self._s3_bucket:
            raise GarakValidationError(
                f"Invalid S3 bucket name in results_s3_prefix: '{self.kfp_config.results_s3_prefix}'. "
                "Bucket name cannot be empty."
            )
        
        
        logger.info(f"Parsed S3 config - bucket: {self._s3_bucket}, prefix: {self._s3_prefix}")

    def _init_kfp_client(self) -> kfp.Client:
        """Initialize Kubeflow Pipelines client with OpenShift authentication"""
        try:
            # Get OpenShift token
            # Use token from config if provided, otherwise get from kubeconfig
            token = self.kfp_config.pipelines_api_token or self._get_token()
            if not token:
                raise GarakError(
                    "No authentication token found. Please check your Kubeflow Pipelines API token or run `oc login` and try again."
                )

            # health check
            response = requests.get(
                f"{self.kfp_config.pipelines_endpoint}/apis/v2beta1/healthz",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                },
                timeout=5,
            )
            response.raise_for_status()

            ssl_cert = None
            verify_ssl = self.kfp_config.verify_ssl
            if isinstance(self.kfp_config.verify_ssl, str):
                verify_ssl = clean_ssl_verify(self.kfp_config.verify_ssl)
                if isinstance(verify_ssl, str):
                    ssl_cert = verify_ssl
                    verify_ssl = True

            return kfp.Client(
                host=self.kfp_config.pipelines_endpoint,   
                existing_token=token,
                verify_ssl=verify_ssl,
                ssl_ca_cert=ssl_cert,
            )
        except requests.exceptions.RequestException as e:
            raise GarakError(
                f"Failed to connect to Kubeflow Pipelines server at {self.kfp_config.pipelines_endpoint}, "
                "do you need a new token?"
            ) from e
        except Exception as e:
            raise GarakError(f"Failed to initialize Kubeflow Pipelines client: {e}") from e

    def _get_token(self) -> str:
        """Get authentication token from kubernetes config."""
        try:
            from kubernetes.client.configuration import Configuration
            from kubernetes.config.kube_config import load_kube_config
            from kubernetes.config.config_exception import ConfigException
            from kubernetes.client.exceptions import ApiException

            config = Configuration()

            load_kube_config(client_configuration=config)
            token = config.api_key["authorization"].split(" ")[-1]
            return token
        except (KeyError, ConfigException) as e:
            raise ApiException(
                401, "Unauthorized, try running command like `oc login` first"
            ) from e
        except ImportError as e:
            raise GarakError(
                "Kubernetes client is not installed. Install with: pip install kubernetes"
            ) from e
    
    def run_scan(self, config: EvalConfig) -> ScanJob:
        """
        Run a Garak security scan.
        
        Args:
            config: EvalConfig with model, benchmark, and scan parameters
            
        Returns:
            ScanJob object with job details
            
        Example:
            >>> # Using predefined benchmark
            >>> job = runner.run_scan(EvalConfig(
            ...     model=ModelConfig(
            ...         model_endpoint="https://your-model/v1",
            ...         model_name="gpt-4",
            ...         api_key="your-api-key",
            ...     ),
            ...     benchmark="quick",
            ...     sampling_params={"temperature": 0.5, "max_tokens": 100},
            ... ))
            >>> 
            >>> # Using inline benchmark
            >>> job = runner.run_scan(EvalConfig(
            ...     model=ModelConfig(
            ...         model_endpoint="https://your-model/v1",
            ...         model_name="gpt-4",
            ...         api_key="your-api-key",
            ...     ),
            ...     benchmark=BenchmarkConfig(
            ...         name="My Custom Scan",
            ...         probes=["dan.DAN", "encoding"],
            ...         timeout=3600,
            ...     ),
            ...     sampling_params={"temperature": 0.5, "max_tokens": 100},
            ... ))
        """
        # Resolve benchmark
        if isinstance(config.benchmark, str):
            benchmark_id = config.benchmark
            benchmark_config = self.benchmarks.get(benchmark_id)
            if not benchmark_config:
                raise GarakConfigError(f"Benchmark '{benchmark_id}' not found")
        else:
            benchmark_config = config.benchmark
            benchmark_id = benchmark_config.name.lower().replace(" ", "_")
            self.register_benchmark(benchmark_id, benchmark_config)
        
        job_id = str(uuid.uuid4())
        created_at = datetime.now().isoformat()
        
        job = ScanJob(
            job_id=job_id,
            status="submitted",
            benchmark_id=benchmark_id,
            model_name=config.model.model_name,
            created_at=created_at
        )
        
        # Submit to Kubeflow
        kubeflow_run_id = self._submit_to_kubeflow(config, benchmark_config, benchmark_id, job_id)
        
        job.kubeflow_run_id = kubeflow_run_id
        self.scan_jobs[job_id] = job
        
        logger.info(
            f"Submitted scan job {job_id} for model '{config.model.model_name}' "
            f"with benchmark '{benchmark_id}' to Kubeflow (run ID: {kubeflow_run_id})"
        )
        
        return job

    def register_benchmark(
        self,
        benchmark_id: str,
        config: BenchmarkConfig,
        overwrite: bool = False
    ) -> None:
        """
        Register a reusable benchmark.
        
        Args:
            benchmark_id: Unique identifier
            config: BenchmarkConfig with probes/taxonomy and options
            overwrite: Allow overwriting existing
            
        Example:
            >>> runner.register_benchmark("jailbreak", BenchmarkConfig(
            ...     name="Jailbreak Tests",
            ...     probes=["dan.DAN"],
            ...     timeout=3600,
            ... ))
        """
        self.benchmarks.register(benchmark_id, config, overwrite=overwrite)
        logger.info(f"Registered benchmark '{benchmark_id}': {config.name}")

    def list_benchmarks(self, include_details: bool = False) -> Dict[str, Dict]:
        """
        List all available benchmarks.
        
        Args:
            include_details: If True, include full BenchmarkConfig objects
            
        Returns:
            Dictionary of benchmark_id -> benchmark info
            
        Example:
            >>> for name, info in runner.list_benchmarks().items():
            ...     tag = " (predefined)" if info["is_predefined"] else ""
            ...     print(f"{name}{tag}: {info['description']}")
        """
        if include_details:
            return {bid: config.model_dump() for bid, config in self.benchmarks}
        
        return self.benchmarks.list_with_info()

    def unregister_benchmark(self, benchmark_id: str) -> bool:
        """
        Remove a benchmark.
        
        Args:
            benchmark_id: The benchmark identifier to remove
            
        Returns:
            True if removed, False if not found
        """
        if self.benchmarks.unregister(benchmark_id):
            logger.info(f"Removed benchmark '{benchmark_id}'")
            return True
        return False

    def _submit_to_kubeflow(
        self, 
        eval_config: EvalConfig, 
        benchmark_config: BenchmarkConfig,
        benchmark_id: str,
        job_id: str
    ) -> str:
        """Submit pipeline to Kubeflow"""
        from .pipeline import garak_scan_pipeline
        
        os.environ['KUBEFLOW_S3_CREDENTIALS_SECRET_NAME'] = self.kfp_config.s3_credentials_secret_name
        os.environ['KUBEFLOW_BASE_IMAGE'] = self.kfp_config.base_image
        
        # Build Garak command
        command = self._build_garak_command(eval_config, benchmark_config)
        
        run_name = f"garak-{benchmark_id}-{job_id[:8]}"
        eval_threshold = eval_config.eval_threshold if eval_config.eval_threshold is not None else benchmark_config.eval_threshold
        timeout = eval_config.timeout if eval_config.timeout is not None else benchmark_config.timeout

        # Submit pipeline
        run_result = self.kfp_client.create_run_from_pipeline_func(
            pipeline_func=garak_scan_pipeline,
            arguments={
                "command": command,
                "job_id": job_id,
                "eval_threshold": eval_threshold,
                "timeout_seconds": timeout,
                "max_retries": eval_config.max_retries,
                "use_gpu": eval_config.use_gpu,
                "s3_bucket": self._s3_bucket,
                "s3_prefix": self._s3_prefix,
                "verify_ssl": str(self.kfp_config.verify_ssl),
            },
            run_name=run_name,
            namespace=self.kfp_config.namespace,
            experiment_name=self.kfp_config.experiment_name,
        )
        
        return run_result.run_id

    def _build_garak_command(
        self, 
        eval_config: EvalConfig, 
        benchmark_config: BenchmarkConfig
    ) -> List[str]:
        """Build Garak CLI command."""
        
        command = ["garak"]
        
        # Model configuration (from EvalConfig)
        command.extend([
            "--model_type", "openai.OpenAICompatible",
            "--model_name", eval_config.model.model_name,
        ])

        model_endpoint = eval_config.model.model_endpoint.rstrip("/")
        if not model_endpoint:
            raise GarakValidationError("Model endpoint is required")
        
        generator_options = {
            "openai": {
                "OpenAICompatible": {
                    "uri": model_endpoint,
                    "model": eval_config.model.model_name,
                    "api_key": eval_config.model.api_key or "DUMMY",
                    "suppressed_params": ["n"]
                }
            }
        }
        if eval_config.sampling_params:
            generator_options["openai"]["OpenAICompatible"].update(eval_config.sampling_params)

        command.extend(["--generator_options", json.dumps(generator_options)])

        # Execution parameters from benchmark config
        command.extend(["--parallel_attempts", str(eval_config.parallel_attempts)])
        command.extend(["--generations", str(eval_config.generations)])
        
        # Optional benchmark parameters
        if benchmark_config.seed is not None:
            command.extend(["--seed", str(benchmark_config.seed)])
        
        if benchmark_config.deprefix is not None:
            command.extend(["--deprefix", benchmark_config.deprefix])
        
        if benchmark_config.eval_threshold is not None:
            command.extend(["--eval_threshold", str(benchmark_config.eval_threshold)])
        
        # override eval_threshold if specified
        if eval_config.eval_threshold is not None:
            command.extend(["--eval_threshold", str(eval_config.eval_threshold)])
        
        if benchmark_config.probe_options is not None:
            command.extend(["--probe_options", json.dumps(benchmark_config.probe_options)])
        
        if benchmark_config.detectors is not None:
            command.extend(["--detectors", self._normalize_list_arg(benchmark_config.detectors)])
        
        if benchmark_config.extended_detectors is not None:
            command.extend(["--extended_detectors", self._normalize_list_arg(benchmark_config.extended_detectors)])
        
        if benchmark_config.detector_options is not None:
            command.extend(["--detector_options", json.dumps(benchmark_config.detector_options)])
        
        if benchmark_config.buffs is not None:
            command.extend(["--buffs", self._normalize_list_arg(benchmark_config.buffs)])
        
        if benchmark_config.buff_options is not None:
            command.extend(["--buff_options", json.dumps(benchmark_config.buff_options)])
        
        if benchmark_config.harness_options is not None:
            command.extend(["--harness_options", json.dumps(benchmark_config.harness_options)])
        
        if benchmark_config.generate_autodan is not None:
            command.extend(["--generate_autodan", benchmark_config.generate_autodan])

        if benchmark_config.taxonomy is not None:
            command.extend(["--taxonomy", benchmark_config.taxonomy])

        # Add probes or taxonomy filters
        if benchmark_config.is_taxonomy_based:
            command.extend(["--probe_tags", ','.join(benchmark_config.taxonomy_filters)])
        elif benchmark_config.is_probe_based:
            command.extend(["--probes", ','.join(benchmark_config.probes)])
        
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
        """Get status of a scan job
        
        Args:
            job_id: Job identifier
            
        Returns:
            ScanJob with updated status
        """
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
            
        except Exception as e:
            logger.error(f"Failed to get job status: {str(e)}")

        return job

    def _fetch_results(self, job: ScanJob):
        """Fetch results from S3.
        
        Requires AWS credentials to be set in environment variables.
        """
        from botocore.exceptions import ClientError
        
        if job.result:
            return  # Already fetched
        
        bucket = self._s3_bucket
        prefix = self._s3_prefix

        if prefix:
            key = f"{prefix}/{job.job_id}/scan_result.json"
        else:
            key = f"{job.job_id}/scan_result.json"
        
        logger.info(f"Fetching results from s3://{bucket}/{key}")
        
        try:
            if not self.s3_client:
                self._create_s3_client()
            
            # Fetch result file
            response = self.s3_client.get_object(
                Bucket=bucket,
                Key=key
            )
            job.result = json.loads(response['Body'].read())
            
            logger.info(f"Successfully fetched results for job {job.job_id}")
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                logger.error(
                    f"Result file not found at s3://{bucket}/{key}. "
                    f"The pipeline may still be uploading or the key path may be incorrect."
                )
            elif error_code == 'NoSuchBucket':
                logger.error(
                    f"Bucket '{bucket}' not found. Check your AWS_S3_BUCKET or results_s3_prefix configuration."
                )
            else:
                logger.error(
                    f"S3 error fetching results for job {job.job_id}: [{error_code}] {e}\n"
                    f"  - Bucket: {bucket}\n"
                    f"  - Key: {key}\n"
                    f"  - Endpoint: {os.getenv('AWS_S3_ENDPOINT', 'default')}"
                )
            raise
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"Failed to fetch results for job {job.job_id}: [{error_type}] {e}\n"
                f"  - Bucket: {bucket}\n"
                f"  - Key: {key}\n"
                f"  - Endpoint: {os.getenv('AWS_S3_ENDPOINT', 'default')}\n"
                f"Ensure AWS credentials are set in your environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)."
            )
            raise

    def _create_s3_client(self):
        """Create S3 client for fetching results.
        
        Note: AWS credentials must be set in environment variables:
        - AWS_ACCESS_KEY_ID
        - AWS_SECRET_ACCESS_KEY
        - AWS_S3_ENDPOINT (optional, for MinIO)
        - AWS_DEFAULT_REGION (optional, defaults to us-east-1)
        """
        endpoint_url = os.getenv('AWS_S3_ENDPOINT')
        access_key = os.getenv('AWS_ACCESS_KEY_ID')
        secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        region = os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
        
        if not access_key or not secret_key:
            logger.warning(
                "AWS credentials not found in environment. "
                "Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY to fetch results from S3."
            )
        
        logger.debug(f"Creating S3 client for bucket={self._s3_bucket}, endpoint={endpoint_url}")
        
        self.s3_client = create_s3_client(
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            verify_ssl=self.kfp_config.verify_ssl,
        )
        check_and_create_bucket(self.s3_client, self._s3_bucket)
        return self.s3_client

    def job_result(self, job_id: str) -> Optional[Dict]:
        """Get the result of a completed scan job
        
        Args:
            job_id: Job identifier
            
        Returns:
            Result dictionary if job is completed, None if still running
        """
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")
        
        if job.status == "completed":
            if not job.result:
                self._fetch_results(job)
            return job.result
        elif job.status == "failed":
            raise RuntimeError(f"Job {job_id} failed")
        else:
            return None  # Job still running

    def download_html_report(self, job_id: str, output_path: Optional[str] = None) -> str:
        """Download the HTML report to a local file
        
        Args:
            job_id: Job identifier
            output_path: Local file path to save the report (default: scan_report_{job_id}.html)
            
        Returns:
            Path to the downloaded file
        """
        from botocore.exceptions import ClientError
        from pathlib import Path
        
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")
        
        if self._s3_prefix:
            key = f"{self._s3_prefix}/{job_id}/scan.report.html"
        else:
            key = f"{job_id}/scan.report.html"
        
        # Default output path
        if output_path is None:
            output_path = f"scan_report_{job_id}.html"
        
        try:
            if not self.s3_client:
                self._create_s3_client()
            
            logger.info(f"Downloading HTML report from s3://{self._s3_bucket}/{key}")
            
            response = self.s3_client.get_object(Bucket=self._s3_bucket, Key=key)
            html_content = response['Body'].read()
            
            # Write to file
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'wb') as f:
                f.write(html_content)
            
            logger.info(f"HTML report saved to: {output_file.absolute()}")
            return str(output_file.absolute())
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            if error_code == 'NoSuchKey':
                logger.error(
                    f"HTML report not found at s3://{self._s3_bucket}/{key}. "
                    f"The scan may not have generated an HTML report."
                )
            else:
                logger.error(f"S3 error downloading HTML report: [{error_code}] {e}")
            raise RuntimeError(f"Failed to download HTML report: {e}") from e
        except Exception as e:
            logger.error(f"Failed to download HTML report: {e}")
            raise RuntimeError(f"Failed to download HTML report: {e}") from e

    def job_cancel(self, job_id: str) -> None:
        """Cancel a running scan job
        
        Args:
            job_id: Job identifier
        """
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")

        try:
            self.kfp_client.terminate_run(job.kubeflow_run_id)
            job.status = "cancelled"
            logger.info(f"Cancelled Kubeflow run {job.kubeflow_run_id} for job {job_id}")
        except Exception as e:
            logger.error(f"Failed to cancel job: {str(e)}")
            raise RuntimeError(f"Failed to cancel job: {str(e)}") from e

    def wait_for_completion(
        self,
        job_id: str,
        poll_interval: int = 30,
        verbose: bool = True
    ) -> ScanJob:
        """
        Wait for job completion with simple status polling
        
        Args:
            job_id: Job identifier
            poll_interval: Seconds between status checks
            verbose: Whether to print status updates
            
        Returns:
            Completed ScanJob
        """
        status = self.job_status(job_id=job_id)
        
        if verbose:
            print(f"Waiting for job {job_id} to complete...")
            print(f"Monitor at: {self.kfp_config.pipelines_endpoint}/#/runs/details/{status.kubeflow_run_id}")
        
        while status.status in ["submitted", "in_progress"]:
            if verbose:
                elapsed = (datetime.now() - datetime.fromisoformat(status.created_at)).total_seconds()
                elapsed_str = f"{int(elapsed//60)}m {int(elapsed%60)}s"
                print(f"  Status: {status.status} (elapsed: {elapsed_str})")
            
            time.sleep(poll_interval)
            status = self.job_status(job_id=job_id)
        
        if verbose:
            if status.status == 'completed':
                print(f"Job completed successfully!")
            elif status.status == 'failed':
                print(f"Job failed!")
            elif status.status == 'cancelled':
                print(f"Job cancelled!")
        
        return status

