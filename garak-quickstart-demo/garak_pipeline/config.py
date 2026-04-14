"""Configuration for standalone Garak KFP pipeline"""

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict, model_validator
from pydantic_settings import BaseSettings

from llama_stack_provider_trustyai_garak.constants import (
    DEFAULT_SDG_FLOW_ID,
    DEFAULT_SDG_MAX_CONCURRENCY,
    DEFAULT_SDG_MAX_TOKENS,
    DEFAULT_SDG_NUM_SAMPLES,
)


class BenchmarkConfig(BaseModel):
    """Configuration for a Garak benchmark.

    For **predefined** benchmarks (``quick``, ``intents``, etc.) the actual
    probe/taxonomy/timeout/eval_threshold configuration lives in the main
    package's ``FRAMEWORK_PROFILES`` / ``SCAN_PROFILES``  — this model only
    carries user-facing metadata and the ``art_intents`` flag.

    For **custom** benchmarks users can specify ``probes`` or
    ``taxonomy_filters`` to override the profile.

    Example:
        # Custom probe-based benchmark
        benchmark = BenchmarkConfig(
            name="My Custom Scan",
            probes=["dan.DAN", "encoding.InjectBase64"],
        )

        # Custom taxonomy-based benchmark
        benchmark = BenchmarkConfig(
            name="OWASP Scan",
            taxonomy_filters=["owasp:llm01", "owasp:llm02"],
        )
    """

    name: str = Field(description="Human-readable name for the benchmark")

    description: Optional[str] = Field(
        default=None,
        description="Description of what this benchmark tests",
    )

    documentation: Optional[str] = Field(
        default=None,
        description="URL to documentation for this benchmark",
    )

    art_intents: bool = Field(
        default=False,
        description="When True, this benchmark runs the intents pipeline "
        "(probes are configured by the pipeline itself, not by the user).",
    )

    # --- Optional overrides (custom benchmarks only) ---

    probes: Optional[List[str]] = Field(
        default=None,
        description="List of garak probes to run (custom benchmarks only). "
        "Predefined benchmarks get probes from the main package profile.",
    )

    taxonomy_filters: Optional[List[str]] = Field(
        default=None,
        description="Taxonomy filters for probe selection (custom benchmarks only).",
    )

    taxonomy: Optional[str] = Field(
        default=None,
        description="MISP top-level taxonomy for grouping probes while reporting",
        examples=["owasp", "avid-effect"],
    )

    seed: Optional[int] = Field(default=None, description="Random seed for reproducible results")
    detectors: Optional[List[str]] = Field(default=None, description="Specific detectors to use")
    extended_detectors: Optional[List[str]] = Field(default=None, description="Additional detectors")
    detector_options: Optional[Dict[str, Any]] = Field(default=None, description="Detector options")
    probe_options: Optional[Dict[str, Any]] = Field(default=None, description="Probe options")
    buffs: Optional[List[str]] = Field(default=None, description="Input transformation buffs")
    buff_options: Optional[Dict[str, Any]] = Field(default=None, description="Buff options")
    harness_options: Optional[Dict[str, Any]] = Field(default=None, description="Harness options")
    deprefix: Optional[str] = Field(default=None, description="Prefix to remove from model outputs")
    generate_autodan: Optional[str] = Field(default=None, description="AutoDAN config")


PREDEFINED_BENCHMARKS: Dict[str, BenchmarkConfig] = {
    "quick": BenchmarkConfig(
        name="Quick Scan",
        description="Quick scan with a small probe set for testing",
    ),
    "owasp_llm_top10": BenchmarkConfig(
        name="OWASP LLM Top 10",
        description="OWASP Top 10 for Large Language Model Applications",
        documentation="https://genai.owasp.org/llm-top-10/",
    ),
    "avid": BenchmarkConfig(
        name="AVID Taxonomy",
        description="AI Vulnerability Database - All vulnerabilities",
        documentation="https://docs.avidml.org/taxonomy/effect-sep-view/",
    ),
    "avid_security": BenchmarkConfig(
        name="AVID Security",
        description="AI Vulnerability Database - Security vulnerabilities",
        documentation="https://docs.avidml.org/taxonomy/effect-sep-view/security",
    ),
    "avid_ethics": BenchmarkConfig(
        name="AVID Ethics",
        description="AI Vulnerability Database - Ethical concerns",
        documentation="https://docs.avidml.org/taxonomy/effect-sep-view/ethics",
    ),
    "avid_performance": BenchmarkConfig(
        name="AVID Performance",
        description="AI Vulnerability Database - Performance issues",
        documentation="https://docs.avidml.org/taxonomy/effect-sep-view/performance",
    ),
    "quality": BenchmarkConfig(
        name="Quality Issues",
        description="Common quality issues - Violence, Profanity, Toxicity, Hate Speech, Integrity",
    ),
    "cwe": BenchmarkConfig(
        name="Common Weakness Enumeration",
        description="CWE - Software security weaknesses",
        documentation="https://cwe.mitre.org/",
    ),
    "intents": BenchmarkConfig(
        name="Intents-based Risk Assessment",
        description="Risk assessment with custom intent typology using TAPIntent probes, "
        "MulticlassJudge detectors, and SDG-generated adversarial prompts",
        art_intents=True,
    ),
}


class BenchmarkRegistry:
    """
    Unified registry for all benchmarks - predefined and custom.
    
    A benchmark is just a BenchmarkConfig. The only difference between 
    "predefined" and "custom" is who defines them (us vs. users).
    
    Example:
        >>> registry = BenchmarkRegistry()
        >>> 
        >>> # Use predefined
        >>> quick = registry.get("quick")
        >>> 
        >>> # Register custom (same as predefined, just user-defined)
        >>> registry.register("my_scan", BenchmarkConfig(
        ...     name="My Scan",
        ...     probes=["dan.DAN"],
        ...     timeout=1800,
        ... ))
        >>> 
        >>> # List all
        >>> for name in registry.list():
        ...     print(name)
    """
    
    def __init__(self):
        # All benchmarks stored uniformly as BenchmarkConfig
        self._benchmarks: Dict[str, BenchmarkConfig] = dict(PREDEFINED_BENCHMARKS)
        self._predefined_ids: set = set(PREDEFINED_BENCHMARKS.keys())
    
    def get(self, benchmark_id: str) -> Optional[BenchmarkConfig]:
        """Get a benchmark by ID."""
        return self._benchmarks.get(benchmark_id)
    
    def register(
        self, 
        benchmark_id: str, 
        config: BenchmarkConfig,
        overwrite: bool = False
    ) -> None:
        """
        Register a benchmark.
        
        Args:
            benchmark_id: Unique identifier
            config: The benchmark configuration
            overwrite: Allow overwriting existing benchmarks
        """
        if benchmark_id in self._benchmarks and not overwrite:
            raise ValueError(
                f"Benchmark '{benchmark_id}' already exists. "
                f"Use overwrite=True to replace it."
            )
        self._benchmarks[benchmark_id] = config
    
    def unregister(self, benchmark_id: str) -> bool:
        """
        Remove a benchmark.
        
        Note: Predefined benchmarks can also be removed if desired.
        """
        if benchmark_id in self._benchmarks:
            del self._benchmarks[benchmark_id]
            self._predefined_ids.discard(benchmark_id)
            return True
        return False
    
    def list(self) -> List[str]:
        """List all benchmark IDs."""
        return list(self._benchmarks.keys())
    
    def list_with_info(self) -> Dict[str, Dict[str, Any]]:
        """List all benchmarks with summary info."""
        result = {}
        for benchmark_id, config in self._benchmarks.items():
            btype = "intents" if config.art_intents else (
                "taxonomy" if config.taxonomy_filters else "probes"
            )
            result[benchmark_id] = {
                "name": config.name,
                "description": config.description or "",
                "type": btype,
                "is_predefined": benchmark_id in self._predefined_ids,
            }
        return result
    
    def exists(self, benchmark_id: str) -> bool:
        """Check if a benchmark exists."""
        return benchmark_id in self._benchmarks
    
    def is_predefined(self, benchmark_id: str) -> bool:
        """Check if a benchmark is one of the predefined ones."""
        return benchmark_id in self._predefined_ids
    
    def __contains__(self, benchmark_id: str) -> bool:
        return self.exists(benchmark_id)
    
    def __len__(self) -> int:
        return len(self._benchmarks)
    
    def __iter__(self):
        return iter(self._benchmarks.items())



class KubeflowConfig(BaseSettings):
    """Configuration for Kubeflow remote execution.

    Pre-requisites:
    - RHOAI operator with the ``trustyai`` component enabled — the
      productized base image is resolved automatically from the
      operator's ConfigMap (no need to specify ``base_image``).
    - Data Science Pipelines (KFP) installed with an S3-backed Data
      Connection.  The same K8s secret (``s3_credentials_secret_name``)
      is used both by KFP pods (via ``use_secret_as_env``) and by the
      client to download results, keeping credentials in a single place.
    """

    results_s3_prefix: Optional[str] = Field(
        default=None,
        description="Where to read results from S3. Supported forms: "
        "(1) omitted — bucket auto-resolved from Data Connection secret, "
        "artifacts at {job_id}/ in that bucket; "
        "(2) 'garak-results' — prefix only, bucket from secret, "
        "artifacts at garak-results/{job_id}/; "
        "(3) 's3://bucket/prefix' or 'bucket/prefix' — explicit bucket + prefix. "
        "WARNING: if you specify a bucket, it MUST match the AWS_S3_BUCKET "
        "in the Data Connection secret, because the KFP pipeline always "
        "writes to that bucket. A mismatch means the runner won't find "
        "the results. Prefer form (1) or (2) to avoid this.",
    )

    pipelines_endpoint: str = Field(
        description="Kubeflow Pipelines API endpoint URL"
    )

    namespace: str = Field(
        description="Kubeflow namespace for pipeline execution"
    )

    base_image: Optional[str] = Field(
        default=None,
        description="Override KFP component base image.  When None the "
        "image is resolved from the TrustyAI operator ConfigMap "
        "(RHOAI) or the KUBEFLOW_GARAK_BASE_IMAGE env var.",
    )

    s3_credentials_secret_name: str = Field(
        default="aws-connection-pipeline-artifacts",
        description="K8s Data-Connection secret with S3 credentials.  "
        "Used by KFP pods *and* by the client to fetch results — "
        "single source of truth for S3 access.",
    )

    experiment_name: str = Field(
        default="garak-demo",
        description="Kubeflow experiment name for pipeline execution"
    )

    pipelines_api_token: Optional[str] = Field(
        description="Kubeflow Pipelines API token with access to submit pipelines",
        default=None,
    )

    verify_ssl: bool | str = Field(
        default=True,
        description="Whether to verify SSL certificates. Can be a boolean or a path."
    )

    model_config = ConfigDict(env_file=".env", env_prefix="KUBEFLOW_", extra="ignore")


class ModelConfig(BaseModel):
    """Configuration for model serving endpoint"""

    model_endpoint: str = Field(
        description="Model serving endpoint URL (OpenAI-compatible API)"
    )

    model_name: str = Field(
        description="Model name/identifier"
    )

    api_key: Optional[str] = Field(
        default=None,
        description="API key for the model serving endpoint"
    )

class IntentsModelConfig(BaseModel):
    """Endpoint for one of the intents-pipeline auxiliary models."""

    url: str = Field(description="OpenAI-compatible endpoint URL")
    name: str = Field(description="Model name at that endpoint")
    api_key: str = Field(
        default="__FROM_ENV__",
        description="API key (use __FROM_ENV__ for K8s Secret injection)",
    )


class EvalConfig(BaseModel):
    """
    Everything needed to run a security scan.

    Combines model, benchmark, and scan parameters into one config.

    Example:
        # Using a predefined benchmark
        config = EvalConfig(
            model=ModelConfig(
                model_endpoint="https://your-model/v1",
                model_name="gpt-4",
                api_key="your-api-key",
            ),
            benchmark="quick",
            sampling_params={"temperature": 0.5, "max_tokens": 100},
        )

        # Intents scan
        config = EvalConfig(
            model=ModelConfig(
                model_endpoint="https://your-model/v1",
                model_name="gpt-4",
                api_key="your-api-key",
            ),
            benchmark="intents",
            intents_models={
                "judge": IntentsModelConfig(url="http://judge:8000/v1", name="judge"),
                "sdg":   IntentsModelConfig(url="http://sdg:8000/v1",   name="sdg"),
            },
            policy_s3_key="policies/my-policy.csv",
            hf_cache_path="s3://hf-models/models/",
        )
    """

    model: ModelConfig = Field(description="Model configuration")

    benchmark: str | BenchmarkConfig = Field(description="Benchmark configuration")

    # Sampling parameters
    sampling_params: Dict[str, Any] = Field(
        default={},
        description="Sampling parameters for the model",
    )

    # Execution parameters
    timeout: Optional[int] = Field(
        default=None,
        description="Override timeout in seconds (0 = no limit). "
        "When None, the value from the main package profile is used.",
    )

    parallel_attempts: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Number of parallel probe attempts (1-32)",
    )

    generations: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Number of generations per probe (1-10)",
    )

    eval_threshold: Optional[float] = Field(
        default=None,
        description="Override vulnerability threshold (0-1). "
        "When None, the value from the main package profile is used.",
    )

    max_retries: int = Field(default=3, ge=1, description="Retry attempts on failure")

    use_gpu: bool = Field(default=False, description="Request GPU resources")

    # --- Intents-specific fields ---

    intents_models: Optional[Dict[str, IntentsModelConfig]] = Field(
        default=None,
        description="Auxiliary model endpoints keyed by role: "
        "'judge', 'attacker', 'evaluator', 'sdg'. "
        "Required when benchmark is 'intents'.",
    )

    model_auth_secret_name: Optional[str] = Field(
        default=None,
        description="K8s Secret name containing model API keys "
        "(mounted as env vars in KFP pods).",
    )

    policy_s3_key: str = Field(
        default="",
        description="S3 key for the policy CSV used by the intents pipeline.",
    )
    intents_s3_key: str = Field(
        default="",
        description="S3 key for the intents CSV.",
    )
    policy_format: str = Field(
        default="csv",
        description="Format of the policy file ('csv' or 'json').",
    )
    intents_format: str = Field(
        default="csv",
        description="Format of the intents file ('csv' or 'json').",
    )

    sdg_flow_id: str = Field(
        default=DEFAULT_SDG_FLOW_ID,
        description="SDG-hub flow identifier.",
    )
    sdg_max_concurrency: int = Field(
        default=DEFAULT_SDG_MAX_CONCURRENCY,
        description="Max concurrent SDG requests.",
    )
    sdg_num_samples: int = Field(
        default=DEFAULT_SDG_NUM_SAMPLES,
        description="RowMultiplierBlock num_samples (0 = use flow default).",
    )
    sdg_max_tokens: int = Field(
        default=DEFAULT_SDG_MAX_TOKENS,
        description="LLMChatBlock max_tokens (0 = use flow default).",
    )

    hf_cache_path: str = Field(
        default="",
        description="S3 URI or prefix pointing to pre-downloaded HuggingFace "
        "translation models.  Required on disconnected clusters.",
    )

    @model_validator(mode="after")
    def validate_benchmark_source(self):
        """Ensure benchmark is specified either by ID or inline definition."""
        if not isinstance(self.benchmark, (str, BenchmarkConfig)):
            raise ValueError("Specify valid benchmark configuration.")
        return self


__all__ = [
    "BenchmarkConfig",
    "BenchmarkRegistry",
    "IntentsModelConfig",
    "PREDEFINED_BENCHMARKS",
    "EvalConfig",
    "KubeflowConfig",
    "ModelConfig",
]
