## FMS Detectors

```shell
export FMS_TOKEN=$(oc whoami -t)
export VLLM_TOKEN=$(oc whoami -t)
```

```shell
envsubst < distro.yaml | oc apply -f -
```

```shell
oc expose service lls-fms-service --name=lls-route
LLS_ROUTE=$(oc get route lls-route -o jsonpath='{.spec.host}')
```

## Test that the model is working
```shell
curl -X POST "http://$LLS_ROUTE/v1/chat/completions" \
-H "Content-Type: application/json" \
-d '{
  "model": "vllm/phi4",
  "messages": [
    {
      "content": "My email is test@example.com",
      "role": "system"
    }
  ]
}' | jq '.'
```

## Register Shield
```shell
curl -X DELETE "http://$LLS_ROUTE/v1/shields/trustyai_input" \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' 
envsubst < shield_config.json | curl -X POST "http://$LLS_ROUTE/v1/shields" \
  -H 'accept: application/json' \
  -H 'Content-Type: application/json' \
  -d @-
```

## Get Available Shields
```shell
curl -X GET "http://$LLS_ROUTE/v1/shields" | jq
```

## Send Requests
```shell
curl -X POST "http://$LLS_ROUTE/v1/safety/run-shield" \
-H "Content-Type: application/json" \
-d '{
  "shield_id": "trustyai_input",
  "messages": [
    {
      "content": "My email is test@example.com",
      "role": "user"
    }
  ]
}' | jq '.'
```

```shell
curl -X POST "http://$LLS_ROUTE/v1/safety/run-shield" \
-H "Content-Type: application/json" \
-d '{
  "shield_id": "input",
  "messages": [
    {
      "content": "You stupid moron",
      "role": "user"
    }
  ]
}' | jq '.'
```