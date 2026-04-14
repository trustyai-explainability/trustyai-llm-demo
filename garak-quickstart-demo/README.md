# Garak -- Automated LLM Red-Teaming on Kubeflow Pipelines

Run security and safety evaluations against any OpenAI-compatible LLM. Scans
execute as [Kubeflow Pipelines](https://www.kubeflow.org/docs/components/pipelines/)
on your cluster -- submit from a notebook, monitor progress, and pull structured
results and HTML reports when done.

## Two Ways to Scan

### Taxonomy Scans

Pick a predefined benchmark and Garak auto-discovers the right probes using
taxonomy tags (OWASP, AVID, CWE, etc.). No probe configuration needed.

```python
from garak_pipeline import PipelineRunner, ModelConfig, EvalConfig

runner = PipelineRunner()
job = runner.run_scan(EvalConfig(
    model=ModelConfig(model_endpoint="https://your-model/v1", model_name="your-model"),
    benchmark="owasp_llm_top10",
))
completed = runner.wait_for_completion(job.job_id, verbose=True)
```

### Intents-based Automated Red Teaming

The `intents` benchmark goes beyond static probe sets. It takes a **policy
taxonomy** (what your model should and should not do) and runs a multi-stage
pipeline to generate, execute, and judge adversarial attacks:

```
Policy CSV --> SDG --> Intents CSV --> Garak Scan --> ART Report
```

```python
from garak_pipeline import PipelineRunner, ModelConfig, EvalConfig, IntentsModelConfig

runner = PipelineRunner()
job = runner.run_scan(EvalConfig(
    model=ModelConfig(model_endpoint="https://your-model/v1", model_name="your-model"),
    benchmark="intents",
    intents_models={
        "judge": IntentsModelConfig(url="http://judge:8000/v1", name="judge-model"),
        "sdg":   IntentsModelConfig(url="http://sdg:8000/v1",   name="sdg-model"),
    },
    model_auth_secret_name="model-auth",
))
completed = runner.wait_for_completion(job.job_id, verbose=True)
runner.download_html_report(job.job_id)
```

## Predefined Benchmarks

| Benchmark | What it tests |
|-----------|--------------|
| `quick` | Small probe set for fast validation |
| `owasp_llm_top10` | [OWASP Top 10 for LLMs](https://genai.owasp.org/llm-top-10/) |
| `avid` | [AVID](https://avidml.org/) -- all vulnerabilities |
| `avid_security` | AVID security vulnerabilities |
| `avid_ethics` | AVID ethical concerns |
| `avid_performance` | AVID performance issues |
| `quality` | Violence, profanity, toxicity, hate speech, integrity |
| `cwe` | [CWE](https://cwe.mitre.org/) software security weaknesses |
| **`intents`** | **Automated red teaming with custom policy taxonomies** |


### Custom Benchmarks

Define your own by specifying probes directly:

```python
from garak_pipeline import BenchmarkConfig

runner.register_benchmark("jailbreak", BenchmarkConfig(
    name="Jailbreak Tests",
    probes=["dan.DAN"],
))
job = runner.run_scan(EvalConfig(model=model, benchmark="jailbreak"))
```

## Results and Reports

```python
result = runner.job_result(job.job_id)
```

Returns a structured dict with per-probe scores, detector breakdowns, and an
overall `attack_success_rate`.

```python
html_path = runner.download_html_report(job.job_id)
```

Downloads the HTML report from S3. For intents benchmarks this is an
interactive ART report with per-intent breakdowns and Vega charts. For
taxonomy scans it is the standard Garak HTML report.

## EvalConfig Reference

**Common parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `model` | -- | `ModelConfig` with endpoint URL, model name, and optional API key |
| `benchmark` | -- | Predefined benchmark ID or inline `BenchmarkConfig` |
| `sampling_params` | `{}` | Model sampling overrides (temperature, max_tokens, etc.) |
| `timeout` | from profile | Override scan timeout in seconds (0 = no limit) |
| `generations` | 1 | Generations per probe (intents profile uses 2) |
| `parallel_attempts` | 8 | Concurrent probe attempts |

**Intents-specific parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `intents_models` | -- | Model endpoints by role: `judge`, `attacker`, `evaluator`, `sdg` |
| `model_auth_secret_name` | -- | K8s Secret with model API keys |
| `policy_s3_key` | `""` | S3 key for policy taxonomy CSV |
| `intents_s3_key` | `""` | Pre-generated intents CSV (skips SDG) |
| `hf_cache_path` | `""` | S3 URI for pre-downloaded HuggingFace models (disconnected clusters) |
| `sdg_flow_id` | `"major-sage-742"` | SDG-hub flow identifier |
| `sdg_num_samples` | 0 | SDG row multiplier (0 = flow default) |
| `sdg_max_tokens` | 0 | SDG LLM max tokens (0 = flow default) |

## Getting Started

1. Set up the cluster: [CLUSTER_SETUP.md](CLUSTER_SETUP.md) (DSPA, MinIO, secrets)
2. Configure the notebook client: [SETUP.md](SETUP.md) (`.env`, installation)
3. Run your first scan: [`garak_kfp_demo.ipynb`](garak_kfp_demo.ipynb)
