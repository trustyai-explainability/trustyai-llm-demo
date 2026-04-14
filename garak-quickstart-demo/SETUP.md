# Setup Guide

Infrastructure and configuration for running the Garak quickstart demo.

## Prerequisites

- Cluster set up per [CLUSTER_SETUP.md](CLUSTER_SETUP.md) (RHOAI 3.4, DSPA,
  MinIO secret patched)
- OpenShift CLI (`oc`) configured and logged in
- Python 3.12+
- Model serving endpoint (OpenAI-compatible API)
- For intents scans: judge and SDG model endpoints, and a policy CSV in S3

## Installation

```bash
pip install -e .
```

This pulls in the [llama-stack-provider-trustyai-garak](https://github.com/trustyai-explainability/llama-stack-provider-trustyai-garak) package which
provides the KFP pipeline, config resolution, result parsing, and HTML report
generation.

## Configuration

Create a `.env` file with your KFP connection details:

```bash
KUBEFLOW_PIPELINES_ENDPOINT=https://your-kfp-endpoint-route
KUBEFLOW_NAMESPACE=your-kubeflow-namespace
KUBEFLOW_S3_CREDENTIALS_SECRET_NAME=aws-connection-pipeline-artifacts
```

S3 bucket and credentials (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`,
`AWS_S3_ENDPOINT`, `AWS_S3_BUCKET`) are **read directly from the Data
Connection K8s secret** at runtime. The same secret is injected into KFP pods
via `use_secret_as_env`, so there is a single source of truth for both the
pipeline and the client.

> **Fallback:** If the secret cannot be read (e.g. RBAC restrictions), the
> client falls back to `AWS_*` environment variables.

### Model Auth Secret (Optional)

Create a secret for the target model if needed.

```
oc create secret generic my-models-secret -n "$NS" \
  --from-literal=api-key=<my-token>
```

If different models need different API keys (e.g., for intents scans, if target model and intents models use separate tokens), you can set them like:

```
oc create secret generic my-models-secret -n "$NS" \
  --from-literal=TARGET_API_KEY=<target-model-token> \
  --from-literal=JUDGE_API_KEY=<judge-model-token> \
  --from-literal=ATTACKER_API_KEY=<attacker-model-token> \
  --from-literal=EVALUATOR_API_KEY=<evaluator-model-token> \
  --from-literal=SDG_API_KEY=<sdg-model-token>
```

You only need to specify keys for roles that differ. Any role without a dedicated key falls back through: `{ROLE}_API_KEY → API_KEY → api-key → “DUMMY”`. For example, if only the SDG model uses a different token:

```
oc create secret generic my-models-secret -n "$NS" \
  --from-literal=api-key=<shared-token> \
  --from-literal=SDG_API_KEY=<sdg-specific-token>
```


### S3 Results Prefix (optional)

By default the runner reads results from the same bucket the pipeline writes to
(resolved from the Data Connection secret). To organize artifacts under a
sub-folder:

```bash
KUBEFLOW_RESULTS_S3_PREFIX=garak-results
```

This stores artifacts at `garak-results/{job_id}/` inside the secret's bucket.

## Running Locally

The cluster-internal Minio URL is not reachable from your laptop. Two options as explained in [Cluster Setup](CLUSTER_SETUP.md#running-the-notebook-locally):

### Option A -- HTTP Route (recommended for dev/demos)

Create a plain HTTP route and patch the Data Connection secret so both KFP pods
and your notebook use the same endpoint:

```bash
NS=your-namespace
oc expose svc/minio-dspa -n $NS --name=minio-dspa-external --port=9000
ENDPOINT="http://$(oc get route minio-dspa-external -n $NS -o jsonpath='{.spec.host}')"
oc patch secret aws-connection-pipeline-artifacts -n $NS --type=merge \
  -p "{\"stringData\":{\"AWS_S3_ENDPOINT\":\"$ENDPOINT\"}}"
```

No code changes needed -- the runner reads the endpoint from the secret.

### Option B -- Port-forward

Forward Minio locally and override the endpoint in your notebook (this only
affects the client, not KFP pods):

```bash
oc port-forward svc/minio-dspa -n your-namespace 9000:9000
```

```python
import os
os.environ["AWS_S3_ENDPOINT"] = "http://localhost:9000"
```

### Why not HTTPS?

The default HTTPS route uses HAProxy TLS termination, which can strip
`Content-Length` headers from proxied requests, causing `MissingContentLength`
errors on S3 uploads. The plain HTTP route bypasses this. Only use HTTP routes
on dev/test clusters.

## Disconnected Mode

For air-gapped clusters without internet access, pre-download HuggingFace
translation models to S3 and pass the path:

```python
job = runner.run_scan(EvalConfig(
    ...,
    hf_cache_path="s3://hf-models/models/hf-cache/",
))
```

The pipeline downloads the cache into each scan pod and sets `HF_HUB_CACHE`
automatically.

Required models for intents scans:
- `Helsinki-NLP/opus-mt-zh-en`
- `Helsinki-NLP/opus-mt-en-zh`

## Troubleshooting

### Pipeline fails at validation step
- Check S3 secret name matches: `kubectl get secrets -n <ns> | grep aws-connection`
- Ensure `AWS_S3_BUCKET` is set in the secret

### MissingContentLength on S3 uploads
- Caused by HTTPS OpenShift route stripping `Content-Length` headers
- **Fix:** Create a plain HTTP route (`oc expose svc/minio-dspa`) and update
  `AWS_S3_ENDPOINT` in the Data Connection secret (see above)
- Alternatively, use `oc port-forward` to bypass the route entirely

### NoSuchBucket when fetching results
- When `results_s3_prefix` is not set, the bucket is auto-resolved from the
  Data Connection secret (`AWS_S3_BUCKET`)
- If set, ensure the bucket in the prefix matches the secret's `AWS_S3_BUCKET`
  (the pipeline always writes to the secret's bucket)

### Intents scan fails -- missing model
- Ensure `intents_models` has at least a `judge` role configured
- If providing 2 of 3 roles (judge/attacker/evaluator), provide all 3 or just 1

### HuggingFace download fails (disconnected)
- Ensure `hf_cache_path` points to a valid S3 prefix with pre-downloaded models
- Models depend on the benchmark probes being used

## References

- [Garak Documentation](https://github.com/NVIDIA/garak)
- [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/)
- [AVID Taxonomy](https://avidml.org/)
- [Kubeflow Pipelines](https://www.kubeflow.org/docs/components/pipelines/)
