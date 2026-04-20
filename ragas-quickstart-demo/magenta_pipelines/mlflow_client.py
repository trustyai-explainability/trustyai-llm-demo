"""MLflow evaluator plugin for Ragas evaluations via Kubeflow Pipelines."""

import logging
from typing import Any, Dict

import pandas as pd
from mlflow import MlflowClient
from mlflow.entities import Metric
from mlflow.models.evaluation import EvaluationResult, ModelEvaluator
from mlflow.utils.time import get_current_time_millis

from .config import EvalConfig, KubeflowConfig
from .pipeline_runner import PipelineRunner

logger = logging.getLogger(__name__)


class RagasKubeflowEvaluator(ModelEvaluator):
    """MLflow evaluator for triggering Ragas evaluations via Kubeflow Pipelines."""

    def __init__(self):
        self.client = MlflowClient()

    @classmethod
    def can_evaluate(
        cls, *, model_type: str, evaluator_config: Dict[str, Any], **kwargs
    ) -> bool:
        return model_type == "ragas"

    def _log_metrics(self, run_id: str, metrics: Dict[str, float]):
        """Helper method to log metrics into specified run."""
        timestamp = get_current_time_millis()
        self.client.log_batch(
            run_id,
            metrics=[
                Metric(key=key, value=value, timestamp=timestamp, step=0)
                for key, value in metrics.items()
            ],
        )

    def evaluate(
        self,
        *,
        model,
        model_type: str,
        dataset,
        run_id: str,
        evaluator_config: Dict[str, Any],
        **kwargs,
    ) -> EvaluationResult:
        """Evaluate the model using Ragas via Kubeflow Pipelines.

        Args:
            model: The model to evaluate (can be None for static dataset evaluation)
            model_type: Type of the model
            dataset: Dataset to evaluate on
            run_id: MLflow run ID
            evaluator_config: Configuration containing Kubeflow and evaluation settings
            **kwargs: Additional arguments

        Returns:
            EvaluationResult with metrics and artifacts
        """
        logger.info("Starting Ragas evaluation via Kubeflow Pipelines")

        # Override config if needed
        kfp_config = self._parse_kubeflow_config(evaluator_config)
        pipeline_runner = PipelineRunner(kfp_config)

        eval_config = self._build_eval_config(evaluator_config, dataset)
        job = pipeline_runner.run_eval(eval_config)
        logger.info(f"Submitted Ragas evaluation job {job.job_id} to Kubeflow")
        final_job = self._wait_for_completion(pipeline_runner, job.job_id)

        if final_job.status == "completed" and final_job.result is not None:
            metrics = self._compute_agg_metrics(final_job.result)
            self._log_metrics(run_id, metrics)
            self._log_artifacts(run_id, final_job.result, job.job_id)
            return EvaluationResult(metrics=metrics, artifacts={})
        else:
            raise RuntimeError(
                f"Evaluation job {job.job_id} failed with status: {final_job.status}"
            )

    def _parse_kubeflow_config(
        self, evaluator_config: Dict[str, Any]
    ) -> KubeflowConfig:
        """Parse Kubeflow configuration from evaluator config."""
        kfp_config_dict = evaluator_config.get("kubeflow", {})
        return KubeflowConfig(**kfp_config_dict)

    def _build_eval_config(
        self, evaluator_config: Dict[str, Any], dataset
    ) -> EvalConfig:
        """Build evaluation configuration from evaluator config and dataset."""
        eval_config_dict = evaluator_config.get("evaluation", {})

        # If dataset has features/labels, we might need to convert it to the expected format
        # For now, assume the dataset URI is provided in config
        return EvalConfig(**eval_config_dict)

    def _wait_for_completion(
        self, pipeline_runner: PipelineRunner, job_id: str, timeout: int = 3600
    ) -> Any:
        """Wait for evaluation job to complete."""
        import time

        poll_interval = 30  # seconds
        elapsed = 0

        while elapsed < timeout:
            job = pipeline_runner.job_status(job_id)

            if job.status in ["completed", "failed", "cancelled"]:
                return job

            logger.info(f"Job {job_id} status: {job.status}, waiting...")
            time.sleep(poll_interval)
            elapsed += poll_interval

        raise RuntimeError(f"Evaluation job {job_id} timed out after {timeout} seconds")

    def _compute_agg_metrics(self, result_df: pd.DataFrame) -> Dict[str, float]:
        """Extract aggregate metrics from Ragas evaluation results."""
        metrics = {}

        # Calculate mean for each metric column (assuming numeric columns are metrics)
        for col in result_df.columns:
            if result_df[col].dtype in ["float64", "int64"]:
                metrics[f"ragas_{col}_mean"] = float(result_df[col].mean())
                metrics[f"ragas_{col}_std"] = float(result_df[col].std())

        return metrics

    def _log_artifacts(self, run_id: str, result_df: pd.DataFrame, job_id: str) -> None:
        """Log evaluation results as MLflow artifacts."""
        import tempfile

        results_artifact_name = f"ragas_evaluation_results_{job_id}.jsonl"

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl") as tmp_file:
            result_df.to_json(tmp_file.name, orient="records", lines=True)
            tmp_file.flush()  # Ensure data is written before logging

            self.client.log_artifact(
                run_id, tmp_file.name, artifact_path="ragas_results"
            )
            logger.info(f"Logged evaluation results artifact: {results_artifact_name}")
