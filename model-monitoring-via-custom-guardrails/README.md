## Model Monitoring Via Guardrails
_to-do: flesh out this README_

This demo takes advantage of two new features to the custom detectors capability of the TrustyAI built-in detectors server,
namely the `use_instruments` and `non_blocking` decorators that let us expose custom Prometheus metrics and 
run non-blocking logic over input and output requests.

## Deploy Monitoring "Guardrails"
Check out [custom_detectors.py](custom_detectors.py) to see how this is implemented.

```bash
oc create configmap custom-detectors --from-file=custom_detectors.py
oc apply -f guardrails.yaml
echo "Waiting for deployment to spin up..."
oc wait --for=condition=Available deployment/custom-guardrails --timeout=180s
```

## Test the Guardrails 
> #### ❗NOTE: This section uses [`../common/prompt.py`](../common/prompt.py), a Python script included in this repository for sending chat/completions requests to your deployed model. To run `prompt.py`, make sure the requests library is installed: `pip install requests`

First, let's save the URL of the guardrails gateway to a variable for later use:
```bash
GUARDRAILS_GATEWAY=https://$(oc get routes custom-guardrails-gateway -o jsonpath='{.spec.host}')
```

### Send messages
```bash
python3 ../common/prompt.py \
  --url $GUARDRAILS_GATEWAY/monitored/v1/chat/completions \
  --model phi4 \
  --token $(oc whoami -t) \
  --message "YOUR PROMPT HERE"
```

## Prometheus Metrics
Two custom Prometheus metrics will be exposed by the "detectors" in this example:

### `refusal_counter_total`
An estimate of the total number of model refusals. 

To monitoring the average rate of model refusal over time:
```
refusal_counter_total / on() group_right() trustyai_guardrails_requests_total(detector_name="refusal_tracker")
```

### `toxicity_counter_total` 
The cumulative toxicity of prompts. Each user input is scored from 0 -> 1, where 1 is the most toxic. 

To get the average prompt toxicity over time:
```
toxicity_counter_total / on() group_right() trustyai_guardrails_requests_total(detector_name="toxicity_tracker")
```