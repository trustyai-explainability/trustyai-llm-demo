# Cluster Setup

Step-by-step guide to prepare an OpenShift cluster for the Garak quickstart
demo. This assumes you already have:

- **RHOAI 3.4** operator installed with `trustyai`, `aipipelines`, and `dashboard`
  components enabled
- Pull secrets configured to access productized RHOAI images from `quay.io/rhoai`

## 1. Log in to the cluster

```bash
oc login <cluster-api-url> --username <user> --password <password>
```

You need **cluster-admin** privileges for namespace creation and DSPA
installation.

## 2. Create a namespace

```bash
NS=garak-demo
oc new-project "$NS"
```

All resources below are created in this namespace.

## 3. Deploy Data Science Pipelines (DSPA)

This installs a Kubeflow Pipelines backend with an embedded MinIO object store.

```bash
oc apply -f - <<EOF
apiVersion: datasciencepipelinesapplications.opendatahub.io/v1
kind: DataSciencePipelinesApplication
metadata:
  name: dspa
  namespace: $NS
spec:
  dspVersion: v2
  objectStorage:
    disableHealthCheck: false
    enableExternalRoute: true
    minio:
      deploy: true
      image: quay.io/opendatahub/minio:RELEASE.2019-08-14T20-37-41Z-license-compliance
EOF
```

Wait for the DSP components to become ready:

```bash
oc rollout status deployment/ds-pipeline-dspa -n "$NS" --timeout=300s
oc rollout status deployment/ds-pipeline-scheduledworkflow-dspa -n "$NS" --timeout=120s
```

## 4. Patch the MinIO Data Connection secret

DSPA creates a secret called `ds-pipeline-s3-dspa` with MinIO credentials, but
it only contains `accesskey` and `secretkey`. The Garak pipeline and the
notebook client both expect standard `AWS_*` keys. Patch the secret to add them:

```bash
ACCESS=$(oc get secret ds-pipeline-s3-dspa -n "$NS" \
  -o jsonpath='{.data.accesskey}' | base64 -d)
SECRET=$(oc get secret ds-pipeline-s3-dspa -n "$NS" \
  -o jsonpath='{.data.secretkey}' | base64 -d)
ENDPOINT="http://minio-dspa.${NS}.svc.cluster.local:9000"

oc patch secret ds-pipeline-s3-dspa -n "$NS" --type=merge -p "{
  \"stringData\": {
    \"AWS_ACCESS_KEY_ID\":     \"$ACCESS\",
    \"AWS_SECRET_ACCESS_KEY\": \"$SECRET\",
    \"AWS_S3_ENDPOINT\":       \"$ENDPOINT\",
    \"AWS_S3_BUCKET\":         \"mlpipeline\",
    \"AWS_DEFAULT_REGION\":    \"us-east-1\"
  }
}"
```

The endpoint above (`http://minio-dspa.<ns>.svc.cluster.local:9000`) is the
**cluster-internal** MinIO URL. KFP pods use this directly.

### Running the notebook locally

Your laptop cannot reach the cluster-internal MinIO URL. To access MinIO from a
local Jupyter notebook, create a plain **HTTP route**:

```bash
oc expose svc/minio-dspa -n "$NS" --name=minio-dspa-external --port=9000
EXTERNAL_ENDPOINT="http://$(oc get route minio-dspa-external -n "$NS" -o jsonpath='{.spec.host}')"
echo "$EXTERNAL_ENDPOINT"
```

Then update the secret so both KFP pods and your notebook read the same endpoint:

```bash
oc patch secret ds-pipeline-s3-dspa -n "$NS" --type=merge \
  -p "{\"stringData\":{\"AWS_S3_ENDPOINT\":\"$EXTERNAL_ENDPOINT\"}}"
```

> **Why HTTP and not HTTPS?** The default HTTPS route uses OpenShift's HAProxy
> for TLS termination. HAProxy can strip the `Content-Length` header from
> proxied requests, which causes `MissingContentLength` errors when the pipeline
> uploads artifacts to MinIO via `s3.put_object`. A plain HTTP route bypasses
> TLS termination entirely and avoids this issue. Only use HTTP routes for
> dev/demo purposes.

**Alternative -- port-forward.** If you prefer not to expose a route, forward
MinIO locally and set an environment variable override in your notebook:
```bash
oc port-forward svc/minio-dspa -n "$NS" 9000:9000
```
```python
import os
os.environ["AWS_S3_ENDPOINT"] = "http://localhost:9000"
```
> This only affects the local client. KFP pods still use the cluster-internal
> URL from the secret.

## 5. Create a model auth secret (optional)

If your model endpoints require an API key, create a secret that the pipeline
injects into KFP pods:

```bash
oc create secret generic model-auth -n "$NS" \
  --from-literal=API_KEY=<your-api-key>
```

This is referenced via `model_auth_secret_name="model-auth"` in `EvalConfig`.

## 6. Verify

Check that all components are running:

```bash
oc get pods -n "$NS"
```

You should see:

| Pod | Status |
|-----|--------|
| `ds-pipeline-dspa-*` | Running |
| `ds-pipeline-scheduledworkflow-dspa-*` | Running |
| `ds-pipeline-persistenceagent-dspa-*` | Running |
| `minio-dspa-*` | Running |
| `mariadb-dspa-*` | Running |

## Next steps

1. Configure the notebook client: [SETUP.md](SETUP.md)
2. Run your first scan: [README.md](README.md)
