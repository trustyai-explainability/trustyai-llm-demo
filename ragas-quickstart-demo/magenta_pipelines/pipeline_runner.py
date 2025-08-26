import logging
import subprocess
import uuid
from typing import Dict

import kfp
import pandas as pd
import requests
from pydantic import BaseModel, ConfigDict

from .config import EvalConfig, KubeflowConfig
from .logging_utils import render_dataframe_as_table

logger = logging.getLogger(__name__)


class EvalJob(BaseModel):
    job_id: str
    status: str
    eval_config: EvalConfig
    kubeflow_run_id: str | None = None
    result: pd.DataFrame | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PipelineRunner:
    """Execute Ragas evaluations using Kubeflow Pipelines."""

    def __init__(self, kfp_config: KubeflowConfig):
        self.kfp_config = kfp_config
        self.evaluation_jobs: Dict[str, EvalJob] = {}
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

            # the kfp.Client handles the healthz endpoint poorly, run a pre-flight check manually
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

    def run_eval(self, eval_config: EvalConfig) -> EvalJob:
        job_id = str(uuid.uuid4())
        job = EvalJob(job_id=job_id, status="submitted", eval_config=eval_config)

        kubeflow_run_id = self._submit_to_kubeflow(
            eval_config=eval_config, job_id=job_id
        )

        job.kubeflow_run_id = kubeflow_run_id
        self.evaluation_jobs[job_id] = job

        logger.info(
            f"Submitted Ragas evaluation job {job_id} to Kubeflow with run ID {kubeflow_run_id}"
        )

        return job

    def _submit_to_kubeflow(self, eval_config: EvalConfig, job_id: str) -> str:
        from .kubeflow.pipeline import ragas_evaluation_pipeline

        sampling_params = {
            "temperature": eval_config.model_params["temperature"],
            "max_tokens": eval_config.model_params["max_tokens"],
        }

        pipeline_args = {
            "model": eval_config.model,
            "sampling_params": sampling_params,
            "embedding_model": eval_config.embedding_model,
            "metrics": eval_config.metric_names,
            "inference_url": eval_config.inference_url,
            "input_dataset_uri": eval_config.input_dataset_uri,
            "output_dataset_uri": eval_config.output_dataset_uri,
        }

        run_result = self.kfp_client.create_run_from_pipeline_func(
            pipeline_func=ragas_evaluation_pipeline,
            arguments=pipeline_args,
            run_name=f"ragas-eval-run-{job_id}",
            namespace=self.kfp_config.namespace,
            experiment_name="lls-provider-ragas-runs",
        )

        return run_result.run_id

    def _fetch_kubeflow_results(self, job: EvalJob) -> pd.DataFrame:
        """Fetch results directly from S3."""
        s3_url = job.eval_config.output_dataset_uri

        try:
            df = pd.read_json(s3_url, lines=True)
            logger.info(f"Successfully fetched results from {s3_url}")
        except Exception as e:
            raise RuntimeError(
                f"Failed to fetch results from {s3_url}: {str(e)}"
            ) from e
        else:
            table_output = render_dataframe_as_table(df, "Fetched Evaluation Results")
            logger.info(f"Fetched Evaluation Results:\n{table_output}")
            job.result = df
            return df

    def job_cancel(self, job_id: str) -> None:
        """Cancel a running Kubeflow pipeline."""
        if (job := self.evaluation_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")

        try:
            self.kfp_client.runs.terminate_run(job.kubeflow_run_id)
            job.status = "cancelled"
            logger.info(
                f"Cancelled Kubeflow run {job.kubeflow_run_id} for job {job_id}"
            )
        except Exception as e:
            logger.error(f"Failed to cancel job: {str(e)}")
            raise RuntimeError(f"Failed to cancel job: {str(e)}") from e

    def job_status(self, job_id: str) -> EvalJob:
        if (job := self.evaluation_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")

        try:
            run_detail = self.kfp_client.get_run(job.kubeflow_run_id)
            if run_detail.state == "FAILED":
                job.status = "failed"
            elif run_detail.state == "SUCCEEDED":
                job.status = "completed"
                self._fetch_kubeflow_results(job)
            elif run_detail.state == "RUNNING" or run_detail.state == "PENDING":
                job.status = "in_progress"
            else:
                raise RuntimeError(f"Unknown Kubeflow run state: {run_detail.state}")
        except Exception as e:
            logger.error(f"Failed to get job status: {str(e)}")

        return job

    def job_result(self, job_id: str) -> pd.DataFrame | None:
        if (job := self.evaluation_jobs.get(job_id)) is None:
            raise RuntimeError(f"Job {job_id} not found")

        if job.status == "completed":
            return job.result
        elif job.status == "failed":
            raise RuntimeError(f"Job {job_id} failed")
        else:
            return None  # Job still running
