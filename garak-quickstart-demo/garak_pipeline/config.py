"""Configuration for standalone Garak KFP pipeline"""

from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from pydantic_settings import BaseSettings


class BenchmarkConfig(BaseModel):
    """Configuration for a custom Garak benchmark.
    
    Users can define custom benchmarks with specific probes, detectors, and options.
    
    Example:
        # Probe-based benchmark
        benchmark = BenchmarkConfig(
            name="My Custom Scan",
            probes=["dan.DAN", "encoding.InjectBase64", "promptinject"],
            timeout=3600,
        )
        
        # Taxonomy-based benchmark  
        benchmark = BenchmarkConfig(
            name="OWASP Scan",
            taxonomy_filters=["owasp:llm01", "owasp:llm02"],
            timeout=7200,
        )
    """
    
    name: str = Field(
        description="Human-readable name for the benchmark"
    )
    
    description: Optional[str] = Field(
        default=None,
        description="Description of what this benchmark tests"
    )
    
    # Probe configuration (mutually exclusive with taxonomy_filters)
    probes: Optional[List[str]] = Field(
        default=None,
        description="List of garak probes to run (e.g., ['dan.DAN', 'encoding', 'promptinject.HijackHateHumans'])"
    )
    
    # Taxonomy configuration (mutually exclusive with probes)
    taxonomy_filters: Optional[List[str]] = Field(
        default=None,
        description="Taxonomy filters for probe selection (e.g., ['owasp:llm', 'avid-effect:security'])"
    )
    
    # Reproducibility
    seed: Optional[int] = Field(
        default=None,
        description="Random seed for reproducible results"
    )
    
    # Detector configuration
    detectors: Optional[List[str]] = Field(
        default=None,
        description="Specific detectors to use (overrides probe defaults)"
    )
    
    extended_detectors: Optional[List[str]] = Field(
        default=None,
        description="Additional detectors to run alongside defaults"
    )
    
    detector_options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom detector configuration options"
    )
    
    # Probe options
    probe_options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom probe configuration options"
    )

    # Execution parameters
    timeout: int = Field(
        default=3600,
        ge=60,
        description="Maximum execution time in seconds (minimum 60s)"
    )
    eval_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Vulnerability threshold (0-1)"
    )
    
    # Input transformations (buffs)
    buffs: Optional[List[str]] = Field(
        default=None,
        description="Input transformation buffs to apply"
    )
    
    buff_options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Custom buff configuration options"
    )
    
    # Harness configuration
    harness_options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Test harness configuration options"
    )
    
    # Output processing
    deprefix: Optional[str] = Field(
        default=None,
        description="Prefix to remove from model outputs"
    )
    
    # AutoDAN
    generate_autodan: Optional[str] = Field(
        default=None,
        description="Enable AutoDAN generation with specified config"
    )
    
    # Documentation
    documentation: Optional[str] = Field(
        default=None,
        description="URL to documentation for this benchmark"
    )

    @model_validator(mode='after')
    def validate_probe_or_taxonomy(self):
        """Ensure either probes or taxonomy_filters is specified, but not both."""
        has_probes = self.probes is not None and len(self.probes) > 0
        has_taxonomy = self.taxonomy_filters is not None and len(self.taxonomy_filters) > 0
        
        if not has_probes and not has_taxonomy:
            raise ValueError(
                "Either 'probes' or 'taxonomy_filters' must be specified. "
                "Example probes: ['dan.DAN', 'encoding', 'promptinject']"
            )
        
        if has_probes and has_taxonomy:
            raise ValueError(
                "Cannot specify both 'probes' and 'taxonomy_filters'. "
                "Use probes for specific tests or taxonomy_filters for category-based selection."
            )
        
        return self
    
    @property
    def is_taxonomy_based(self) -> bool:
        """Check if this benchmark uses taxonomy filters."""
        return self.taxonomy_filters is not None and len(self.taxonomy_filters) > 0
    
    @property
    def is_probe_based(self) -> bool:
        """Check if this benchmark uses explicit probes."""
        return self.probes is not None and len(self.probes) > 0


PREDEFINED_BENCHMARKS: Dict[str, BenchmarkConfig] = {
    # Quick testing
    "quick": BenchmarkConfig(
        name="Quick Scan",
        description="Quick security scan for testing (~10 minutes)",
        probes=["realtoxicityprompts.RTPProfanity"],
        timeout=1800,
    ),
    
    "standard": BenchmarkConfig(
        name="Standard Scan", 
        description="Standard security scan covering common attack vectors (~30 minutes)",
        probes=[
            "dan",              # Jailbreak
            "encoding",         # Prompt injection via encoding
            "promptinject",     # Prompt injection
            "realtoxicityprompts",  # Toxicity
            "continuation",     # Bias
        ],
        timeout=1800,
    ),
    
    # Comprehensive framework-based benchmarks
    "owasp_llm_top10": BenchmarkConfig(
        name="OWASP LLM Top 10",
        description="OWASP Top 10 for Large Language Model Applications (~12 hours)",
        taxonomy_filters=["owasp:llm"],
        timeout=43200,
        documentation="https://genai.owasp.org/llm-top-10/",
    ),
    
    "avid_security": BenchmarkConfig(
        name="AVID Security",
        description="AI Vulnerability Database - Security vulnerabilities (~12 hours)",
        taxonomy_filters=["avid-effect:security"],
        timeout=43200,
        documentation="https://docs.avidml.org/taxonomy/effect-sep-view/security",
    ),
    
    "avid_ethics": BenchmarkConfig(
        name="AVID Ethics",
        description="AI Vulnerability Database - Ethical concerns (~1 hour)",
        taxonomy_filters=["avid-effect:ethics"],
        timeout=3600,
        documentation="https://docs.avidml.org/taxonomy/effect-sep-view/ethics",
    ),
    
    "avid_performance": BenchmarkConfig(
        name="AVID Performance",
        description="AI Vulnerability Database - Performance issues (~1 hour)",
        taxonomy_filters=["avid-effect:performance"],
        timeout=3600,
        documentation="https://docs.avidml.org/taxonomy/effect-sep-view/performance",
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
            result[benchmark_id] = {
                "name": config.name,
                "description": config.description or "",
                "type": "taxonomy" if config.is_taxonomy_based else "probes",
                "timeout": config.timeout,
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
    """Configuration for Kubeflow remote execution"""

    results_s3_prefix: str = Field(
        description="S3 prefix (folder) where the evaluation results will be written.",
    )

    pipelines_endpoint: str = Field(
        description="Kubeflow Pipelines API endpoint URL"
    )

    namespace: str = Field(
        description="Kubeflow namespace for pipeline execution"
    )

    base_image: str = Field(
        description="Base image for Kubeflow pipeline components"
    )

    s3_credentials_secret_name: str = Field(
        default="aws-connection-pipeline-artifacts",
        description="Name of Kubernetes secret containing S3 credentials"
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

        # Using an inline benchmark definition
        config = EvalConfig(
            model=ModelConfig(
                model_endpoint="https://your-model/v1",
                model_name="gpt-4",
                api_key="your-api-key",
            ),
            benchmark=BenchmarkConfig(
                name="My Custom Scan",
                probes=["dan", "encoding"],
                timeout=3600,
            ),
            sampling_params={"temperature": 0.5, "max_tokens": 100},
        )
    """
    
    # Model configuration (named 'model' to avoid conflict with Pydantic's 'model_config')
    model: ModelConfig = Field(
        description="Model configuration"
    )
    
    # Benchmark - either reference a registered one OR define inline
    benchmark: str | BenchmarkConfig = Field(
        description="Benchmark configuration"
    )

    # Sampling parameters
    sampling_params: Dict[str, Any] = Field(
        default={},
        description="Sampling parameters for the model"
    )

    # Execution parameters
    timeout: Optional[int] = Field(
        default=None,
        description="Maximum execution time in seconds (minimum 60s). If not specified, use benchmark timeout."
    )
    
    parallel_attempts: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Number of parallel probe attempts (1-32)"
    )
    
    generations: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Number of generations per probe (1-10)"
    )
    
    # Scan parameters
    eval_threshold: Optional[float] = Field(
        default=None,
        description="Vulnerability threshold (0-1). If not specified, use benchmark eval_threshold."
    )
    
    max_retries: int = Field(
        default=3,
        ge=1,
        description="Retry attempts on failure"
    )
    
    use_gpu: bool = Field(
        default=False,
        description="Request GPU resources"
    )

    @model_validator(mode='after')
    def validate_benchmark_source(self):
        """Ensure benchmark is specified either by ID or inline definition."""
        has_benchmark_id = isinstance(self.benchmark, str)
        if not has_benchmark_id and not isinstance(self.benchmark, BenchmarkConfig):
            raise ValueError(
                "Specify valid benchmark configuration."
            )
        
        return self
    
    # def to_benchmark_config(self) -> Optional[BenchmarkConfig]:
    #     """Convert inline definition to BenchmarkConfig, or None if using benchmark ID."""
    #     if isinstance(self.benchmark, str):
    #         return None  # Using registered benchmark
        
    #     return BenchmarkConfig(
    #         name=f"Inline ({self.probes[0] if self.probes else self.taxonomy_filters[0]}...)",
    #         probes=self.probes,
    #         taxonomy_filters=self.taxonomy_filters,
    #         timeout=self.timeout,
    #         parallel_attempts=self.parallel_attempts,
    #         generations=self.generations,
    #         seed=self.seed,
    #         eval_threshold=self.eval_threshold,
    #     )


__all__ = [
    "BenchmarkConfig",
    "BenchmarkRegistry",
    "PREDEFINED_BENCHMARKS",
    "EvalConfig",
    "GarakConfig",
    "KubeflowConfig",
    "ScanConfig",
    "ModelConfig",
]
