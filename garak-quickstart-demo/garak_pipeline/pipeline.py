"""Standalone Garak KFP Pipeline Definition"""

from typing import List
from kfp import dsl, kubernetes
from .components import validate_inputs, garak_scan, parse_results


@dsl.pipeline()
def garak_scan_pipeline(
    command: List[str],
    job_id: str,
    eval_threshold: float,
    timeout_seconds: int,
    max_retries: int = 3,
    use_gpu: bool = False,
):
    """Garak security scan pipeline"""

    # AWS connection secret
    aws_connection_secret = "aws-connection-pipeline-artifacts"
    secret_key_to_env = {
        "AWS_ACCESS_KEY_ID": "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY": "AWS_SECRET_ACCESS_KEY",
        "AWS_DEFAULT_REGION": "AWS_DEFAULT_REGION",
        "AWS_S3_BUCKET": "AWS_S3_BUCKET",
        "AWS_S3_ENDPOINT": "AWS_S3_ENDPOINT",
    }

    # Step 1: Validate inputs
    validate_task: dsl.PipelineTask = validate_inputs(
        command=command,
    )
    validate_task.set_caching_options(False)
    
    # Step 2: Run the garak scan ONLY if validation passes
    with dsl.If(validate_task.outputs['is_valid'] == True, name="validation_passed"):
        
        with dsl.If(use_gpu == True, name="USE_GPU"):
            scan_task_gpu: dsl.PipelineTask = garak_scan(
                command=command,
                job_id=job_id,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
            )
            scan_task_gpu.after(validate_task)
            scan_task_gpu.set_caching_options(False)
            scan_task_gpu.set_accelerator_type(accelerator="nvidia.com/gpu")
            scan_task_gpu.set_accelerator_limit(limit=1)
            kubernetes.add_toleration(scan_task_gpu, key="nvidia.com/gpu", operator="Exists", effect="NoSchedule")
            kubernetes.use_secret_as_env(
                scan_task_gpu,
                secret_name=aws_connection_secret,
                secret_key_to_env=secret_key_to_env,
            )

            # Step 3: Parse the scan results ONLY if scan succeeds
            with dsl.If(scan_task_gpu.outputs['success'] == True, name="gpu_scan_succeeded"):
                parse_task_gpu: dsl.PipelineTask = parse_results(
                    file_list=scan_task_gpu.outputs['file_list'],
                    job_id=job_id,
                    eval_threshold=eval_threshold,
                )
                parse_task_gpu.set_caching_options(False)
                
                kubernetes.use_secret_as_env(
                    parse_task_gpu,
                    secret_name=aws_connection_secret,
                    secret_key_to_env=secret_key_to_env,
                )
        
        with dsl.Else(name="USE_CPU"):
            scan_task_cpu: dsl.PipelineTask = garak_scan(
                command=command,
                job_id=job_id,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
            )
            scan_task_cpu.after(validate_task)
            scan_task_cpu.set_caching_options(False)
            kubernetes.use_secret_as_env(
                scan_task_cpu,
                secret_name=aws_connection_secret,
                secret_key_to_env=secret_key_to_env,
            )

            # Step 3: Parse the scan results ONLY if scan succeeds
            with dsl.If(scan_task_cpu.outputs['success'] == True, name="cpu_scan_succeeded"):
                parse_task_cpu: dsl.PipelineTask = parse_results(
                    file_list=scan_task_cpu.outputs['file_list'],
                    job_id=job_id,
                    eval_threshold=eval_threshold,
                )
                parse_task_cpu.set_caching_options(False)
                
                kubernetes.use_secret_as_env(
                    parse_task_cpu,
                    secret_name=aws_connection_secret,
                    secret_key_to_env=secret_key_to_env,
                )
