# NeMo Guardrails Server Helm Chart

A Helm chart for deploying the TrustyAI NeMo Guardrails server on Openshift/Kubernetes

All Kubernetes resources are named after the Helm release (`helm install <release-name> ...`) and created in the namespace passed via `--namespace`.

## Prerequisites

Create the namespace, a service account, and a secret with its token before installing:

```bash
kubectl create namespace "$GUARDRAILS_NAMESPACE" || true
kubectl create serviceaccount nemo-guardrails-service-account -n "$GUARDRAILS_NAMESPACE"
kubectl create secret generic api-token-secret -n "$GUARDRAILS_NAMESPACE" \
  --from-literal=token=$(kubectl create token nemo-guardrails-service-account -n "$GUARDRAILS_NAMESPACE" --duration=8760h)
```

## Install

```bash
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NAMESPACE"
```

### With custom image

```bash
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NAMESPACE" \
  --set image.repository=quay.io/christinaexyou/nemo-guardrails-dev \
  --set image.tag=multiarch
```

### With OpenShift Route

```bash
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NAMESPACE" \
  --set route.enabled=true
```

### With Istio EnvoyFilter (MCP SSE stripping)

Creates an `EnvoyFilter` in `envoyFilter.gatewayNamespace`. Note that this resource lives outside the release namespace and will **not** be removed by `helm uninstall`.

```bash
helm install nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NAMESPACE" \
  --set envoyFilter.enabled=true \
  --set envoyFilter.gatewayNamespace=istio-system
```

## Upgrade

```bash
helm upgrade nemoguardrails ./mcp-guardrails/deploy \
  --namespace "$GUARDRAILS_NAMESPACE"
```

## Uninstall

```bash
helm uninstall nemoguardrails --namespace "$GUARDRAILS_NAMESPACE"
```

## Values

| Key | Default | Description |
|-----|---------|-------------|
| `replicaCount` | `1` | Number of server replicas |
| `image.repository` | `quay.io/trustyai/nemo-guardrails-server` | Container image repository |
| `image.tag` | `latest` | Container image tag |
| `image.pullPolicy` | `IfNotPresent` | Image pull policy |
| `env` | `[{ name: LOG_LEVEL, value: "DEBUG" }]` | Extra container env vars |
| `route.enabled` | `false` | Create an OpenShift Route for external access |
| `envoyFilter.enabled` | `false` | Create an Istio EnvoyFilter for MCP SSE stripping |
| `envoyFilter.gatewayNamespace` | `gateway-system` | Namespace of the Istio gateway workload |
| `envoyFilter.gatewayName` | `mcp-gateway` | Name of the gateway workload to target |

## Usage

Retrieve the NeMo Guardrails pod name:

```bash
export NEMO_POD=$(kubectl get pods -n ${GUARDRAILS_NAMESPACE} -l app=nemoguardrails -o jsonpath='{.items[0].metadata.name}') && echo "$NEMO_POD"
```

Port-forward the NeMo Guardrails pod:

```bash
kubectl port-forward pod/${NEMO_POD} 8000:8000 -n "$GUARDRAILS_NAMESPACE"
```

In a new terminal window and send a request to the `v1/chat/completions` endpoint:

```bash
curl -s -X POST http://localhost:8000/v1/chat/completions \
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

