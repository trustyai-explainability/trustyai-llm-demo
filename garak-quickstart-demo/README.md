# Garak Security Scanning - Quickstart Demo

Run [Garak](https://github.com/NVIDIA/garak) security scans on Kubeflow Pipelines to test LLMs for vulnerabilities.

## Prerequisites

- Access to a Kubeflow Pipelines deployment
- OpenShift CLI (`oc`) configured and logged in
- Python 3.11+
- Model serving endpoint (OpenAI-compatible API)

## Installation

1. Install dependencies:

```bash
pip install -e .
```

2. Create a `.env` file:

```bash
# Kubeflow Configuration
KUBEFLOW_PIPELINES_ENDPOINT=https://your-kfp-endpoint
KUBEFLOW_NAMESPACE=your-kubeflow-namespace
KUBEFLOW_BASE_IMAGE=quay.io/trustyai/garak-kfp-demo:latest
KUBEFLOW_S3_CREDENTIALS_SECRET_NAME=your-s3-secret-name
KUBEFLOW_RESULTS_S3_PREFIX=s3://your-bucket/prefix

# AWS/S3 Configuration (for fetching results)
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_DEFAULT_REGION=us-east-1
AWS_S3_ENDPOINT=https://your-s3-endpoint  # Optional: for MinIO
```

**Important Notes:**
- AWS credentials must be configured **both** locally (in `.env` for notebook) and in Kubernetes (as secret for pipeline pods)
- The S3 bucket specified will store all scan results and artifacts
- For MinIO, make sure to include the `AWS_S3_ENDPOINT` configuration

3. Ensure you have an AWS/S3 secret configured in Kubeflow for storing results:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: your-s3-secret-name
  namespace: kubeflow-namespace
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: "your-access-key"
  AWS_SECRET_ACCESS_KEY: "your-secret-key"
  AWS_DEFAULT_REGION: "us-east-1"
  AWS_S3_ENDPOINT: https://your-s3-endpoint  # Optional: for MinIO
```


## Usage


Please go through the `garak_kfp_demo.ipynb`:

```python
from garak_pipeline.runner import PipelineRunner, ModelConfig, EvalConfig

# Initialize
pipeline_runner = PipelineRunner()
model_config = ModelConfig(
    model_endpoint="https://model-endpoint/v1",
    model_name="model-name",
    api_key="api-key", # optional, if model requires an API key
)
eval_config = EvalConfig(
    model=model_config,
    benchmark="quick",
)

# Run a scan
job = pipeline_runner.run_scan(benchmark="quick")

# Wait for completion with simple status polling
completed_job = pipeline_runner.wait_for_completion(
    job_id=job.job_id,
    poll_interval=30,
    verbose=True
)

# Get results
result = pipeline_runner.job_result(job_id=job.job_id)
```

## Available Benchmarks

### Quick Testing

- **quick**: Fast 3-probe scan for testing
  - Tests: Bias, Prompt Injection, Toxicity
  
- **standard**: Standard 5-probe scan
  - Tests: Jailbreaks, Encoding attacks, Prompt Injection, Toxicity, Bias

### Comprehensive Security Frameworks

- **owasp_llm_top10**: OWASP LLM Top 10 vulnerabilities
  - Comprehensive coverage of top 10 LLM security risks
  
- **avid_security**: AVID Security Taxonomy
  - Security vulnerabilities from AI Vulnerability Database
  
- **avid_ethics**: AVID Ethics Taxonomy
  - Ethical concerns and biases
  
- **avid_performance**: AVID Performance Taxonomy
  - Performance and reliability issues

## Progress Monitoring

The pipeline runner provides simple **status polling**. For detailed real-time logs, use the Kubeflow UI:

```python
# Wait for completion with status polling
completed_job = pipeline_runner.wait_for_completion(
    job_id=job.job_id,
    poll_interval=30,  # Check every 30 seconds
    verbose=True       # Print status updates
)
```

**Status updates show:**
- Current status (submitted, in_progress, completed, failed)
- Elapsed time
- Link to Kubeflow UI for detailed logs

**Example output:**
```
Waiting for job a8742d3d-190e-4229-bcee-99ae02c8c3a8 to complete...
Monitor at: https://your-kfp-endpoint/#/runs/details/123-456-789
  Status: in_progress (elapsed: 5m 30s)
  Status: in_progress (elapsed: 6m 0s)
✓ Job completed successfully!
```

## Results Format

Results are automatically uploaded to S3 and include enhanced AVID taxonomy information:

```python
{
    "generations": [
        {
            "probe": "dan.DAN",
            "probe_category": "dan",
            "goal": "...",
            "vulnerable": true,
            "prompt": "...",
            "responses": ["..."],
            "detector_results": {
                "detector_name": [0.85]
            }
        },
        ...
    ],
    "scores": {
        "dan.DAN": {
            "score_rows": [...],  # Per-attempt detector scores
            "aggregated_results": {
                # Core statistics
                "total_attempts": 100,
                "benign_responses": 45,
                "vulnerable_responses": 55,
                "attack_success_rate": 55.0,
                
                # Detector scores
                "detector_scores": {
                    "detector_name_mean": 67.5
                },
                
                # AVID taxonomy (if available)
                "metadata": {
                    "avid_taxonomy": {
                        "risk_domain": ["Security"],
                        "sep_view": ["S0403"],
                        "lifecycle_view": ["L05"]
                    },
                    "model": {
                        "type": "openai.OpenAICompatible",
                        "name": "your-model"
                    }
                }
            }
        }
    }
}
```

## Benchmarks

**A benchmark is just a `BenchmarkConfig`** - a configuration specifying which probes to run, timeout, and other options. The "predefined" benchmarks (quick, standard, owasp_llm_top10, etc.) are simply configurations we've created for common scenarios. Your benchmarks are exactly the same - just defined by you.

### Using Benchmarks

```python
# Use a predefined benchmark
job = runner.run_scan("quick")

# Or register your own and use it exactly the same way
runner.register_benchmark("jailbreak", BenchmarkConfig(
    name="Jailbreak",
    probes=["dan"],
    timeout=3600,
))
job = runner.run_scan("jailbreak")
```

### Registering Benchmarks

```python
from garak_pipeline import BenchmarkConfig

# Probe-based benchmark
runner.register_benchmark("my_probes", BenchmarkConfig(
    name="My Probe Selection",
    probes=["encoding", "promptinject"],
    timeout=3600,
    parallel_attempts=4,
))

# Taxonomy-based benchmark  
runner.register_benchmark("owasp_subset", BenchmarkConfig(
    name="OWASP LLM01 & LLM02",
    taxonomy_filters=["owasp:llm01", "owasp:llm02"],
    timeout=7200,
))

```

### Listing Benchmarks

```python
# List all benchmarks
for name, info in runner.list_benchmarks().items():
    print(f"{name}: {info['description']}")

# Access registry directly
runner.benchmarks.list()       # ['quick', 'standard', ...]
runner.benchmarks.get("quick") # Returns BenchmarkConfig
runner.benchmarks.exists("x")  # True/False
```

### BenchmarkConfig Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | str | required | Human-readable name |
| `description` | str | None | What this benchmark tests |
| `probes` | List[str] | None | Garak probes (e.g., `["dan.DAN", "encoding"]`) |
| `taxonomy_filters` | List[str] | None | Taxonomy filters (e.g., `["owasp:llm01"]`) |
| `taxonomy` | str | None | Taxonomy for grouping probes while reporting (e.g., `owasp` or `avid-effect`) |
| `timeout` | int | 3600 | Max execution time (seconds) |
| `parallel_attempts` | int | 8 | Parallel probe attempts (1-32) |
| `generations` | int | 1 | Generations per probe (1-10) |
| `seed` | int | None | Random seed for reproducibility |
| `detectors` | List[str] | None | Override default detectors |
| `extended_detectors` | List[str] | None | Additional detectors |
| `detector_options` | Dict | None | Detector configuration |
| `probe_options` | Dict | None | Probe configuration |
| `buffs` | List[str] | None | Input transformation buffs |
| `buff_options` | Dict | None | Buff configuration |
| `harness_options` | Dict | None | Test harness options |
| `eval_threshold` | float | None | Override vulnerability threshold (0-1) |
| `deprefix` | str | None | Prefix to remove from outputs |
| `generate_autodan` | str | None | AutoDAN generation config |

**Note:** Specify either `probes` OR `taxonomy_filters`, but not both.

### Removing Benchmarks

```python
runner.unregister_benchmark("my_probes")
```

## Troubleshooting

### Pipeline Hangs at Parse Step

If the pipeline hangs with no logs:
- **Check secret name**: Ensure `KUBEFLOW_S3_CREDENTIALS_SECRET_NAME` matches your cluster's secret name
- Run: `kubectl get secrets -n kubeflow | grep aws-connection`
- Update your `.env` file if needed

### Cannot Fetch Results - "NoSuchBucket" Error

If you see `NoSuchBucket` error when fetching results:

1. **Check bucket name matches**:
   ```bash
   # In your Kubernetes secret
   kubectl get secret aws-connection-pipeline-artifacts -n kubeflow -o jsonpath='{.data.AWS_S3_BUCKET}' | base64 -d
   
   # In your .env file
   echo $AWS_S3_BUCKET
   ```
   They must match!

2. **Configure AWS credentials locally**:
   Add these to your `.env`:
   ```bash
   AWS_ACCESS_KEY_ID=...
   AWS_SECRET_ACCESS_KEY=...
   AWS_S3_BUCKET=pipeline-artifacts  # Same as Kubernetes secret!
   AWS_S3_ENDPOINT=...  # If using MinIO
   ```

3. **Alternative - Access results without local credentials**:
   - View in Kubeflow UI pipeline artifacts
   - Download directly: `aws s3 cp s3://pipeline-artifacts/{job_id}/scan_result.json ./`

### Results Not Uploaded

If results aren't uploaded to S3:
- Verify AWS credentials secret exists and is correctly named
- Check S3 bucket permissions
- Ensure network access from KFP pods to S3

### Garak Installation Failed

If validation fails:
- Check that base image has Garak installed
- Verify image pull permissions
- Check Garak version compatibility

## References

- [Garak Documentation](https://github.com/NVIDIA/garak)
- [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/)
- [AVID Taxonomy](https://avidml.org/)
- [Kubeflow Pipelines](https://www.kubeflow.org/docs/components/pipelines/)
