# Kubeflow ConfigMap keys and defaults for base image resolution
GARAK_PROVIDER_IMAGE_CONFIGMAP_NAME = "trustyai-service-operator-config"
GARAK_PROVIDER_IMAGE_CONFIGMAP_KEY = "garak-provider-image" # from https://github.com/opendatahub-io/opendatahub-operator/pull/2567
DEFAULT_GARAK_PROVIDER_IMAGE = "quay.io/rh-ee-spandraj/garak-kfp-demo:latest"
KUBEFLOW_CANDIDATE_NAMESPACES = ["redhat-ods-applications", "opendatahub"]