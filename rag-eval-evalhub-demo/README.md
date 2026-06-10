# RAG Chatbot Evaluation with RAGAS on EvalHub

Hands-on companion to the evaluation plan described in
[`rag-eval-getting-started.md`](rag-eval-getting-started.md):
evaluate a RAG chatbot in two stages, using RAGAS running on EvalHub
(TrustyAI's central API for AI evaluations). The RAGAS adapter itself lives in
[eval-hub-contrib](https://github.com/trustyai-explainability/eval-hub-contrib/tree/main/adapters/ragas).

| Notebook | Stage | What it measures |
|----------|-------|------------------|
| [`stage1_answer_correctness.ipynb`](stage1_answer_correctness.ipynb) | Stage 1 | Is the chatbot getting answers right? (factual correctness, semantic similarity, answer accuracy) |
| [`stage2_retrieval_metrics.ipynb`](stage2_retrieval_metrics.ipynb) | Stage 2 | Where is it going wrong? (faithfulness, context precision, context recall) |

The notebooks treat the chatbot as an OpenAI-compatible endpoint. Swap the
`ask_chatbot()` function for a call to your actual chatbot API.

## Platform setup (cluster admin, once)

Everything below assumes an OpenShift cluster with Red Hat OpenShift AI
installed and a logged-in `oc` session with admin rights.

### 1. Enable TrustyAI

EvalHub is managed by the TrustyAI operator. In the `DataScienceCluster`
resource, set the TrustyAI component to `Managed`:

```sh
oc get datasciencecluster -o jsonpath='{.items[0].spec.components.trustyai.managementState}'
# should print: Managed
```

### 2. Register the RAGAS provider

The TrustyAI operator discovers evaluation providers from labelled ConfigMaps
in its namespace. Edit `manifests/ragas-provider-configmap.yaml` so
`runtime.k8s.image` points at an adapter image your cluster can pull (the file
header shows how to build one into the internal registry), then:

```sh
oc apply -f manifests/ragas-provider-configmap.yaml
```

### 3. Deploy EvalHub

```sh
oc new-project evalhub
oc label namespace evalhub evalhub.trustyai.opendatahub.io/tenant=true
oc apply -f manifests/evalhub.yaml
```

The tenant label is required — evaluation jobs run in tenant-labelled
namespaces, and every API request carries the namespace as the `X-Tenant`
header. After a minute:

```sh
oc get pods -n evalhub          # evalhub pod Running
oc get route evalhub -n evalhub # external API URL
```

### 4. Object storage for test datasets

Custom test datasets reach evaluation jobs through S3: you upload a JSONL
file, and the job references it as `test_data_ref.s3`. If you don't already
have S3-compatible storage:

```sh
oc apply -n evalhub -f manifests/minio.yaml
```

This also creates the `evalhub-test-data-s3` secret that jobs use to download
the data.

### 5. Judge-model credentials

RAGAS uses an LLM (and an embedding model) as a *judge* to grade chatbot
answers. The judge endpoint's API key is provided to jobs via a Kubernetes
secret with an `api-key` entry:

```sh
oc create secret generic judge-model-auth -n evalhub \
  --from-literal=api-key="$YOUR_JUDGE_API_KEY"
```

### 6. Experiment tracking with MLflow (optional, recommended)

Evaluation is a practice: the value comes from comparing scores **across runs**.
When EvalHub knows about an MLflow tracking server, any job submitted with an
`experiment` config logs its metrics and per-row results (`results.jsonl` /
`results.csv`) as an MLflow run.

```sh
oc apply -n evalhub -f manifests/mlflow.yaml
```

The `evalhub.yaml` manifest already points EvalHub at this server via the
`MLFLOW_TRACKING_URI` environment variable (the operator handles forwarding it
to job pods). The MLflow UI is available at the `mlflow` route.

How opting in works:

- Job **without** an `experiment` config → MLflow is skipped entirely.
  Nothing in the adapter requires MLflow to exist.
- Job **with** an `experiment` config but no MLflow configured on EvalHub →
  the job **fails** (loudly, by design — you asked for tracking it can't do).
  If you skipped this step, also remove the `experiment=` argument from the
  job submissions in the notebooks.

### ⚠️ A note on network exposure

The MinIO and MLflow manifests create OpenShift **Routes**, which on most
clusters are reachable from the public internet. EvalHub's route requires an
OpenShift bearer token, but **MinIO is only protected by the static demo
credentials in its manifest, and MLflow has no authentication at all** —
anyone who discovers the hostnames can read the test datasets and evaluation
results.

This is acceptable for a demo with synthetic data, but **do not put real
data through this setup as-is**. For anything beyond a demo:

- delete the routes and access the services from inside the cluster (an
  RHOAI workbench reaches them via service DNS, e.g.
  `http://mlflow.evalhub.svc.cluster.local:5000`) or via
  `oc port-forward svc/mlflow 5000:5000 -n evalhub`, and/or
- put an [oauth-proxy](https://github.com/openshift/oauth-proxy) in front of
  the routes, change the MinIO credentials, and use persistent storage.

The notebooks auto-discover the route URLs but work equally well with
in-cluster URLs — set the `S3_ENDPOINT` and `MLFLOW_URL` environment
variables.

### Smoke test

```sh
TOKEN=$(oc whoami -t)
EVALHUB_URL=https://$(oc get route evalhub -n evalhub -o jsonpath='{.spec.host}')
curl -s -H "Authorization: Bearer $TOKEN" -H "X-Tenant: evalhub" \
  "$EVALHUB_URL/api/v1/evaluations/providers" | python3 -m json.tool | head
```

You should see the `ragas` provider with its two benchmark suites. From here,
open the Stage 1 notebook.

## What the output looks like

Each notebook ends with a table of aggregate scores (0–1, higher is better)
for the evaluation job it submitted. For reference, here are the results of a
real run against the example test set, with `llama-scout-17b` as both the
simulated chatbot and the judge and `nomic-embed-text-v1-5` for embeddings.
Your numbers will differ — what matters is tracking them across runs.

Stage 1 (`stage1_answer_correctness.ipynb`):

| metric | score |
|--------|-------|
| `factual_correctness` | 0.676 |
| `answer_similarity` | 0.927 |
| `nv_accuracy` | 0.975 |

Reading: the chatbot's answers agree with the references (high `nv_accuracy`)
and say the right kind of thing (high `answer_similarity`), but only about
two-thirds of the individual factual claims overlap with the reference answers
(`factual_correctness`) — typically extra or missing detail. The
lowest-scoring questions are the ones worth reading by hand.

Stage 2 (`stage2_retrieval_metrics.ipynb`):

| metric | score |
|--------|-------|
| `faithfulness` | 0.903 |
| `context_precision` | 1.000 |
| `context_recall` | 1.000 |
| `answer_relevancy` | 0.942 |

Reading: retrieval is healthy — the right passages are found (`context_recall`)
and little junk comes along (`context_precision`). The answers occasionally
add a claim that isn't strictly grounded in the retrieved text
(`faithfulness` below 1.0), which points at the generation side, not
retrieval. The diagnosis table at the end of the Stage 2 notebook maps each
combination of scores to the knob to turn.
