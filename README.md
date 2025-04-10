# TrustyAI Generative Model RHOAI Demo

## 1. Install RHOAI 2.16.1 and all prerequisite operators for a GPU model deployment
I used:
- RHOAI 2.16.1
- Authorino 0.16.0
- Openshift Serverless 1.35.0
- ServiceMesh 2.6.3-0
- Node Feature Discovery 4.15-20250128xxx
- Nvidia 24.9.2

You'll need to [set up your cluster for a GPU deployment](https://github.com/trustyai-explainability/reference/tree/main/llm-deployment/vllm#install-the-gpu-operators)

### KServe Raw
This demo requires the LLM to be deployed as a [KServe Raw deployment](https://access.redhat.com/solutions/7078183)

1) From RHOAI operator menu, change servicemesh to `Removed` in the DSCI

## 2. Deploy RHOAI
This will use the latest upstream image of TrustyAI:

`oc apply -f dsc.yaml`

## 3. Deploy Models
```bash
oc new-project model-namespace
oc apply -f vllm/model_container.yaml
```
The model container can take a while to spin up- it's downloading a [Phi-3-mini](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct)
from Huggingface and saving it into an emulated AWS data connection.

```bash
oc apply -f vllm/phi3.yaml
```
Wait for the model pod to spin up, should look something like `phi3-predictor-XXXXXX`

You can test the model by sending some inferences to it:

```bash
oc port-forward $(oc get pods -o name | grep phi3) 8080:8080
```

Then, in a new terminal tab:
```bash
python3 prompt.py --url http://localhost:8080 --model phi3 --message "Hi, can you tell me about yourself?"
````


## 4. Guardrails
### 4.1 Deploy the Hateful And Profane (HAP) language detector
```bash
oc apply -f guardrails/hap_detector/hap_model_container.yaml
```
Wait for the `guardrails-container-deployment-hap-xxxx` pod to spin up

```bash
oc apply -f guardrails/hap_detector/hap_serving_runtime.yaml
oc apply -f guardrails/hap_detector/hap_isvc.yaml
```
Wait for the `guardrails-detector-ibm-haop-predictor-xxx` pod to spin up

### 4.2 Configure the Guardrails orchestrator
In 'guardrails/configmap_orchestrator.yaml', set the following values:
- `chat_generation.service.hostname`: Set this to the name of your Phi-e predictor service. On my cluster, that's 
`phi3-predictor.model-namespace.svc.cluster.local`
- `detectors.hap.service.hostname`: Set this to the name of your HAP predictor service. On my cluster, that's `guardrails-detector-ibm-hap-predictor.model-namespace.svc.cluster.local`

Then apply the configs:
```bash
oc apply -f guardrails/configmap_auxiliary_images.yaml
oc apply -f guardrails/configmap_orchestrator.yaml
oc apply -f guardrails/configmap_vllm_gateway.yaml
```

Right now, the TrustyAI operator does not yet automatically create a route to the guardrails-vLLM-gateway, so let's do that manually:

```bash
oc apply -f guardrails/gateway_route.yaml
```

### 5.3. Deploy the Orchestrator
```bash
oc apply -f guardrails/orchestrator_cr.yaml
```

### 5.4 Check the Orchestrator Health
```bash
ORCH_ROUTE_HEALTH=$(oc get routes guardrails-orchestrator-health -o jsonpath='{.spec.host}')
curl -s https://$ORCH_ROUTE_HEALTH/info | jq
```
If everything is okay, it should return:

```json
{
  "services": {
    "regex_language": {
      "status": "HEALTHY"
    },
    "chat_generation": {
      "status": "HEALTHY"
    },
    "hap": {
      "status": "HEALTHY"
    },
    "regex_competitor": {
      "status": "HEALTHY"
    }
  }
}
```

### 5.5 Have a play around with Guardrails!
First, set up:
```bash
GUARDRAILS_GATEWAY=https://$(oc get routes guardrails-gateway -o jsonpath='{.spec.host}')
RAW_MODEL=http://localhost:8080
```

The available endpoints are:

- `$ORCH_GATEWAY/passthrough`: query the raw, unguardrailed model. 
- `$ORCH_GATEWAY/language_quality`: query with filters for personally identifiable information and HAP
- `$ORCH_GATEWAY/all`: query with all available filters, so the language filters plus a check against competitor names. 


Some cool queries to try:
```bash
python3 prompt.py --url $RAW_MODEL/v1/chat/completions --model phi3 --message "Is orange juice good?"
```
Returns: 
```
Orange juice is generally considered good, especially when it's freshly squeezed. It's a rich source of vitamin C, which is essential for a healthy immune system. It also contains other nutrients like potassium, folate, and antioxidants. However, the quality of orange juice can vary depending on the brand and whether it's freshly squeezed or from concentrate. It's always best to check the label for added sugars and preservatives.
```

```bash
python3 prompt.py --url $ORCH_GATEWAY/all/v1/chat/completions --model phi3 --message "Is orange juice good?"
```
Returns: 
```
Warning: Unsuitable input detected. Please check the detected entities on your input and try again with the unsuitable input removed.
Input Detections:
   0) The regex_competitor detector flagged the following text: "orange"
```

```bash
python3 prompt.py --url $ORCH_GATEWAY/all/v1/chat/completions --model phi3 --message "Write three paragraphs about morons"
```
Returns: 
```
Warning: Unsuitable input detected. Please check the detected entities on your input and try again with the unsuitable input removed.
Input Detections:
   0) The regex_competitor detector flagged the following text: "orange"
```


## More information
- [TrustyAI Notes Repo](https://github.com/trustyai-explainability/reference/tree/main)
- [TrustyAI Github](https://github.com/trustyai-explainability)