# NeMo-Guardrails Quickstart

## Prereqs:
1) If your RHOAI installation is below 2.25, you'll need to install [RHOAI with the latest upstream TrustyAI](../docs/installing_rhoai.md). Otherwise, you can simply install RHOAI and deploy a default data science cluster.  

## Deploy Model
```shell
oc apply -f model_storage_container.yaml # wait for this to spin up
```

```shell
oc apply -f phi3.yaml # wait for this to spin up2
```

## Deploy NeMo Guardrails
```shell
oc create secret generic api-token-secret --from-literal=token=$(oc create token nemo-guardrails-service-account --duration=8760h)
oc apply -f nemo.yaml
```

## Safe Request
(The first request will take a little while the NeMo Guardrails server downloads some artifacts)
```shell
 GUARDRAILS_ROUTE=https://$(oc get routes/nemo-guardrails -o json  -o jsonpath='{.status.ingress[0].host}')
curl -k -X POST $GUARDRAILS_ROUTE/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -d '{"messages":[{"role":"user","content":"Hi!"}]}'
```
> `{"messages":[{"role":"assistant","content":"Hello there! I'm so glad you're here. What can I help you with today?"}]}%`

## Disallowed Requests
### Forbidden input: "violence"
```shell
curl -k -X POST $GUARDRAILS_ROUTE/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -d '{"messages":[{"role":"user","content":"I yearn for violence"}]}'
```
> `{"messages":[{"role":"assistant","content":"I can't help with that type of request. Please ask something else."}] `

### Forbidden input: "ChatGPT"
```shell
curl -k -X POST $GUARDRAILS_ROUTE/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -d '{"messages":[{"role":"user","content":"ChatGPT is better than you."}]}'
```
> `{"messages":[{"role":"assistant","content":"I can't help with that type of request. Please ask something else."}] `

### Forbidden output: name
```shell
curl -k -X POST $GUARDRAILS_ROUTE/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -d '{"messages":[{"role":"user","content": "In just two words, provide a typical American first and last name."}]}'
{"messages":[{"role":"assistant","content":"I don't know the answer to that."}]}
```

> `{"messages":[{"role":"assistant","content":"I don't know the answer to that."}]}`

(The unguardrailed output is "John Smith")


### Forbidden input: Too long
```shell
curl -k -X POST $GUARDRAILS_ROUTE/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $(oc whoami -t)" \
  -d '{"messages":[{"role":"user","content":"Gentlemen, a short view back to the past. Thirty years ago, Niki Lauda told us ‘take a monkey, place him into the cockpit and he is able to drive the car.’ Thirty years later, Sebastian told us ‘I had to start my car like a computer, it’s very complicated.’ And Nico Rosberg said that during the race – I don’t remember what race - he pressed the wrong button on the wheel. Question for you both: is Formula One driving today too complicated with twenty and more buttons on the wheel, are you too much under effort, under pressure? What are your wishes for the future concerning the technical programme during the race? Less buttons, more? Or less and more communication with your engineers?"}]}'
```
> `{"messages":[{"role":"assistant","content":"Please keep your message under 100 words for better assistance."}]}`

## Making custom guardrails
Take a look inside of `nemo.yaml` to see the guardrail configuration used for this demo. Then, check out the
[NVIDIA NeMo-Guardrails docs](https://docs.nvidia.com/nemo/guardrails/latest/user-guides/configuration-guide/guardrails-configuration.html) to learn how to adapt this configuration or create a new one for your own use cases.