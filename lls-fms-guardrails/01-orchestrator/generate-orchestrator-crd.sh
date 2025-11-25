#!/bin/bash

# Function to display usage
usage() {
  echo "Usage: $0 [OPTIONS]"
  echo ""
  echo "Automatically generates manual-crd.yaml by discovering detector services"
  echo "with the 'trustyai/guardrails=true' label."
  echo ""
  echo "Options:"
  echo "  -n, --namespace <name>    Namespace to search for detector services (default: current context)"
  echo "  -t, --threshold <value>   Default detection threshold (default: 0.5)"
  echo "  -o, --output <file>       Output file (default: manual-crd.yaml)"
  echo "  -h, --help                Show this help message"
  echo ""
  echo "Examples:"
  echo "  $0                                    # Use current namespace"
  echo "  $0 -n testing                         # Search in 'testing' namespace"
  echo "  $0 -n testing -t 0.7                  # Custom threshold"
  echo "  $0 -n testing -o my-config.yaml       # Custom output file"
  echo ""
  exit 1
}

# Default values
NAMESPACE=""
DEFAULT_THRESHOLD="0.5"
OUTPUT_FILE="orchestrator-crd.yaml"

# Parse command line arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--namespace)
      NAMESPACE="$2"
      shift 2
      ;;
    -t|--threshold)
      DEFAULT_THRESHOLD="$2"
      shift 2
      ;;
    -o|--output)
      OUTPUT_FILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      ;;
    *)
      echo "Error: Unknown option '$1'"
      echo ""
      usage
      ;;
  esac
done

# If namespace not provided, use current context
if [ -z "$NAMESPACE" ]; then
  NAMESPACE=$(oc config view --minify -o jsonpath='{..namespace}')
  if [ -z "$NAMESPACE" ]; then
    echo "Error: Could not determine current namespace and none was provided"
    echo "Please specify a namespace with -n or set your current context"
    exit 1
  fi
  echo "Using current namespace: $NAMESPACE"
fi

echo "Discovering detector services in namespace: $NAMESPACE"
echo "Looking for services with label: trustyai/guardrails=true"
echo ""

# Get all services with the trustyai/guardrails label ending in -predictor
SERVICES=$(oc get services -n "$NAMESPACE" -l trustyai/guardrails=true -o json | \
  jq -r '.items[] | select(.metadata.name | endswith("-predictor")) | .metadata.name')

if [ -z "$SERVICES" ]; then
  echo "Error: No detector services found in namespace '$NAMESPACE'"
  echo "Make sure services are labeled with 'trustyai/guardrails=true'"
  exit 1
fi

echo "Found detector services:"
echo "$SERVICES" | sed 's/^/  - /'
echo ""

# Start building the YAML file
cat > "$OUTPUT_FILE" <<EOF
kind: ConfigMap
apiVersion: v1
metadata:
  name: fms-orchestr8-config-nlp
data:
  config.yaml: |
    detectors:
      built-in-detector:
        type: text_contents
        service:
            hostname: "127.0.0.1"
            port: 8080
        chunker_id: whole_doc_chunker
        default_threshold: $DEFAULT_THRESHOLD
EOF

# Add each discovered service
for SERVICE in $SERVICES; do
  SERVICE_INFO=$(oc get service "$SERVICE" -n "$NAMESPACE" -o json)
  TARGET_PORT=$(echo "$SERVICE_INFO" | jq -r '.spec.ports[] | select(.name=="http") | .targetPort // 8000')
  HOSTNAME="${SERVICE}.${NAMESPACE}.svc.cluster.local"

  echo "  Adding: $SERVICE (port: $TARGET_PORT)"

  # Append to config
  cat >> "$OUTPUT_FILE" <<EOF
      $SERVICE:
        type: text_contents
        service:
            hostname: "$HOSTNAME"
            port: $TARGET_PORT
        chunker_id: whole_doc_chunker
        default_threshold: $DEFAULT_THRESHOLD
EOF
done

# Add the GuardrailsOrchestrator CRD
cat >> "$OUTPUT_FILE" <<'EOF'
---
apiVersion: trustyai.opendatahub.io/v1alpha1
kind: GuardrailsOrchestrator
metadata:
  name: guardrails-orchestrator
  annotations:
    security.opendatahub.io/enable-auth: 'true'
spec:
  orchestratorConfig: "fms-orchestr8-config-nlp"
  enableBuiltInDetectors: true
  enableGuardrailsGateway: false
  replicas: 1
---
EOF

echo ""
echo "Successfully generated: $OUTPUT_FILE"
echo ""
echo "Configuration summary:"
echo "  Namespace:          $NAMESPACE"
echo "  Detector services:  $(echo "$SERVICES" | wc -l | tr -d ' ')"
echo "  Default threshold:  $DEFAULT_THRESHOLD"
echo ""
echo "Next steps:"
echo "  oc apply -f $OUTPUT_FILE"
