from typing import List
from kfp import dsl, kubernetes
from .components import validate_inputs, garak_scan, parse_results
import os


@dsl.pipeline()
def garak_scan_pipeline(
    command: List[str],
    job_id: str,
    eval_threshold: float,
    timeout_seconds: int,
    s3_bucket: str,
    s3_prefix: str,
    verify_ssl: str,
    max_retries: int = 3,
    use_gpu: bool = False,
):
    """Garak security scan pipeline
    
    Args:
        command: Garak command to execute (e.g., ['garak', '--probes', 'dan', ...])
        job_id: Unique job identifier
        eval_threshold: Vulnerability threshold (0.0-1.0)
        timeout_seconds: Maximum execution time for scan
        s3_bucket: S3 bucket name for storing results
        s3_prefix: S3 prefix for storing results
        verify_ssl: Whether to verify SSL
        max_retries: Number of retry attempts on failure
        use_gpu: Whether to use GPU resources
    """

    # AWS S3 connection secret (configured in Kubeflow)
    aws_connection_secret = os.environ.get(
        'KUBEFLOW_S3_CREDENTIALS_SECRET_NAME',
        'aws-connection-pipeline-artifacts'
    )
    
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
        
        # GPU path
        with dsl.If(use_gpu == True, name="USE_GPU"):
            scan_task_gpu: dsl.PipelineTask = garak_scan(
                command=command,
                job_id=job_id,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                verify_ssl=verify_ssl,
                s3_bucket=s3_bucket,
                s3_prefix=s3_prefix,
            )
            scan_task_gpu.after(validate_task)
            scan_task_gpu.set_caching_options(False)
            scan_task_gpu.set_accelerator_type(accelerator="nvidia.com/gpu")
            scan_task_gpu.set_accelerator_limit(limit=1)
            kubernetes.add_toleration(
                scan_task_gpu,
                key="nvidia.com/gpu",
                operator="Exists",
                effect="NoSchedule"
            )
            kubernetes.use_secret_as_env(
                scan_task_gpu,
                secret_name=aws_connection_secret,
                secret_key_to_env=secret_key_to_env,
            )

            # Step 3: Parse the scan results ONLY if scan succeeds
            with dsl.If(scan_task_gpu.outputs['success'] == True, name="gpu_scan_succeeded"):
                parse_task_gpu: dsl.PipelineTask = parse_results(
                    scan_files=scan_task_gpu.outputs['scan_files'],
                    job_id=job_id,
                    eval_threshold=eval_threshold,
                    verify_ssl=verify_ssl,
                    s3_bucket=s3_bucket,
                    s3_prefix=s3_prefix,
                )
                parse_task_gpu.set_caching_options(False)
                
                kubernetes.use_secret_as_env(
                    parse_task_gpu,
                    secret_name=aws_connection_secret,
                    secret_key_to_env=secret_key_to_env,
                )
        
        # CPU path
        with dsl.Else(name="USE_CPU"):
            scan_task_cpu: dsl.PipelineTask = garak_scan(
                command=command,
                job_id=job_id,
                max_retries=max_retries,
                timeout_seconds=timeout_seconds,
                verify_ssl=verify_ssl,
                s3_bucket=s3_bucket,
                s3_prefix=s3_prefix,
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
                    scan_files=scan_task_cpu.outputs['scan_files'],
                    job_id=job_id,
                    eval_threshold=eval_threshold,
                    verify_ssl=verify_ssl,
                    s3_bucket=s3_bucket,
                    s3_prefix=s3_prefix,
                )
                parse_task_cpu.set_caching_options(False)
                
                kubernetes.use_secret_as_env(
                    parse_task_cpu,
                    secret_name=aws_connection_secret,
                    secret_key_to_env=secret_key_to_env,
                )
