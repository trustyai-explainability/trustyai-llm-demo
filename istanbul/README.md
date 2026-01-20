#

```shell
oc apply -f kubectl apply -f https://raw.githubusercontent.com/red-hat-data-services/llama-stack-k8s-operator/main/release/operator.yam
```

```shell
oc apply -f model_storage_container.yaml
oc apply -f qwen3.yaml
```

```shell
oc apply -f serviceaccount.yaml

export TOKEN=$(oc create token guardrails-service-account --duration=8760h)
envsubst < distro.yaml | oc apply -f -
```w