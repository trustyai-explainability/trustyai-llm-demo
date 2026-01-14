def __getattr__(name: str):
    """Lazy import of client-side modules to avoid kfp.Client import errors in components."""
    if name == "PipelineRunner":
        from .runner import PipelineRunner
        return PipelineRunner
    if name == "ScanJob":
        from .runner import ScanJob
        return ScanJob
    if name == "EvalConfig":
        from .config import EvalConfig
        return EvalConfig
    if name == "BenchmarkConfig":
        from .config import BenchmarkConfig
        return BenchmarkConfig
    if name == "BenchmarkRegistry":
        from .config import BenchmarkRegistry
        return BenchmarkRegistry
    if name == "PREDEFINED_BENCHMARKS":
        from .config import PREDEFINED_BENCHMARKS
        return PREDEFINED_BENCHMARKS
    if name == "GarakConfig":
        from .config import GarakConfig
        return GarakConfig
    if name == "KubeflowConfig":
        from .config import KubeflowConfig
        return KubeflowConfig
    if name == "ScanConfig":
        from .config import ScanConfig
        return ScanConfig
    if name == "ModelConfig":
        from .config import ModelConfig
        return ModelConfig
    if name == "GarakError":
        from .errors import GarakError
        return GarakError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "EvalConfig",
    "BenchmarkConfig",
    "BenchmarkRegistry",
    "PREDEFINED_BENCHMARKS",
    "GarakConfig",
    "KubeflowConfig",
    "ScanConfig",
    "ModelConfig",
    "PipelineRunner",
    "ScanJob",
    "GarakError",
]
