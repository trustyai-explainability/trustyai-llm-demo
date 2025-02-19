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
The model container can take a while to spin up- it's downloading a [Qwen2](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct)
from Huggingface and saving it into an emulated AWS data connection.

```bash
oc apply -f vllm/serving_runtime.yaml
oc apply -f vllm/isvc_qwen2
```
Wait for the model pod to spin up, should look something like `qwen2-predictor-XXXXXX`

You can test the model by sending some inferences to it:

```bash
oc port-forward $(oc get pods -o name | grep qwen2) 8080:8080
```

Then, in a new terminal tab:
```bash
./curl_model 127.0.0.1:8080 "Hi, can you tell me about yourself?"
````

## 4. LM-Eval
```bash
oc apply -f lm-eval/lm-eval-job.yaml
```
This will download [the Arc dataset](https://huggingface.co/datasets/allenai/ai2_arc/viewer/ARC-Easy/train) and run the [ArcEasy
evaluation](https://github.com/opendatahub-io/lm-evaluation-harness/tree/main/lm_eval/tasks/arc).

You should see an `evaljob` pod spin up in your cluster. This eval job should take ~5 minutes to run. 
Afterwards, you can navigate to the lmevaljob resource (Home -> Search -> Search for "LMEvalJob" -> Click evaljob)-
inside the lmevaljob's YAML you will see the results of the evaluation, e.g.:
```json
      "results": {
        "arc_easy": {
          "alias": "arc_easy",
          "acc,none": 0.6561447811447811,
          "acc_stderr,none": 0.009746660584852454,
          "acc_norm,none": 0.5925925925925926,
          "acc_norm_stderr,none": 0.010082326627832872
        }
```


## 5. Guardrails
### 5.1 Deploy the Hateful And Profane (HAP) language detector
```bash
oc apply -f guardrails/hap_detector/hap_model_container.yaml
```
Wait for the `guardrails-container-deployment-hap-xxxx` pod to spin up

```bash
oc apply -f guardrails/hap_detector/hap_serving_runtime.yaml
oc apply -f guardrails/hap_detector/hap_isvc.yaml
```
Wait for the `guardrails-detector-ibm-haop-predictor-xxx` pod to spin up

### 5.2 Configure the Guardrails orchestrator
In 'gaurdrails/configmap_orchestrator.yaml', set the following values:
- `chat_generation.service.hostname`: Set this to the name of your Qwen2 predictor service. On my cluster, that's 
`qwen2-predictor.model-namespace.svc.cluster.local`
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
ORCH_GATEWAY=https://$(oc get routes guardrails-gateway -o jsonpath='{.spec.host}')
```

The available endpoints are:

- `$ORCH_GATEWAY/passthrough`: query the raw, unguardrailed model. 
- `$ORCH_GATEWAY/language_quality`: query with filters for personally identifiable information and HAP
- `$ORCH_GATEWAY/all`: query with all available filters, so the language filters plus a check against competitor names. 


Some cool queries to try:
```
./curl_model $ORCH_GATEWAY/passthrough "Write three paragraphs about morons"

./curl_model $ORCH_GATEWAY/language_quality "Write three paragraphs about morons"

./curl_model $ORCH_GATEWAY/language_quality "My email address is abc@def.com"

./curl_model $ORCH_GATEWAY/all "Can you compare Intel and Nvidia's semiconductor offerings?"

./curl_model $ORCH_GATEWAY/language_quality "Can you compare Intel and Nvidia's semiconductor offerings?"

```



## More information
- [TrustyAI Notes Repo](https://github.com/trustyai-explainability/reference/tree/main)
- [TrustyAI Github](https://github.com/trustyai-explainability)