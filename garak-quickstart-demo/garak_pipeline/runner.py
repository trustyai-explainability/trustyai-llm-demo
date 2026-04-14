import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import kfp
import requests
from pydantic import BaseModel, Field

from llama_stack_provider_trustyai_garak.constants import DEFAULT_EVAL_THRESHOLD

from .config import (
    BenchmarkConfig,
    BenchmarkRegistry,
    EvalConfig,
    KubeflowConfig,
)
from .errors import GarakConfigError, GarakError, GarakValidationError
from .utils import check_and_create_bucket, clean_ssl_verify, create_s3_client

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

    Supports both plain garak scans and intents-based scans via the
    6-step ``evalhub_garak_pipeline``.

    Example:
        >>> runner = PipelineRunner(kfp_config)
        >>>
        >>> # Plain scan
        >>> job = runner.run_scan(EvalConfig(
        ...     model=ModelConfig(model_endpoint="https://m/v1", model_name="m"),
        ...     benchmark="quick",
        ... ))
        >>>
        >>> # Intents scan
        >>> job = runner.run_scan(EvalConfig(
        ...     model=ModelConfig(model_endpoint="https://m/v1", model_name="m"),
        ...     benchmark="intents",
        ...     intents_models={
        ...         "judge": IntentsModelConfig(url="http://j:8000/v1", name="j"),
        ...         "sdg":   IntentsModelConfig(url="http://s:8000/v1", name="s"),
        ...     },
        ...     policy_s3_key="policies/my-policy.csv",
        ... ))
    """

    def __init__(self, kfp_config: Optional[KubeflowConfig] = None):
        self.kfp_config = kfp_config or KubeflowConfig()
        self.scan_jobs: Dict[str, ScanJob] = {}
        self._s3_bucket: str = ""
        self._s3_prefix: str = ""
        self._parse_s3_config()
        self.s3_client = self._create_s3_client()

        self.benchmarks = BenchmarkRegistry()
        self.kfp_client = self._init_kfp_client()

    # ------------------------------------------------------------------
    # S3 helpers
    # ------------------------------------------------------------------

    def _parse_s3_config(self):
        """Parse S3 bucket and prefix from results_s3_prefix.

        Supported forms:
        - Not set / empty   → bucket resolved from Data Connection secret
        - ``garak-results`` → prefix only, bucket from secret
        - ``s3://bucket/prefix`` → explicit bucket + prefix
        - ``bucket/prefix`` → explicit bucket + prefix
        """
        results_s3_prefix = (self.kfp_config.results_s3_prefix or "").strip()
        if not results_s3_prefix:
            logger.info(
                "results_s3_prefix not set — bucket will be resolved "
                "from the Data Connection secret"
            )
            return

        has_scheme = results_s3_prefix.lower().startswith("s3://")
        if has_scheme:
            results_s3_prefix = results_s3_prefix[len("s3://"):]
        if not results_s3_prefix:
            return

        if "/" in results_s3_prefix or has_scheme:
            parts = results_s3_prefix.split("/", 1)
            self._s3_bucket = parts[0].strip()
            self._s3_prefix = parts[1].strip().rstrip("/") if len(parts) > 1 else ""
        else:
            self._s3_prefix = results_s3_prefix.rstrip("/")

        logger.info("Parsed S3 config — bucket: %s, prefix: %s", self._s3_bucket, self._s3_prefix)

    def _create_s3_client(self):
        """Create S3 client using credentials from the K8s Data Connection secret.

        Resolution order:
        - Credentials (key/secret/region): K8s secret -> env vars
        - Endpoint: env var -> K8s secret  (env var wins so users can
          override the cluster-internal URL with e.g. localhost via
          port-forward)
        """
        creds = self._read_s3_credentials_from_secret(
            self.kfp_config.s3_credentials_secret_name,
            self.kfp_config.namespace,
        )

        access_key = creds.get("access_key") or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = creds.get("secret_key") or os.getenv("AWS_SECRET_ACCESS_KEY")
        endpoint_url = os.getenv("AWS_S3_ENDPOINT") or creds.get("endpoint_url")
        region = creds.get("region") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")

        # Resolve bucket: results_s3_prefix > secret > env var
        if not self._s3_bucket:
            self._s3_bucket = creds.get("bucket") or os.getenv("AWS_S3_BUCKET", "")
            if self._s3_bucket:
                logger.info("Resolved S3 bucket from Data Connection secret: %s", self._s3_bucket)

        if not self._s3_bucket:
            raise GarakValidationError(
                "S3 bucket could not be determined. Either set "
                "KUBEFLOW_RESULTS_S3_PREFIX (e.g. 'mybucket/prefix') "
                "or ensure AWS_S3_BUCKET is in the Data Connection secret."
            )

        if not access_key or not secret_key:
            logger.warning(
                "S3 credentials not found in K8s secret '%s' or environment. "
                "Ensure the Data Connection secret exists and is readable, "
                "or set AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.",
                self.kfp_config.s3_credentials_secret_name,
            )

        self.s3_client = create_s3_client(
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            verify_ssl=self.kfp_config.verify_ssl,
        )
        check_and_create_bucket(self.s3_client, self._s3_bucket)
        return self.s3_client

    @staticmethod
    def _read_s3_credentials_from_secret(secret_name: str, namespace: str) -> dict:
        """Read S3 credentials from the Data Connection K8s secret.

        Returns a dict with keys: access_key, secret_key, region,
        bucket, endpoint_url.  Returns empty dict on any failure
        (missing secret, no RBAC, not in cluster, etc.).
        """
        import base64

        try:
            from kubernetes import client as k8s_client, config as k8s_config

            try:
                k8s_config.load_incluster_config()
            except Exception:
                k8s_config.load_kube_config()
            v1 = k8s_client.CoreV1Api()
            secret = v1.read_namespaced_secret(secret_name, namespace)
            data = secret.data or {}

            def _decode(key: str) -> str:
                val = data.get(key, "")
                return base64.b64decode(val).decode() if val else ""

            result = {
                "access_key": _decode("AWS_ACCESS_KEY_ID"),
                "secret_key": _decode("AWS_SECRET_ACCESS_KEY"),
                "region": _decode("AWS_DEFAULT_REGION"),
                "bucket": _decode("AWS_S3_BUCKET"),
                "endpoint_url": _decode("AWS_S3_ENDPOINT"),
            }
            logger.info(
                "Read S3 credentials from secret %s/%s (bucket=%s, endpoint=%s)",
                namespace,
                secret_name,
                result.get("bucket", ""),
                result.get("endpoint_url", ""),
            )
            return result
        except Exception as exc:
            logger.debug(
                "Could not read S3 credentials from secret %s/%s: %s — "
                "falling back to environment variables",
                namespace,
                secret_name,
                exc,
            )
            return {}

    # ------------------------------------------------------------------
    # KFP init
    # ------------------------------------------------------------------

    def _init_kfp_client(self) -> kfp.Client:
        """Initialize KFP client with OpenShift authentication."""
        try:
            token = self.kfp_config.pipelines_api_token or self._get_token()
            if not token:
                raise GarakError(
                    "No authentication token found. "
                    "Please check your KFP API token or run `oc login` and try again."
                )
            response = requests.get(
                f"{self.kfp_config.pipelines_endpoint}/apis/v2beta1/healthz",
                headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
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
                f"Failed to connect to KFP at {self.kfp_config.pipelines_endpoint}, "
                "do you need a new token?"
            ) from e
        except Exception as e:
            raise GarakError(f"Failed to initialize KFP client: {e}") from e

    def _get_token(self) -> str:
        try:
            from kubernetes.client.configuration import Configuration
            from kubernetes.client.exceptions import ApiException
            from kubernetes.config.config_exception import ConfigException
            from kubernetes.config.kube_config import load_kube_config

            config = Configuration()
            load_kube_config(client_configuration=config)
            return config.api_key["authorization"].split(" ")[-1]
        except Exception as e:
            raise GarakError(f"Could not obtain Kubernetes token: {e}") from e

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_scan(self, config: EvalConfig) -> ScanJob:
        """Run a Garak security scan (plain or intents)."""
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
            created_at=created_at,
        )

        kubeflow_run_id = self._submit_to_kubeflow(config, benchmark_config, benchmark_id, job_id)
        job.kubeflow_run_id = kubeflow_run_id
        self.scan_jobs[job_id] = job

        logger.info(
            "Submitted scan job %s for model '%s' with benchmark '%s' (run ID: %s)",
            job_id,
            config.model.model_name,
            benchmark_id,
            kubeflow_run_id,
        )
        return job

    def register_benchmark(self, benchmark_id: str, config: BenchmarkConfig, overwrite: bool = False) -> None:
        self.benchmarks.register(benchmark_id, config, overwrite=overwrite)
        logger.info("Registered benchmark '%s': %s", benchmark_id, config.name)

    def list_benchmarks(self, include_details: bool = False) -> Dict[str, Dict]:
        if include_details:
            return {bid: cfg.model_dump() for bid, cfg in self.benchmarks}
        return self.benchmarks.list_with_info()

    def unregister_benchmark(self, benchmark_id: str) -> bool:
        if self.benchmarks.unregister(benchmark_id):
            logger.info("Removed benchmark '%s'", benchmark_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Config building — reuses core modules from the main package
    # ------------------------------------------------------------------

    def _build_config(
        self,
        eval_config: EvalConfig,
        benchmark_config: BenchmarkConfig,
        benchmark_id: str,
    ) -> tuple[str, dict[str, Any]]:
        """Build the ``config_json`` and ``intents_params`` for the pipeline.

        Returns:
            (config_json, intents_params)
        """
        from llama_stack_provider_trustyai_garak.core.command_builder import build_generator_options
        from llama_stack_provider_trustyai_garak.core.config_resolution import (
            build_effective_garak_config,
            resolve_scan_profile,
            resolve_timeout_seconds,
        )
        from llama_stack_provider_trustyai_garak.constants import (
            DEFAULT_EVAL_THRESHOLD,
            DEFAULT_TIMEOUT,
        )
        from llama_stack_provider_trustyai_garak.garak_command_config import GarakCommandConfig

        profile = resolve_scan_profile(benchmark_id)

        # Flatten BenchmarkConfig overrides (custom benchmarks only).
        bc: dict[str, Any] = {}
        if benchmark_config.probes:
            bc["probes"] = benchmark_config.probes
        if benchmark_config.taxonomy_filters:
            bc["probe_tags"] = ",".join(benchmark_config.taxonomy_filters)
        if benchmark_config.taxonomy:
            bc["taxonomy"] = benchmark_config.taxonomy

        garak_config: GarakCommandConfig = build_effective_garak_config(
            benchmark_config=bc,
            profile=profile,
        )

        # Resolve timeout and eval_threshold the same way the adapter does:
        # user override (EvalConfig) > profile > package default
        self._resolved_timeout = resolve_timeout_seconds(
            {"timeout": eval_config.timeout} if eval_config.timeout is not None else {},
            profile,
            default_timeout=DEFAULT_TIMEOUT,
        )
        self._resolved_eval_threshold = float(
            garak_config.to_dict().get("run", {}).get("eval_threshold", DEFAULT_EVAL_THRESHOLD)
        )

        # Set generator from EvalConfig.model
        endpoint = eval_config.model.model_endpoint.rstrip("/")
        garak_config.plugins.generators = build_generator_options(
            model_endpoint=endpoint,
            model_name=eval_config.model.model_name,
            api_key=eval_config.model.api_key or "__FROM_ENV__",
            extra_params=eval_config.sampling_params or None,
        )
        garak_config.plugins.target_type = "openai.OpenAICompatible"
        garak_config.plugins.target_name = eval_config.model.model_name

        # Only override generations / parallel_attempts when the user
        # explicitly set them (i.e. they differ from the EvalConfig defaults).
        # This preserves the profile's values (e.g. intents → generations=2).
        _EVAL_DEFAULT_GENERATIONS = 1
        _EVAL_DEFAULT_PARALLEL = 8
        if eval_config.generations != _EVAL_DEFAULT_GENERATIONS:
            garak_config.run.generations = eval_config.generations
        if eval_config.parallel_attempts != _EVAL_DEFAULT_PARALLEL:
            garak_config.run.parallel_attempts = eval_config.parallel_attempts

        art_intents = benchmark_config.art_intents
        intents_params: dict[str, Any] = {
            "art_intents": art_intents,
            "policy_s3_key": eval_config.policy_s3_key,
            "policy_format": eval_config.policy_format,
            "intents_s3_key": eval_config.intents_s3_key,
            "intents_format": eval_config.intents_format,
            "sdg_flow_id": eval_config.sdg_flow_id,
            "sdg_max_concurrency": eval_config.sdg_max_concurrency,
            "sdg_num_samples": eval_config.sdg_num_samples,
            "sdg_max_tokens": eval_config.sdg_max_tokens,
        }

        if art_intents:
            sdg_params = self._apply_intents_model_overlay(
                garak_config, eval_config, profile
            )
            intents_params.update(sdg_params)

        from llama_stack_provider_trustyai_garak.core.pipeline_steps import redact_api_keys

        config_dict = garak_config.to_dict(exclude_none=True)
        config_json = json.dumps(redact_api_keys(config_dict))
        return config_json, intents_params

    # ------------------------------------------------------------------
    # Intents model overlay (extracted from garak_adapter logic)
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_intents_model_overlay(
        garak_config: Any,
        eval_config: EvalConfig,
        profile: dict[str, Any],
    ) -> dict[str, str]:
        """Apply judge/attacker/evaluator/SDG endpoints onto the garak config.

        Returns dict with ``sdg_model`` and ``sdg_api_base``.
        """
        models = eval_config.intents_models or {}

        judge_cfg = models.get("judge")
        attacker_cfg = models.get("attacker")
        evaluator_cfg = models.get("evaluator")
        sdg_cfg = models.get("sdg")

        provided = {
            role: cfg
            for role, cfg in [("judge", judge_cfg), ("attacker", attacker_cfg), ("evaluator", evaluator_cfg)]
            if cfg and cfg.url
        }

        if len(provided) == 0:
            raise ValueError(
                "Intents benchmark requires intents_models with at least judge endpoint."
            )
        if len(provided) == 2:
            missing = {"judge", "attacker", "evaluator"} - set(provided)
            raise ValueError(
                f"Ambiguous intents_models: {', '.join(sorted(provided))} "
                f"configured but {', '.join(sorted(missing))} missing. "
                f"Provide all three, or exactly one to use for all roles."
            )

        # 1 provided -> broadcast to all roles
        if len(provided) == 1:
            base = next(iter(provided.values()))
            if not judge_cfg:
                judge_cfg = base
            if not attacker_cfg:
                attacker_cfg = base
            if not evaluator_cfg:
                evaluator_cfg = base

        _PLACEHOLDER = "__FROM_ENV__"

        plugins = garak_config.plugins
        plugins.detectors = plugins.detectors or {}
        existing_judge = plugins.detectors.get("judge", {})
        existing_judge["detector_model_type"] = existing_judge.get("detector_model_type") or "openai.OpenAICompatible"
        existing_judge["detector_model_name"] = existing_judge.get("detector_model_name") or judge_cfg.name
        det_cfg = existing_judge.get("detector_model_config", {})
        det_cfg["uri"] = det_cfg.get("uri") or judge_cfg.url
        det_cfg["api_key"] = _PLACEHOLDER
        existing_judge["detector_model_config"] = det_cfg
        plugins.detectors["judge"] = existing_judge

        if plugins.probes and plugins.probes.get("tap"):
            tap = plugins.probes["tap"].get("TAPIntent", {})
            if isinstance(tap, dict):
                tap["attack_model_name"] = tap.get("attack_model_name") or attacker_cfg.name
                atk_cfg = tap.get("attack_model_config", {})
                atk_cfg.setdefault("max_tokens", 500)
                atk_cfg["uri"] = atk_cfg.get("uri") or attacker_cfg.url
                atk_cfg["api_key"] = _PLACEHOLDER
                tap["attack_model_config"] = atk_cfg

                tap["evaluator_model_name"] = tap.get("evaluator_model_name") or evaluator_cfg.name
                eval_cfg = tap.get("evaluator_model_config", {})
                eval_cfg.setdefault("max_tokens", 10)
                eval_cfg.setdefault("temperature", 0.0)
                eval_cfg["uri"] = eval_cfg.get("uri") or evaluator_cfg.url
                eval_cfg["api_key"] = _PLACEHOLDER
                tap["evaluator_model_config"] = eval_cfg

                plugins.probes["tap"]["TAPIntent"] = tap

        sdg_params: dict[str, str] = {"sdg_model": "", "sdg_api_base": ""}
        if sdg_cfg and sdg_cfg.url and sdg_cfg.name:
            sdg_params["sdg_model"] = sdg_cfg.name
            sdg_params["sdg_api_base"] = sdg_cfg.url

        return sdg_params

    # ------------------------------------------------------------------
    # KFP submission
    # ------------------------------------------------------------------

    def _submit_to_kubeflow(
        self,
        eval_config: EvalConfig,
        benchmark_config: BenchmarkConfig,
        benchmark_id: str,
        job_id: str,
    ) -> str:
        """Submit the 6-step evalhub_garak_pipeline to KFP."""
        from llama_stack_provider_trustyai_garak.evalhub.kfp_pipeline import evalhub_garak_pipeline

        config_json, intents_params = self._build_config(eval_config, benchmark_config, benchmark_id)

        # Validate intents SDG requirements (same checks as the eval-hub adapter)
        if intents_params.get("art_intents"):
            if intents_params.get("policy_s3_key") and intents_params.get("intents_s3_key"):
                raise GarakValidationError(
                    "policy_s3_key and intents_s3_key are mutually exclusive. "
                    "Provide a taxonomy for SDG (policy_s3_key) OR "
                    "pre-generated prompts (intents_s3_key), not both."
                )
            if not intents_params.get("intents_s3_key"):
                if not intents_params.get("sdg_model"):
                    raise GarakValidationError(
                        "Intents benchmark requires sdg_model for prompt "
                        "generation when intents_s3_key is not provided. "
                        "Set intents_models.sdg in your EvalConfig."
                    )
                if not intents_params.get("sdg_api_base"):
                    raise GarakValidationError(
                        "Intents benchmark requires sdg_api_base for prompt "
                        "generation when intents_s3_key is not provided. "
                        "Set intents_models.sdg.url in your EvalConfig."
                    )

        eval_threshold = self._resolved_eval_threshold
        timeout = self._resolved_timeout

        s3_prefix = f"{self._s3_prefix}/{job_id}" if self._s3_prefix else job_id
        run_name = f"garak-{benchmark_id}-{job_id[:8]}"

        arguments: dict[str, Any] = {
            "config_json": config_json,
            "s3_prefix": s3_prefix,
            "timeout_seconds": timeout,
            "s3_secret_name": self.kfp_config.s3_credentials_secret_name,
            "model_auth_secret_name": eval_config.model_auth_secret_name or "model-auth",
            "eval_threshold": eval_threshold,
            "hf_cache_path": eval_config.hf_cache_path or "",
            # Intents params
            "art_intents": intents_params["art_intents"],
            "policy_s3_key": intents_params.get("policy_s3_key", ""),
            "policy_format": intents_params.get("policy_format", "csv"),
            "intents_s3_key": intents_params.get("intents_s3_key", ""),
            "intents_format": intents_params.get("intents_format", "csv"),
            "sdg_model": intents_params.get("sdg_model", ""),
            "sdg_api_base": intents_params.get("sdg_api_base", ""),
            "sdg_flow_id": intents_params.get("sdg_flow_id", eval_config.sdg_flow_id),
            "sdg_max_concurrency": intents_params.get("sdg_max_concurrency", eval_config.sdg_max_concurrency),
            "sdg_num_samples": intents_params.get("sdg_num_samples", eval_config.sdg_num_samples),
            "sdg_max_tokens": intents_params.get("sdg_max_tokens", eval_config.sdg_max_tokens),
        }

        run_result = self.kfp_client.create_run_from_pipeline_func(
            pipeline_func=evalhub_garak_pipeline,
            arguments=arguments,
            run_name=run_name,
            namespace=self.kfp_config.namespace,
            experiment_name=self.kfp_config.experiment_name,
        )
        return run_result.run_id

    # ------------------------------------------------------------------
    # Job lifecycle
    # ------------------------------------------------------------------

    def job_status(self, job_id: str) -> ScanJob:
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")
        try:
            run_detail = self.kfp_client.get_run(job.kubeflow_run_id)
            if run_detail.state == "FAILED":
                job.status = "failed"
            elif run_detail.state == "SUCCEEDED":
                job.status = "completed"
                self._fetch_results(job)
            elif run_detail.state in ("RUNNING", "PENDING"):
                job.status = "in_progress"
            elif run_detail.state == "CANCELED":
                job.status = "cancelled"
            else:
                job.status = "unknown"
        except Exception as e:
            logger.error("Failed to get job status: %s", e)
        return job

    def _fetch_results(self, job: ScanJob):
        """Fetch and parse results from S3."""
        if job.result:
            return

        from llama_stack_provider_trustyai_garak.result_utils import (
            combine_parsed_results,
            parse_aggregated_from_avid_content,
            parse_digest_from_report_content,
            parse_generations_from_report_content,
        )

        s3_prefix = f"{self._s3_prefix}/{job.job_id}" if self._s3_prefix else job.job_id
        logger.debug(
            "Fetching results — bucket=%s, prefix=%s", self._s3_bucket, s3_prefix
        )

        def _download_text(key: str) -> str:
            try:
                resp = self.s3_client.get_object(Bucket=self._s3_bucket, Key=key)
                return resp["Body"].read().decode("utf-8")
            except Exception:
                logger.warning(
                    "Failed to download s3://%s/%s", self._s3_bucket, key, exc_info=True
                )
                return ""

        report_key = f"{s3_prefix}/scan.report.jsonl"
        report_content = _download_text(report_key)
        if not report_content.strip():
            logger.warning(
                "Report file empty or not found for job %s at s3://%s/%s",
                job.job_id, self._s3_bucket, report_key,
            )
            return

        avid_content = _download_text(f"{s3_prefix}/scan.avid.jsonl")

        benchmark_cfg = self.benchmarks.get(job.benchmark_id)
        art_intents = benchmark_cfg.art_intents if benchmark_cfg else False
        eval_threshold = getattr(self, "_resolved_eval_threshold", DEFAULT_EVAL_THRESHOLD)

        generations, score_rows_by_probe, raw_entries_by_probe = (
            parse_generations_from_report_content(report_content, eval_threshold)
        )
        aggregated_by_probe = parse_aggregated_from_avid_content(avid_content)
        digest = parse_digest_from_report_content(report_content)

        combined = combine_parsed_results(
            generations,
            score_rows_by_probe,
            aggregated_by_probe,
            eval_threshold,
            digest,
            art_intents=art_intents,
            raw_entries_by_probe=raw_entries_by_probe,
        )
        job.result = combined
        logger.info("Parsed results for job %s", job.job_id)

    def job_result(self, job_id: str) -> Optional[Dict]:
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")
        if job.status == "completed":
            if not job.result:
                self._fetch_results(job)
            return job.result
        elif job.status == "failed":
            raise RuntimeError(f"Job {job_id} failed")
        return None

    def download_html_report(self, job_id: str, output_path: Optional[str] = None) -> str:
        """Download the HTML report from S3.

        For intents benchmarks the report is ``scan.intents.html``
        (generated by ``write_kfp_outputs``).  If that file is missing
        in S3 (e.g. the KFP output step failed), a local fallback
        generates the ART report from ``scan.report.jsonl``.

        For non-intents benchmarks the report is ``scan.report.html``
        (written by garak itself).
        """
        from botocore.exceptions import ClientError

        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")

        s3_prefix = f"{self._s3_prefix}/{job_id}" if self._s3_prefix else job_id

        benchmark_cfg = self.benchmarks.get(job.benchmark_id)
        art_intents = benchmark_cfg.art_intents if benchmark_cfg else False

        html_key = f"{s3_prefix}/scan.intents.html" if art_intents else f"{s3_prefix}/scan.report.html"

        if output_path is None:
            output_path = f"scan_report_{job_id}.html"

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        try:
            response = self.s3_client.get_object(Bucket=self._s3_bucket, Key=html_key)
            out.write_bytes(response["Body"].read())
            logger.info("HTML report saved to: %s", out.absolute())
            return str(out.absolute())
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code != "NoSuchKey":
                raise RuntimeError(f"Failed to download HTML report: {e}") from e

            if not art_intents:
                raise RuntimeError(
                    f"HTML report not found at s3://{self._s3_bucket}/{html_key}"
                ) from e

            # Fallback: generate ART intents report locally from report.jsonl
            logger.warning(
                "scan.intents.html not in S3, generating locally from report.jsonl"
            )
            report_key = f"{s3_prefix}/scan.report.jsonl"
            try:
                resp = self.s3_client.get_object(Bucket=self._s3_bucket, Key=report_key)
                report_content = resp["Body"].read().decode("utf-8")
            except Exception as dl_err:
                raise RuntimeError(
                    f"Could not download report.jsonl for local HTML generation: {dl_err}"
                ) from dl_err

            from llama_stack_provider_trustyai_garak.result_utils import generate_art_report

            html_content = generate_art_report(report_content)
            if not html_content:
                raise RuntimeError("generate_art_report returned empty content")
            out.write_text(html_content)
            logger.info("Generated ART report locally, saved to: %s", out.absolute())
            return str(out.absolute())

    def job_cancel(self, job_id: str) -> None:
        if (job := self.scan_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")
        try:
            self.kfp_client.terminate_run(job.kubeflow_run_id)
            job.status = "cancelled"
            logger.info("Cancelled KFP run %s for job %s", job.kubeflow_run_id, job_id)
        except Exception as e:
            raise RuntimeError(f"Failed to cancel job: {e}") from e

    def wait_for_completion(
        self,
        job_id: str,
        poll_interval: int = 30,
        verbose: bool = True,
    ) -> ScanJob:
        status = self.job_status(job_id=job_id)
        if verbose:
            print(f"Waiting for job {job_id} to complete...")
            print(f"Monitor at: {self.kfp_config.pipelines_endpoint}/#/runs/details/{status.kubeflow_run_id}")

        while status.status in ("submitted", "in_progress"):
            if verbose:
                elapsed = (datetime.now() - datetime.fromisoformat(status.created_at)).total_seconds()
                print(f"  Status: {status.status} (elapsed: {int(elapsed // 60)}m {int(elapsed % 60)}s)")
            time.sleep(poll_interval)
            status = self.job_status(job_id=job_id)

        if verbose:
            if status.status == "completed":
                print("Job completed successfully!")
            elif status.status == "failed":
                print("Job failed!")
            elif status.status == "cancelled":
                print("Job cancelled!")

        return status
