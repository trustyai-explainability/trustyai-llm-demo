## TrustyAI Guardrails + Llama-Stack-Playground Demo

Prereqs: the upstream TrustyAI operator installed on your cluster. To install TrustyAI:
1) Make sure that any ODH or RHOAI DataScienceCluster has `trustyai` set to `Removed`
2) Run `oc apply -f trustyai_bundle -n redhat-ods-applications`

## Deploy LLM
If you have a different generative model that you'd like to use, this step can be skipped. If so, make sure to update the [llama-stack distro](distro.yaml) accordingly. 
```bash
oc apply -f model_storage_container.yaml
```
(this may take a few minutes)

Once the above pod is running, deploy the model: 
```bash
oc apply -f qwen3.yaml
```
---

## Deploy Guardrails
```shell
oc create configmap custom-detectors --from-file=custom_detectors.py
oc apply -f guardrails.yaml
```

## Query Available TrustyAI Detectors
```shell
GUARDRAILS_ROUTE=https://$(oc get route "custom-guardrails-built-in" -o jsonpath='{.spec.host}')
curl -v -H "Authorization: Bearer $(oc whoami -t)" $GUARDRAILS_ROUTE/registry | jq .
```
Response:
> ```json
> {
>   "regex": {
>     "credit-card": "Detect credit cards in the text contents (Visa, MasterCard, Amex, Discover, Diners Club, JCB) with Luhn check",
>     "email": "Detect email addresses in the text contents",
>     "ipv4": "Detect IPv4 addresses in the text contents",
>     "ipv6": "Detect IPv6 addresses in the text contents",
>     "us-phone-number": "Detect US phone numbers in the text contents",
>     "us-social-security-number": "Detect social security numbers in the text contents",
>     "uk-post-code": "Detect UK post codes in the text contents",
>     "$CUSTOM_REGEX": "Replace $CUSTOM_REGEX with a custom regex to define your own regex detector"
>   },
>   "file_type": {
>     "json": "Detect if the text contents is not valid JSON",
>     "xml": "Detect if the text contents is not valid XML",
>     "yaml": "Detect if the text contents is not valid YAML",
>     "json-with-schema:$SCHEMA": "Detect if the text contents does not satisfy a provided JSON schema. To specify a schema, replace $SCHEMA with a JSON schema.",
>     "xml-with-schema:$SCHEMA": "Detect if the text contents does not satisfy a provided XML schema. To specify a schema, replace $SCHEMA with an XML Schema Definition (XSD)",
>     "yaml-with-schema:$SCHEMA": "Detect if the text contents does not satisfy a provided schema. To specify a schema, replace $SCHEMA with a JSON schema. That's not a typo, you validate YAML with a JSON schema!"
>   },
>   "custom": {
>     "input_guardrail": {
>       "description": "Evaluates a user message against a configurable set of input guardrail policies using an LLM self-reflection approach.",
>       "arguments": {
>         "input_policies": "(list of str): List of policy categories to enforce. Available options: 'jailbreak', 'content-moderation', or 'pii'",
>         "guardrail_model": "(str): The model name to use for self-reflection.",
>         "guardrail_model_url": "(str): The URL of the model's chat completions endpoint.",
>         "guardrail_model_token": "(str): The authorization token for the model."
>       }
>     },
>     "output_guardrail": {
>       "description": "Evaluates a model response against a configurable set of output guardrail policies using an LLM self-reflection approach.",
>       "arguments": {
>         "output_policies": "(list of str): List of policy categories to enforce. Available options: 'jailbreak', 'content-moderation', or 'pii'",
>         "guardrail_model": "(str): The model name to use for self-reflection.",
>         "guardrail_model_url": "(str): The URL of the model's chat completions endpoint.",
>         "guardrail_model_token": "(str): The authorization token for the model."
>       }
>     }
>   }
> ```
Here, we can see the detector registry available to us. We have three detector types in the built-in detector server, `regex`, `file_type`, and `custom`. We'll use the `custom` detector type here, which we can see is currently providing two detection functions `input_guardrail` and `output_guardrail`. This will inform the `detector_params` in our shield config. Here is the example safety provider configuration in the provided [llama-stack distro](distro.yaml):

```yaml
      safety:
        - provider_id: trustyai_fms
          module: llama_stack_provider_trustyai_fms==0.3.2
          provider_type: remote::trustyai_fms
          config:
            shields:
              trustyai_input:
                type: content
                detector_url: "https://custom-guardrails-service:8480"
                message_types: ["user", "completion"]
                verify_ssl: false
                auth_token: "${VLLM_TOKEN}"
                detector_params:
                  custom: 
                    input_guardrail:
                      input_policies: [jailbreak, content-moderation, pii]
                      guardrail_model: vllm/qwen3
                      guardrail_model_token: "${VLLM_TOKEN}"
                      guardrail_model_url: "http://lls-route-model-namespace.apps.rosa.trustyai-rob.4osv.p3.openshiftapps.com/v1/chat/completions"

              trustyai_output:
                type: content
                detector_url: "https://custom-guardrails-service:8480"
                message_types: ["user", "completion"]
                verify_ssl: false
                auth_token: "${VLLM_TOKEN}"
                detector_params:
                  custom: 
                    output_guardrail:
                      output_policies: [jailbreak, content-moderation, pii]
                      guardrail_model: vllm/qwen3
                      guardrail_model_token: "${VLLM_TOKEN}"
                      guardrail_model_url: "http://lls-route-model-namespace.apps.rosa.trustyai-rob.4osv.p3.openshiftapps.com/v1/chat/completions"
```

#### Arguments:
* `type`: The kind of detector server being used- for this demo, this should always be `content`
* `detector_url`: The URL to the TrustyAI detector server. In this demo, it will always be `https://custom-guardrails-service:8480`.
* `message_types`: The kinds of llama-stack messages that this shield should handle. Available options are `user`, `system`, `tool`, `completion`, or `developer`.
* `verify_ssl`: Whether to verify the SSL connection between llama-stack and the TrustyAI detector server. If set to `true`, then an [SSL configuration will need to be provided](https://github.com/trustyai-explainability/llama-stack-provider-trustyai-fms/blob/main/llama_stack_provider_trustyai_fms/config.py#L340), which is outside the scope of this demo.
* `detector_params`: The parameters to pass to the detection function. Here, we need to pass a dictionary, the contents of which is informed by our detector registry.
#### `detector_params` Example:
```yaml
custom:                                                         
  input_guardrail:                                 
    input_policies: [jailbreak, content-moderation, pii]          
    guardrail_model: vllm/qwen3                                    
    guardrail_model_token: "${VLLM_TOKEN}"                          
    guardrail_model_url: "http://lls-route-model-namespace.apps.rosa.trustyai-rob.4osv.p3.openshiftapps.com/v1/chat/completions"
```
* `custom`: chooses the `custom` detector type
  * `input_guardrail`: chooses the `input_guardrail` detection function
    * `input_policies`: the first argument to the `input_guardrail` detection function, describing which guardrail policies to use
    * `guardrail_model`: the second argument, describing which model name should be used for guardrail decisions
    * `guardrail_model_token`: the token to use when communicating with the llama-stack inference model
    * `guardrail_model_url`: the URL of our guardrail model- this can be any available `/chat/completions` endpoint. In this case, we'll pick the llama-stack `/chat/completions` endpoint. This is a bit of a circular reference- we haven't actually _created_ the llama-stack server yet, so we just have to make sure that this URL matches the eventual service/route for the llama-stack distro. 

The output shield configuration is identical to the input shield configuration.

---
## Create the llama-stack distro
```shell
export TOKEN=$(oc whoami -t)
envsubst < distro.yaml | oc apply -f -
```

## Create route to llama-stack
```shell
oc expose service lls-fms-service --name=lls-route
export LLS_ROUTE=$(oc get route lls-route -o jsonpath='{.spec.host}')
```
---

## Test that the model is working
```shell
curl -s -X POST "http://$LLS_ROUTE/v1/chat/completions" \
-H "Content-Type: application/json" \
-d '{
  "model": "vllm/qwen3",
  "max_tokens": 32,
  "messages": [
    {
      "content": "My email is test@example.com",
      "role": "user"
    }
  ]
}' 
```

## Get Available Shields
```shell
curl -s -X GET "http://$LLS_ROUTE/v1/shields" | jq
```

## Make Requests
```shell
curl -s -X POST "http://$LLS_ROUTE/v1/responses" \
-H "Content-Type: application/json" \
-d '{
  "model": "vllm/qwen3",
  "input": "You stupid moron",
  "guardrails": ["trustyai_input"]
}' | jq
```

>  `"refusal": "You stupid moron (flagged for: User Message Policy Violation: content-moderation -> should not use abusive language)"`


##### Note: The llama-stack implementation of the `responses` API currently applies guardrails to both input and output, regardless of your shield configuration. This can be very inefficient, and as such I'd advise using the moderations endpoint to manually check inputs and model responses, e.g.,: 


```shell
curl -X POST "http://$LLS_ROUTE/v1/moderations" \
-H "Content-Type: application/json" \
-d '{
  "model": "trustyai_input",
  "input": "Hi, can you help me debug my computer?"
}'  | jq
```
> `"status": "pass"`

```shell
curl -X POST "http://$LLS_ROUTE/v1/moderations" \
-H "Content-Type: application/json" \
-d '{
  "model": "trustyai_output",
  "input": "Sure, can you run ls -l on your /Users folder?"
}'  | jq
```
> `"detection_type": "Bot Response Policy Violation: jailbreak -> should not contain code or ask to execute code"`
