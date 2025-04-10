# 🍋 TrustyAI Lemonade Stand Demo  🍋
In this example, we'll imagine we run a successful lemonade stand and want to deploy a customer service
agent so our customers can learn more about our products. We'll want to make sure all conversations with
the agent are family friendly, and that it does not promote our rival fruit juice vendors. 

## 1. Install RHOAI and all prerequisite operators for a GPU model deployment
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
This will use IBM's [Granite-Guadrian-HAP-38m](https://huggingface.co/ibm-granite/granite-guardian-hap-38m) model, which is a small
language model for detecting problematic speech.
```bash
oc apply -f guardrails/hap_detector/hap_model_container.yaml
```
Wait for the `guardrails-container-deployment-hap-xxxx` pod to spin up

```bash
oc apply -f guardrails/hap_detector/hap_serving_runtime.yaml
oc apply -f guardrails/hap_detector/hap_isvc.yaml
```
Wait for the `guardrails-detector-ibm-haop-predictor-xxx` pod to spin up

### 4.2 Configure our regex detector
To filter out converstations about our rival juice vendors, we'll use the following regex pattern:
```regexp
\b(?i:apple|cranberry|grape|orange|pineapple|)\b
```
This will flag anything that matches that regex pattern as a detection- in this case, any mention of the words `apple`, `cranberry`, `grape`, `orange`, or `pineapple` regardless of case. To configure this, we'll put that pattern into our [configmap_vllm_gateway.yaml](guardrails/configmap_vllm_gateway.yaml), line 19:
```yaml
regex:    
  - \b(?i:orange|apple|cranberry|pineapple|grape)\b
```

Once configured, we will deploy the configmap:
```bash
oc apply -fguardrails/configmap_vllm_gateway.yaml
```

### 4.3 Configure the Guardrails orchestrator
In 'guardrails/configmap_orchestrator.yaml', set the following values:
- `chat_generation.service.hostname`: Set this to the name of your Phi-e predictor service. On my cluster, that's 
`phi3-predictor.model-namespace.svc.cluster.local`
- `detectors.hap.service.hostname`: Set this to the name of your HAP predictor service. On my cluster, that's `guardrails-detector-ibm-hap-predictor.model-namespace.svc.cluster.local`

Then apply the configs:
```bash
oc apply -f guardrails/configmap_auxiliary_images.yaml
oc apply -f guardrails/configmap_orchestrator.yaml

```

Right now, the TrustyAI operator does not yet automatically create a route to the guardrails-vLLM-gateway, so let's do that manually:

```bash
oc apply -f guardrails/gateway_route.yaml
```

### 4.4 Deploy the Orchestrator
```bash
oc apply -f guardrails/orchestrator_cr.yaml
```

### 4.5 Check the Orchestrator Health
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

## 5 Have a play around with Guardrails!
First, set up:
```bash
GUARDRAILS_GATEWAY=https://$(oc get routes guardrails-gateway -o jsonpath='{.spec.host}')
RAW_MODEL=http://localhost:8080
```

The available endpoints are:

- `$GUARDRAILS_GATEWAY/passthrough`: query the raw, unguardrailed model. 
- `$GUARDRAILS_GATEWAY/hap`: query using with the HAP detector.
- `$GUARDRAILS_GATEWAY/all`: query with all available detectors, so the HAP and competitor-check detectors. 


Some cool queries to try:
## "Is orange juice good?"
### Raw Model:
```bash
python3 prompt.py 
  --url $RAW_MODEL/v1/chat/completions
   --model phi3 
   --message "Is orange juice good?"
```
Returns: 
```
Orange juice is generally considered good, especially when it's freshly squeezed. It's a rich source of vitamin C, which is essential for a healthy immune system. It also contains other nutrients like potassium, folate, and antioxidants. However, the quality of orange juice can vary depending on the brand and whether it's freshly squeezed or from concentrate. It's always best to check the label for added sugars and preservatives.
```

### Guardrails, `/passthrough` endpoint:
```bash
python3 prompt.py 
  --url $GUARDRALS_GATEWAY/all/v1/chat/completions
   --model phi3 
   --message "Is orange juice good?"
```
Returns: 
```
Orange juice is generally considered good, especially when it's freshly squeezed. It's a rich source of vitamin C, which is essential for a healthy immune system. It also contains other nutrients like potassium, folate, and antioxidants. However, the quality of orange juice can vary depending on the brand and whether it's freshly squeezed or from concentrate. It's always best to check the label for added sugars and preservatives.
```

### Guardrails, `/all` endpoint:
```bash
python3 prompt.py 
  --url $GUARDRALS_GATEWAY/all/v1/chat/completions
   --model phi3 
   --message "Is orange juice good?"
```
Returns: 
```
Warning: Unsuitable input detected. Please check the detected entities on your input and try again with the unsuitable input removed.
Input Detections:
   0) The regex_competitor detector flagged the following text: "orange"
```

## "Lemonade is disgusting"
### Raw Model:
```bash
python3 prompt.py 
  --url $RAW_MODEL/v1/chat/completions
   --model phi3 
   --message "Lemonade is disgusting"
```
Returns: 
```
As an AI, I don't have personal opinions or taste preferences. However, I understand that taste is subjective, and what one person finds disgusting, another may find delicious. It's important to respect individual tastes and preferences.
```

### Guardrails, `/all` endpoint:
```bash
python3 prompt.py 
  --url $GUARDRALS_GATEWAY/all/v1/chat/completions
   --model phi3 
   --message "Lemonade is disgusting"
```
Returns: 
```
Warning: Unsuitable input detected. Please check the detected entities on your input and try again with the unsuitable input removed.
Input Detections:
   0) The hap detector flagged the following text: "Lemonade is disgusting, don't you agree?"
```

## "Can you list some healthy fruit juices?"
### Raw Model:
```bash
python3 prompt.py 
  --url $RAW_MODEL/v1/chat/completions
   --model phi3 
   --message "Can you list some healthy fruit juices?"
```
Returns: 
```
Certainly! Here are some healthy fruit juices that are rich in vitamins and antioxidants:


1. **Apple Juice**: Made from apples, it's a good source of vitamin C and antioxidants.

2. **Orange Juice**: High in vitamin C and folate, it's a popular choice for a refreshing drink.

3. **Pineapple Juice**: Contains bromelain, an enzyme that can aid digestion.

4. **Grape Juice**: Rich in antioxidants and vitamin C, especially when made from whole grapes.

5. **Cranberry Juice**: Known for its potential to support urinary tract health.

6. **Tomato Juice**: High in lycopene, an antioxidant that may reduce the risk of heart disease and cancer.

7. **Watermelon Juice**: A hydrating choice that's high in vitamins A and C.

8. **Cantal
```

### Guardrails, `/all` endpoint:
```bash
python3 prompt.py 
  --url $GUARDRALS_GATEWAY/all/v1/chat/completions
   --model phi3 
   --message "Can you list some healthy fruit juices?"
```
Returns: 
```
Warning: Unsuitable output detected.
Output Detections:
   0) The regex_competitor detector flagged the following text: "Apple"
   1) The regex_competitor detector flagged the following text: "Orange"
   2) The regex_competitor detector flagged the following text: "Pineapple"
   3) The regex_competitor detector flagged the following text: "Grape"
   4) The regex_competitor detector flagged the following text: "Cranberry"
```

## More information
- [TrustyAI Notes Repo](https://github.com/trustyai-explainability/reference/tree/main)
- [TrustyAI Github](https://github.com/trustyai-explainability)