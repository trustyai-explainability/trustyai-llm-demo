import json
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from pydantic_settings import BaseSettings
from ragas.metrics import Metric

from .constants import METRIC_MAPPING


class RagasConfig(BaseModel):
    """Additional configuration parameters for Ragas evaluation."""

    batch_size: Optional[int] = Field(
        default=None,
        description="Batch size for evaluation. If None, no batching is done.",
    )

    show_progress: bool = Field(
        default=True, description="Whether to show progress bar during evaluation"
    )

    raise_exceptions: bool = Field(
        default=True,
        description="Whether to raise exceptions or return NaN for failed evaluations",
    )

    column_map: Optional[Dict[str, str]] = Field(
        default=None, description="Mapping of dataset column names to expected names"
    )


class KubeflowConfig(BaseSettings):
    """Configuration for Kubeflow remote execution."""

    pipelines_endpoint: str = Field(
        description="Kubeflow Pipelines API endpoint URL (required for remote execution)",
    )

    namespace: str = Field(
        description="Kubeflow namespace for pipeline execution",
    )

    base_image: str = Field(
        description="Base image for Kubeflow pipeline components",
    )

    model_config = ConfigDict(env_file=".env", env_prefix="KUBEFLOW_", extra="ignore")


class EvalConfig(BaseSettings):
    """Configuration for the evaluation pipeline."""

    input_dataset_uri: str = Field(
        description="S3 URI of the input dataset",
    )

    output_dataset_uri: str = Field(
        description="S3 URI of the output dataset",
    )

    inference_url: str = Field(
        description="Base URL for inference API (accessible from Kubeflow pods)",
    )

    model: str = Field(
        default="granite3.3:2b",
        description=(
            "Model to use for evaluation. "
            "Adding here for completeness, as it is already provided in the benchmark config's eval_candidate. "
            "It must match the identifier of the model in Llama Stack."
        ),
    )

    model_params: dict = Field(
        default={"temperature": 0.1, "max_tokens": 100},
        description=(
            "Sampling parameters for the model. "
            "Also here for completeness, as it is already provided in the benchmark config's eval_candidate. "
        ),
    )

    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description=(
            "Embedding model for Ragas evaluation. "
            "At the moment, this cannot be set in the benchmark config, so it must be set here. "
            "It must match the identifier of the embedding model in Llama Stack."
        ),
    )

    metric_names: List[str] = Field(
        default=[
            "answer_relevancy",
            "context_precision",
            "faithfulness",
            "context_recall",
        ],
        description="Metrics to use for evaluation",
        alias="metrics",
    )

    @field_validator("metric_names", mode="before")
    @classmethod
    def parse_metrics(cls, v):
        """Parse metrics from string if needed (for YAML env var substitution)."""
        if isinstance(v, str):
            return json.loads(v)
        return v

    @property
    @computed_field(return_type=List[Metric])
    def metric_functions(self) -> List[Metric]:
        return [METRIC_MAPPING[metric] for metric in self.metric_names]

    ragas_config: RagasConfig = Field(
        default=RagasConfig(),
        description="Additional configuration parameters for Ragas",
    )

    model_config = ConfigDict(env_file=".env", extra="ignore")
