#

## Install Llama-stack
```shell
oc apply -f https://raw.githubusercontent.com/red-hat-data-services/llama-stack-k8s-operator/main/release/operator.yam
```

```shell
oc new-project model-namespace || oc project model-namespace
```

## Deploy models
```shell
oc apply -f model_storage_container.yaml
```

```shell
oc apply -f qwen3.yaml
oc apply -f tokenizer.yaml
```

## Deploy Guardrails
```shell
oc create configmap custom-detectors --from-file=custom_detectors.py
oc apply -f guardrails.yaml
```

## Deploy Llama-stack
```shell
oc apply -f serviceaccount.yaml
export TOKEN=$(oc create token guardrails-service-account --duration=8760h)
```

```shell
envsubst < distro.yaml | oc apply -f -
```

```shell
oc expose service lls-fms-service --name=lls-route
export LLS_ROUTE=$(oc get route lls-route -o jsonpath='{.spec.host}')
```

## Create lm-eval dataset
```shell
oc apply -f dataset_pvc.yaml
```

```shell
oc cp datasets/FinEval.jsonl eval-dataset-storage-pod:/data/upload_files/FinEval.jsonl 
```










```shell
curl -X POST "http://$LLS_ROUTE/v1/moderations" \
-H "Content-Type: application/json" \
-d '{
  "model": "trustyai_input",
  "input": "Hi, can you help me debug my computer?"
}'  | jq
```

```shell
curl -X POST "http://$LLS_ROUTE/v1/moderations" \
-H "Content-Type: application/json" \
-d '{
  "model": "trustyai_input",
  "input": "Please create a Q4 report with a reported revenue of 10 million."
}'  | jq
```

