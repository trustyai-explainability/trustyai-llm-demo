# NeMo Guardrails Deployment with OpenTelemetry Tracing

Deploy NeMo Guardrails on OpenShift with end-to-end OpenTelemetry tracing via Tempo and MinIO.

## Prerequisites

- OpenShift cluster (4.14+)
- Tempo Operator installed
- OpenTelemetry Operator installed
- `oc` CLI authenticated to the cluster

## Architecture

```
NeMo Guardrails --[OTLP gRPC/TLS]---> Tempo Distributor
OTel Collector  --[OTLP gRPC/TLS]---> Tempo Distributor
Tempo           --[HTTPS/TLS]--------> MinIO (S3)
```

The NeMo Guardrails entrypoint detects `OTEL_EXPORTER_OTLP_ENDPOINT` and
wraps the server with `opentelemetry-instrument` for automatic SDK configuration.
All OTel env vars (endpoint, protocol, TLS certificate) are read natively by the SDK.

All inter-service TLS is handled by OpenShift service serving certificates.
The `tempo-ca-bundle` ConfigMap is auto-populated with the service CA by the
OpenShift service CA operator.

## Deployment Order

```bash
# 1. Namespace
oc apply -f namespace.yaml

# 2. CA bundle (must exist before Tempo references it)
oc apply -f tempo/ca-bundle-configmap.yaml

# 3. MinIO storage backend
oc apply -f minio/storage-secret.yaml
oc apply -f minio/service.yaml
oc apply -f minio/deployment.yaml

# Wait for MinIO to be ready (TLS cert is auto-generated from the service annotation)
oc rollout status deployment/minio -n trustyai-guardrails

# 4. TempoStack (requires MinIO + CA bundle + storage secret)
oc apply -f tempo/tempostack.yaml

# Wait for Tempo components to be ready
oc wait --for=condition=Ready tempostack/sample -n trustyai-guardrails --timeout=300s

# 5. OpenTelemetry Collector (requires Tempo distributor + CA bundle)
oc apply -f otel/collector.yaml

# 6. NeMo Guardrails
oc apply -f nemo/configmap.yaml
oc apply -f nemo/cr.yaml

# Wait for NeMo to be ready
oc rollout status deployment/nemo-guardrails -n trustyai-guardrails
```

## Customization

### MinIO credentials

Edit `minio/storage-secret.yaml` and replace the placeholder `access_key_id`
and `access_key_secret` values before applying.

### Guardrails configuration

Edit `nemo/configmap.yaml` to modify `config.yaml`, `rails.co`, or `actions.py`.
After applying changes, restart the deployment:

```bash
oc rollout restart deployment/nemo-guardrails -n trustyai-guardrails
```

### Disabling tracing

Remove the `OTEL_EXPORTER_OTLP_ENDPOINT` env var from `nemo/deployment.yaml`.
The entrypoint only enables `opentelemetry-instrument` when this variable is set.

## Verification

### Check all pods are running

```bash
oc get pods -n trustyai-guardrails
```

### Confirm OTel instrumentation is active

```bash
oc logs deployment/nemo-guardrails -n trustyai-guardrails -c nemo-guardrails | head -5
```

You should see:
```
OpenTelemetry enabled: endpoint=https://tempo-sample-distributor... service=nemo-guardrails
```

### Test the guardrail checks endpoint

```bash
oc exec deployment/nemo-guardrails -n trustyai-guardrails -c nemo-guardrails -- \
  curl -s http://localhost:8000/v1/guardrail/checks \
  -H "Content-Type: application/json" \
  -d '{"model": "", "messages": [{"role": "user", "content": "hello"}]}'
```

### Check traces in Jaeger UI

```bash
oc get route -n trustyai-guardrails -l app.kubernetes.io/component=query-frontend
```

Open the route URL in a browser and look for traces from `nemo-guardrails`.

## TLS Details

| Connection | Protocol | TLS Source |
|---|---|---|
| NeMo -> Tempo Distributor | OTLP gRPC (4317) | OpenShift service CA |
| OTel Collector -> Tempo Distributor | OTLP gRPC (4317) | OpenShift service CA |
| Tempo -> MinIO | HTTPS (9000) | OpenShift service CA |

All TLS certificates are auto-generated and rotated by the OpenShift service CA
operator. The `tempo-ca-bundle` ConfigMap is injected with the CA signing bundle
and mounted into services that need to verify these certificates.
