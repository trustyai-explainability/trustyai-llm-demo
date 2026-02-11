#!/bin/bash

# Function to display usage
usage() {
  echo "Usage: $0 [--gpu|--cpu]"
  echo ""
  echo "Options:"
  echo "  --gpu    Generate detector YAMLs with GPU support (uses detector-gpu-template.yaml)"
  echo "  --cpu    Generate detector YAMLs for CPU-only (uses detector-cpu-template.yaml)"
  echo ""
  echo "If no option is provided, defaults to CPU."
  exit 1
}

# Function to sanitize names for Kubernetes
# - Convert to lowercase
# - Replace underscores with hyphens
# - Truncate to 53 chars (leaving room for "-detector" suffix = 63 total)
sanitize_k8s_name() {
  local name="$1"
  # Convert to lowercase, replace underscores with hyphens
  name=$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr '_' '-')
  # Truncate to 53 characters (63 - 10 for "-detector")
  if [ ${#name} -gt 53 ]; then
    name="${name:0:53}"
  fi
  echo "$name"
}

# Parse command line arguments
USE_GPU=false
TEMPLATE_FILE="detector-cpu-template.yaml"

if [ $# -gt 0 ]; then
  case "$1" in
    --gpu)
      USE_GPU=true
      TEMPLATE_FILE="detector-gpu-template.yaml"
      ;;
    --cpu)
      USE_GPU=false
      TEMPLATE_FILE="detector-cpu-template.yaml"
      ;;
    --help|-h)
      usage
      ;;
    *)
      echo "Error: Unknown option '$1'"
      echo ""
      usage
      ;;
  esac
fi

# Validate template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
  echo "Error: Template file '$TEMPLATE_FILE' not found!"
  exit 1
fi

# Model mapping: HuggingFace path|short name for Kubernetes resources
models=(
    "martin-ha/toxic-comment-model|toxicity"
    "ibm-granite/granite-guardian-hap-38m|hate-speech"
    "m2im/XLM-T_finetuned_violence_twitter|violence"
    "sivasothy-Tharsi/bert-uncased-finetuned-selfharm-detector|self-harm"
    "Mehdi009/Antisemitism_Harassment_Detection_Model|harassment"
    "protectai/deberta-v3-base-prompt-injection-v2|jailbreaks"
)

# Create deployments directory if it doesn't exist
mkdir -p deployments

echo "Generating detector YAML files in deployments/ directory..."
echo "Using template: $TEMPLATE_FILE"
if [ "$USE_GPU" = true ]; then
  echo "Mode: GPU-enabled"
else
  echo "Mode: CPU-only"
fi
echo ""

for entry in "${models[@]}"; do
  # Split on pipe character
  hf_path="${entry%%|*}"
  model_name_raw="${entry##*|}"
  model_path=$(basename "$hf_path")

  # Sanitize the model name for Kubernetes compliance
  model_name=$(sanitize_k8s_name "$model_name_raw")

  echo "Creating deployments/${model_name}-detector.yaml (from $model_name_raw)"

  # Replace variables in template
  sed -e "s/\${MODEL_NAME}/$model_name/g" \
      -e "s/\${MODEL_PATH}/$model_path/g" \
      "$TEMPLATE_FILE" > "deployments/${model_name}-detector.yaml"
done

echo ""
echo "Done! Generated YAML files:"
ls -1 deployments/*-detector.yaml 2>/dev/null || echo "No files generated"
