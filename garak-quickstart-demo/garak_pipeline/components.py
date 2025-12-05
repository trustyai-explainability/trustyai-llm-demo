"""KFP Components for standalone Garak pipeline - S3-based storage"""

from kfp import dsl
from typing import NamedTuple, List, Dict
import os
from .constants import (
    GARAK_PROVIDER_IMAGE_CONFIGMAP_NAME,
    GARAK_PROVIDER_IMAGE_CONFIGMAP_KEY,
    KUBEFLOW_CANDIDATE_NAMESPACES,
    DEFAULT_GARAK_PROVIDER_IMAGE
    )
from .utils import load_kube_config
from kubernetes import client
from kubernetes.client.exceptions import ApiException
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def get_base_image() -> str:
    """Get base image from env, fallback to k8s ConfigMap, fallback to default image.
    
    This function is called at module import time, so it must handle cases where
    kubernetes config is not available (e.g., in tests or non-k8s environments).
    """
    # Check environment variable first (highest priority)
    if (base_image := os.environ.get("KUBEFLOW_BASE_IMAGE")) is not None:
        return base_image

    # Try to load from kubernetes ConfigMap
    try:
        load_kube_config()
        api = client.CoreV1Api()

        for candidate_namespace in KUBEFLOW_CANDIDATE_NAMESPACES:
            try:
                configmap = api.read_namespaced_config_map(
                    name=GARAK_PROVIDER_IMAGE_CONFIGMAP_NAME,
                    namespace=candidate_namespace,
                )

                data: dict[str, str] | None = configmap.data
                if data and GARAK_PROVIDER_IMAGE_CONFIGMAP_KEY in data:
                    return data[GARAK_PROVIDER_IMAGE_CONFIGMAP_KEY]
            except ApiException as api_exc:
                if api_exc.status == 404:
                    continue
                else:
                    logger.warning(f"Warning: Could not read from ConfigMap: {api_exc}")
            except Exception as e:
                logger.warning(f"Warning: Could not read from ConfigMap: {e}")
        else:
            # None of the candidate namespaces had the required ConfigMap/key
            logger.debug(
                f"ConfigMap '{GARAK_PROVIDER_IMAGE_CONFIGMAP_NAME}' with key "
                f"'{GARAK_PROVIDER_IMAGE_CONFIGMAP_KEY}' not found in any of the namespaces: "
                f"{KUBEFLOW_CANDIDATE_NAMESPACES}. Using default image."
            )
            return DEFAULT_GARAK_PROVIDER_IMAGE
    except Exception as e:
        # Kubernetes config not available (e.g., in tests or non-k8s environment)
        logger.debug(f"Kubernetes config not available: {e}. Using default image.")
        return DEFAULT_GARAK_PROVIDER_IMAGE


# Component 1: Validation Step
@dsl.component(
    base_image=get_base_image()
)
def validate_inputs(
    command: List[str],
) -> NamedTuple('outputs', [
    ('is_valid', bool),
    ('validation_errors', List[str])
]):
    """Validate inputs before running expensive scan"""
    import subprocess
    import logging

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    validation_errors = []
    
    # Check if Garak is installed
    try:
        result = subprocess.run(
            ['garak', '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            logger.info(f"Garak installed: {version}")
        else:
            validation_errors.append(f"Garak version check failed: {result.stderr}")
    except Exception as e:
        validation_errors.append(f"Error checking Garak installation: {str(e)}")
    
    # Validate command structure
    if not command or command[0] != 'garak':
        validation_errors.append("Invalid command: must start with 'garak'")
    
    # Check for dangerous flags
    dangerous_flags = ['--rm', '--force', '--no-limit']
    for flag in dangerous_flags:
        if flag in command:
            validation_errors.append(f"Dangerous flag detected: {flag}")
    
    logger.info(f"validation_errors: {validation_errors}")
    return (
        len(validation_errors) == 0,
        validation_errors
    )


# Component 2: Garak Scan
@dsl.component(
    base_image=get_base_image()
)
def garak_scan(
    command: List[str],
    job_id: str,
    max_retries: int,
    timeout_seconds: int,
    verify_ssl: str,
    s3_bucket: str,
    s3_prefix: str,
) -> NamedTuple('outputs', [
    ('exit_code', int),
    ('success', bool),
    ('scan_files', List[str])
]):
    """Execute Garak Scan and upload results to S3"""
    import subprocess
    import time
    import os
    import signal
    import json
    from pathlib import Path
    import logging
    from garak_pipeline.utils import create_s3_client, check_and_create_bucket

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # Setup directories
    scan_dir = Path(os.getcwd()) / 'scan_files'
    scan_dir.mkdir(exist_ok=True, parents=True)
    
    scan_log_file = scan_dir / "scan.log"
    scan_report_prefix = scan_dir / "scan"
    
    command = command + ['--report_prefix', str(scan_report_prefix)]
    env = os.environ.copy()
    env["GARAK_LOG_FILE"] = str(scan_log_file)
    
    scan_files = []
    
    for attempt in range(max_retries):
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                preexec_fn=os.setsid
            )
            
            try:
                stdout, stderr = process.communicate(timeout=timeout_seconds)
                
            except subprocess.TimeoutExpired:
                # Kill the entire process group
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # process is still running, kill it with SIGKILL
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait()
                raise
            
            if process.returncode != 0:
                raise subprocess.CalledProcessError(
                    process.returncode, command, stdout, stderr
                )
            
            # Generate AVID report
            report_file = scan_report_prefix.with_suffix(".report.jsonl")
            try:
                from garak_pipeline.avid_report import Report
                
                if not report_file.exists():
                    logger.error(f"Report file not found: {report_file}")
                else:
                    report = Report(str(report_file)).load().get_evaluations()
                    report.export()  # Creates scan.avid.jsonl
                    logger.info("Successfully converted report to AVID format")
                    
            except FileNotFoundError as e:
                logger.error(f"Report file not found during AVID conversion: {e}")
            except PermissionError as e:
                logger.error(f"Permission denied reading report file: {e}")
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Failed to parse report file: {e}", exc_info=True)
            except ImportError as e:
                logger.error(f"Failed to import AVID report module: {e}")
            except Exception as e:
                logger.error(f"Unexpected error converting report to AVID format: {e}", exc_info=True)
            
            s3_client = create_s3_client(
                endpoint_url=os.environ.get('AWS_S3_ENDPOINT'),
                aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
                verify_ssl=verify_ssl
            )
            check_and_create_bucket(s3_client, s3_bucket)
            
            s3_prefix = s3_prefix.rstrip("/").strip()

            # Upload files to S3
            for file_path in scan_dir.glob('*'):
                if file_path.is_file():
                    if s3_prefix:
                        s3_key = f"{s3_prefix}/{job_id}/{file_path.name}"
                    else:
                        s3_key = f"{job_id}/{file_path.name}"
                    logger.info(f"Uploading {file_path.name} to s3://{s3_bucket}/{s3_key}")
                    with open(file_path, 'rb') as f:
                        s3_client.put_object(
                            Bucket=s3_bucket,
                            Key=s3_key,
                            Body=f.read()
                        )
                    scan_files.append(s3_key)
            
            logger.info(f"Successfully uploaded {len(scan_files)} files to s3://{s3_bucket}/{s3_prefix}")
            return (0, True, scan_files)
            
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = min(5 * (2 ** attempt), 60)
                logger.info(f"Attempt {attempt + 1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                logger.error(f"All {max_retries} attempts failed: {e}")
                raise e
        finally:
            if s3_client:
                try:
                    s3_client.close()
                except Exception as e:
                    logger.warning(f"Error closing S3 client: {e}")
            if process:
                try:
                    process.terminate()
                except Exception as e:
                    logger.warning(f"Error terminating process: {e}")
    
    return (-1, False, [])


# Component 3: Results Parser
@dsl.component(
    base_image=get_base_image()
)
def parse_results(
    scan_files: List[str],
    job_id: str,
    eval_threshold: float,
    verify_ssl: str,
    s3_bucket: str,
    s3_prefix: str,
    html_report: dsl.Output[dsl.HTML]
):
    """Parse Garak scan results and upload results to S3"""
    import os
    import json
    from pathlib import Path
    from garak_pipeline.utils import create_s3_client, check_and_create_bucket
    import logging
    from garak_pipeline.result_parser import (
        parse_generations_from_report_content,
        parse_aggregated_from_avid_content,
        combine_parsed_results
    )

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    s3_client = create_s3_client(
        endpoint_url=os.environ.get('AWS_S3_ENDPOINT'),
        aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
        region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
        verify_ssl=verify_ssl
    )
    check_and_create_bucket(s3_client, s3_bucket)
    
    s3_prefix = s3_prefix.rstrip("/").strip()
    report_file_key = f"{job_id}/scan.report.jsonl"
    avid_file_key = f"{job_id}/scan.avid.jsonl"
    scan_result_file_key = f"{job_id}/scan_result.json"
    
    if s3_prefix:
        report_file_key = f"{s3_prefix}/{report_file_key}"
        avid_file_key = f"{s3_prefix}/{avid_file_key}"
        scan_result_file_key = f"{s3_prefix}/{scan_result_file_key}"
    
    logger.info(f"Downloading report file from s3://{s3_bucket}/{report_file_key}")
    try:
        response = s3_client.get_object(
            Bucket=s3_bucket,
            Key=report_file_key
        )
        report_content = response['Body'].read().decode('utf-8')
    except Exception as e:
        print(f"Error downloading report file: {e}")
        raise
    
    # Download AVID report (if available)
    avid_content = ""
    try:
        response = s3_client.get_object(
            Bucket=s3_bucket,
            Key=avid_file_key
        )
        avid_content = response['Body'].read().decode('utf-8')
        logger.info(f"Downloaded AVID report from s3://{s3_bucket}/{avid_file_key}")
    except Exception as e:
        logger.warning(f"No AVID report - will not have taxonomy info: {e}")
    
    # Parse using result_parser utilities
    logger.info("Parsing generations from report.jsonl...")
    generations, score_rows_by_probe = parse_generations_from_report_content(
        report_content, eval_threshold
    )
    logger.info(f"Parsed {len(generations)} attempts")
    
    logger.info("Parsing aggregated info from AVID report...")
    aggregated_by_probe = parse_aggregated_from_avid_content(avid_content)
    logger.info(f"Parsed {len(aggregated_by_probe)} probe summaries")
    
    logger.info("Combining results...")
    scan_result = combine_parsed_results(
        generations,
        score_rows_by_probe,
        aggregated_by_probe,
        eval_threshold
    )
    
    # Save file to tmp directory and upload results to S3
    logger.info("Saving scan result...")
    scan_result_file = Path(os.getcwd()) / "scan_result.json"
    with open(scan_result_file, 'w') as f:
        json.dump(scan_result, f, indent=2)
    
    # Upload the scan_result.json
    logger.info(f"Uploading scan_result.json to s3://{s3_bucket}/{scan_result_file_key}")
    with open(scan_result_file, 'rb') as f:
        s3_client.put_object(
            Bucket=s3_bucket,
            Key=scan_result_file_key,
            Body=f.read()
        )
    
    # Create file mapping (for easy retrieval)
    file_mapping = {}
    for filename in scan_files:
        if filename:
            file_mapping[filename.split("/")[-1]] = filename
    file_mapping["scan_result.json"] = scan_result_file_key

    logger.info(f"File mapping: {file_mapping}")

    # Upload the mapping itself to S3 (for job_status to retrieve)
    s3_client.put_object(
        Bucket=s3_bucket,
        Key=f"{s3_prefix}/{job_id}.json",
        Body=json.dumps(file_mapping)
    )
    
    logger.info(f"Results uploaded successfully to s3://{s3_bucket}/{s3_prefix}")
    
    html_report_key = file_mapping.get("scan.report.html")
    if html_report_key:
        logger.info(f"Downloading HTML report from s3://{s3_bucket}/{html_report_key}")
        try:
            response = s3_client.get_object(
                Bucket=s3_bucket,
                Key=html_report_key
            )
            html_content = response['Body'].read().decode('utf-8')
        except Exception as e:
            logger.warning(f"No HTML report found: {e}")
        with open(html_report.path, 'w') as f:
            f.write(html_content)
    else:
        logger.warning("No HTML report found")