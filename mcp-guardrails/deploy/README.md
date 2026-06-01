# NeMo Guardrails Server Helm Chart

A Helm chart for deploying the TrustyAI NeMo Guardrails server on Openshift/Kubernetes

## Table of Contents
[I. Quick Start](#quick-start)

[II. Advanced Usage](#advanced-usage)

[III. Helm Chart Values](#values)

## Quick Start

Define a environment variable for the namespace. Replace `<GUARDRAILS_NAMESPACE>` below before running the full command:

```bash
export GUARDRAILS_NS=<GUARDRAILS_NAMESPACE> && echo "$GUARDRAILS_NS"

```

Create the namespace, a service account, and a secret with its token before installing:

```bash
# Creates a namespace based on the previous command
kubectl create namespace "$GUARDRAILS_NS" || true

# Creates a ServiceAccount and Secret to authenticate to an OpenAI-compatible inference endpoint
kubectl create serviceaccount nemo-guardrails-service-account -n "$GUARDRAILS_NS"

kubectl create secret generic api-token-secret -n "$GUARDRAILS_NS" \
  --from-literal=token=$(kubectl create token nemo-guardrails-service-account -n "$GUARDRAILS_NS" --duration=8760h)
```

Install NeMo Guardrails:
```bash
# Creates a ConfigMap, Deployment, and Service for NeMo Guardrails
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NS"
```

Retrieve the NeMo Guardrails pod name:

```bash
export NEMO_POD=$(kubectl get pods -n ${GUARDRAILS_NS} -l app=nemoguardrails -o jsonpath='{.items[0].metadata.name}') && echo "$NEMO_POD"
```

Wait for the NeMo Guardrails pod to become Ready before port-forwarding the NeMo Guardrails pod:

```bash
kubectl wait --for=condition=Ready pods/$NEMO_POD --timeout=200s -n "$GUARDRAILS_NS" &&
kubectl port-forward pod/${NEMO_POD} 8000:8000 -n "$GUARDRAILS_NS"
```

In a new terminal window and send a request to the `v1/guardrails/checks` endpoint:

```bash
curl -s -X POST http://localhost:8000/v1/guardrail/checks \
  -H "Content-Type: application/json" \
  -d '{
    "model": "",
    "messages": [{"role": "user", "content": "Hello! My name is Christina, my email address is xxx@gmail.com"}],
    "guardrails": {
      "options": {
        "output_vars": ["triggered_input_rail"]
      }
    }
  }' | python3 -m json.tool
```

## Advanced Usage

### Install with custom image

```bash
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NS" \
  --set image.repository=quay.io/christinaexyou/nemo-guardrails-dev \
  --set image.tag=multiarch
```

### Install with OpenShift Route

```bash
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NS" \
  --set route.enabled=true
```

### Install with Istio EnvoyFilter (MCP SSE stripping)

Creates an `EnvoyFilter` in `envoyFilter.gatewayNamespace`. Note that this resource lives outside the release namespace and will **not** be removed by `helm uninstall`.

```bash
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NS" \
  --set envoyFilter.enabled=true \
  --set envoyFilter.gatewayNamespace=istio-system
```

### Upgrade

```bash
helm upgrade nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NS"
```

### Uninstall

```bash
helm uninstall nemoguardrails --namespace "$GUARDRAILS_NS"
```

## Values

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `1` | Number of server replicas |
| `image.repository` | `quay.io/rgeada/nemo-debug:latest` | Container image repository |
| `image.tag` | `latest` | Container image tag |
| `image.pullPolicy` | `Always` | Image pull policy |
| `env` | `[{ name: LOG_LEVEL, value: "DEBUG" }]` | Extra container env vars |
| `route.enabled` | `false` | Create an OpenShift Route for external access |
| `envoyFilter.enabled` | `false` | Create an Istio EnvoyFilter for MCP SSE stripping |
| `envoyFilter.gatewayNamespace` | `gateway-system` | Namespace of the Istio gateway workload |
| `envoyFilter.gatewayName` | `mcp-gateway` | Name of the gateway workload to target |
