import logging
import boto3

logger = logging.getLogger(__name__)


def load_kube_config():
    from kubernetes.config import load_incluster_config, load_kube_config, ConfigException
    from kubernetes.client.configuration import Configuration

    config = Configuration()

    try:
        load_incluster_config(client_configuration=config)
        logger.info("Loaded in-cluster Kubernetes configuration")
    except ConfigException:
        load_kube_config(client_configuration=config)
        logger.info("Loaded Kubernetes configuration from kubeconfig file")

    return config

def clean_ssl_verify(verify_ssl: str) -> bool | str:
    if verify_ssl.lower().strip() in ("true", "1", "yes", "on", ""):
        return True
    elif verify_ssl.lower().strip() in ("false", "0", "no", "off"):
        return False
    else:
        return verify_ssl

def create_s3_client(endpoint_url: str, aws_access_key_id: str, aws_secret_access_key: str, region_name: str, verify_ssl: bool | str) -> boto3.client:
    from botocore.config import Config
    
    boto_config = Config(
        retries={'max_attempts': 3, 'mode': 'standard'}
    )

    return boto3.client(
                's3',
                endpoint_url=endpoint_url,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                region_name=region_name,
                verify=clean_ssl_verify(verify_ssl) if isinstance(verify_ssl, str) else verify_ssl,
                config=boto_config
            )

def check_and_create_bucket(s3_client: boto3.client, bucket: str):
    from botocore.exceptions import ClientError

    try:
        s3_client.head_bucket(Bucket=bucket)
    except ClientError as e:
        # If a ClientError is returned, the bucket either doesn't exist or lack permission
        error_code = e.response.get('Error', {}).get('Code', '')
        if error_code == '404':
            logger.info(f"Bucket '{bucket}' not found. Creating bucket now...")
            s3_client.create_bucket(Bucket=bucket)
            logger.info("Bucket created. Proceeding with upload.")
        else:
            if error_code == '403':
                logger.error(f"Permission denied for bucket '{bucket}'. Check IAM policies.")
            raise e
    except Exception as e:
        logger.error(f"Unexpected error checking bucket '{bucket}': {e}")
        raise e