"""KFP Components for standalone Garak pipeline"""

from kfp import dsl
from typing import NamedTuple, List, Dict
import os

CPU_BASE_IMAGE = 'quay.io/rh-ee-spandraj/trustyai-garak-provider-dsp:cpu'


# Component 1: Validation Step
@dsl.component(
    base_image=os.getenv('KUBEFLOW_BASE_IMAGE', CPU_BASE_IMAGE)
)
def validate_inputs(
    command: List[str],
) -> NamedTuple('outputs', [
    ('is_valid', bool),
    ('validation_errors', List[str])
]):
    """Validate inputs before running expensive scan"""

    import subprocess
    
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
            print(f"Garak installed: {version}")
        else:
            validation_errors.append(f"Garak version check failed: {result.stderr}")
    except FileNotFoundError:
        validation_errors.append("Garak is not installed or not in PATH")
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
    
    return (
        len(validation_errors) == 0,
        validation_errors
    )


# Component 2: Garak Scan
@dsl.component(
    base_image=os.getenv('KUBEFLOW_BASE_IMAGE', CPU_BASE_IMAGE)
)
def garak_scan(
    command: List[str],
    job_id: str,
    max_retries: int,
    timeout_seconds: int,
) -> NamedTuple('outputs', [
    ('exit_code', int),
    ('success', bool),
    ('file_list', str)
]):
    """Actual Garak Scan"""
    import subprocess
    import time
    import os
    import signal
    from pathlib import Path
    import threading
    
    # Setup directories
    scan_dir = Path(os.getcwd()) / 'scan_files'
    scan_dir.mkdir(exist_ok=True, parents=True)
    
    scan_log_file = scan_dir / "scan.log"
    scan_report_prefix = scan_dir / "scan"
    
    command = command + ['--report_prefix', str(scan_report_prefix)]
    env = os.environ.copy()
    env["GARAK_LOG_FILE"] = str(scan_log_file)
    env["PYTHONUNBUFFERED"] = "1"
    
    file_list = []

    def stream_output(pipe, prefix=""):
        """Stream subprocess output to stdout (pod logs)"""
        try:
            for line in iter(pipe.readline, ''):
                print(f"{prefix}{line}", end='', flush=True)
        except Exception as e:
            print(f"Error streaming output: {e}")
    
    for attempt in range(max_retries):
        
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                env=env,
                preexec_fn=os.setsid  # Create new process group
            )
            
            stream_thread = threading.Thread(
                target=stream_output,
                args=(process.stdout, ""),
                daemon=True
            )
            stream_thread.start()
            
            try:
                process.wait(timeout=timeout_seconds)
                stream_thread.join(timeout=5)
                
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
                    process.returncode, command, "", ""
                )
            
            # Upload files to S3 and track them
            import boto3
            from botocore.config import Config
            
            boto_config = Config(
                connect_timeout=30,
                read_timeout=60,
                retries={'max_attempts': 3, 'mode': 'standard'}
            )
            
            s3_endpoint = os.environ.get('AWS_S3_ENDPOINT', '')
            
            if s3_endpoint:
                s3_client = boto3.client(
                    's3',
                    endpoint_url=s3_endpoint,
                    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                    region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
                    use_ssl=s3_endpoint.startswith('https'),
                    verify=os.environ.get('AWS_S3_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes'),
                    config=boto_config
                )
            else:
                s3_client = boto3.client('s3',
                    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
                    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
                    region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
                    config=boto_config
                )
            
            bucket = os.getenv('AWS_S3_BUCKET', 'garak-results')
            
            for file_path in scan_dir.glob('*'):
                if file_path.is_file():
                    print(f"Uploading {file_path.name} to S3...")
                    with open(file_path, 'rb') as f:
                        s3_client.put_object(
                            Bucket=bucket,
                            Key=f"{job_id}/{file_path.name}",
                            Body=f.read()
                        )
                    file_list.append(file_path.name)
                        
            
            return (0, True, ",".join(file_list))
            
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = min(5 * (2 ** attempt), 60)  # Exponential backoff
                print(f"Attempt {attempt + 1} failed, retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise e
    
    return (-1, False, "")


# Component 3: Results Parser
@dsl.component(
    base_image=os.getenv('KUBEFLOW_BASE_IMAGE', CPU_BASE_IMAGE)
)
def parse_results(
    file_list: str,
    job_id: str,
    eval_threshold: float,
):

    """Parse results and provide analysis"""
    import boto3
    import os
    import json
    from pathlib import Path
    from typing import List, Dict, Any
    from botocore.config import Config

    print(f"Parsing results for job {job_id}")
    print(f"Files to process: {file_list}")
    
    # Setup S3 client
    boto_config = Config(
        connect_timeout=30,
        read_timeout=60,
        retries={'max_attempts': 3, 'mode': 'standard'}
    )
    
    s3_endpoint = os.environ.get('AWS_S3_ENDPOINT', '')
    
    if s3_endpoint:
        s3_client = boto3.client(
            's3',
            endpoint_url=s3_endpoint,
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
            region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
            use_ssl=s3_endpoint.startswith('https'),
            verify=os.environ.get('AWS_S3_VERIFY_SSL', 'true').lower() in ('true', '1', 'yes'),
            config=boto_config
        )
    else:
        s3_client = boto3.client('s3',
            aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
            aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
            region_name=os.environ.get('AWS_DEFAULT_REGION', 'us-east-1'),
            config=boto_config
        )
    
    if not s3_client:
        raise ValueError("S3 client not found")
    
    bucket = os.getenv('AWS_S3_BUCKET', 'garak-results')
    
    # Download report file from S3
    report_file_key = f"{job_id}/scan.report.jsonl"
    
    print(f"Downloading report file from s3://{bucket}/{report_file_key}")
    
    try:
        response = s3_client.get_object(
            Bucket=bucket,
            Key=report_file_key
        )
        report_file_content = response['Body'].read().decode('utf-8')
    except Exception as e:
        print(f"Error downloading report file: {e}")
        raise
    
    # Parse the report
    generations: List[Dict[str, Any]] = []
    scores: Dict[str, Dict[str, Any]] = {} 

    score_rows: Dict[str, List[Dict[str, float]]] = {}
    aggregated_results_by_probe: Dict[str, Dict[str, List[float]]] = {}

    for line in report_file_content.split("\n"):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            generation: Dict[str, Any] = {}

            # Handle attempt entries
            if (entry.get("entry_type") == "attempt" and entry.get("status") == 2):
                probe_name: str = entry.get("probe_classname", "unknown")

                detector_results: dict = entry.get("detector_results", {})
                detector_maxscore_map: Dict[str, float] = {}
                is_vulnerable: bool = False
                
                for detector, _scores in detector_results.items():
                    _scores = _scores if isinstance(_scores, list) else [_scores]
                    if any(score >= eval_threshold for score in _scores):
                        is_vulnerable = True
                    detector_maxscore_map[detector] = max(_scores) if _scores else 0
                outputs: list = entry.get("outputs", [])

                generation["probe"] = probe_name
                generation["vulnerable"] = is_vulnerable
                generation["prompt"] = entry.get("prompt", "")
                generation["response"] = outputs[0] if len(outputs) > 0 and outputs[0] else ""
                generations.append(generation)

                if probe_name not in score_rows:
                    score_rows[probe_name] = []
                score_rows[probe_name].append(detector_maxscore_map)

                if probe_name not in aggregated_results_by_probe:
                    aggregated_results_by_probe[probe_name] = {}
                for detector, score in detector_maxscore_map.items():
                    if detector not in aggregated_results_by_probe[probe_name]:
                        aggregated_results_by_probe[probe_name][detector] = []
                    aggregated_results_by_probe[probe_name][detector].append(score)
        
        except json.JSONDecodeError as e:
            print(f"Invalid JSON line in report file for job {job_id}: {line} - {e}")
            continue
        except Exception as e:
            print(f"Error parsing line in report file for job {job_id}: {line} - {e}")
            continue
        
    # Calculate the mean of the scores for each probe
    aggregated_results_mean: Dict[str, Dict[str, float]] = {}
    for probe_name, results in aggregated_results_by_probe.items():
        aggregated_results_mean[probe_name] = {}
        for detector, _scores in results.items():
            detector_mean_score: float = round(sum(_scores) / len(_scores), 3) if _scores else 0
            aggregated_results_mean[probe_name][f"{detector}_mean"] = detector_mean_score
            
    all_probes: List[str] = list(aggregated_results_mean.keys())
    for probe_name in all_probes:
        scores[probe_name] = {
            "score_rows": score_rows[probe_name],
            "aggregated_results": aggregated_results_mean[probe_name]
        }

    scan_result = {
        "generations": generations,
        "scores": scores
    }

    # Save file and upload results mapping to S3
    scan_result_file = Path(os.getcwd()) / "scan_result.json"
    with open(scan_result_file, 'w') as f:
        json.dump(scan_result, f)
    
    # Upload the scan_result.json
    print(f"Uploading scan_result.json to S3...")
    with open(scan_result_file, 'rb') as f:
        s3_client.put_object(
            Bucket=bucket,
            Key=f"{job_id}/scan_result.json",
            Body=f.read()
        )
    
    # Create file mapping (matching Llama Stack format)
    file_mapping = {}
    for filename in file_list.split(","):
        if filename:
            file_mapping[filename] = f"{job_id}/{filename}"
    file_mapping["scan_result.json"] = f"{job_id}/scan_result.json"

    print(f"file_mapping: {file_mapping}")

    # Upload the mapping itself to S3 (for job_status to retrieve)
    s3_client.put_object(
        Bucket=bucket,
        Key=f"{job_id}.json",
        Body=json.dumps(file_mapping)
    )
    
    print(f"Results uploaded successfully!")
