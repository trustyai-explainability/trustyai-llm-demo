# TrustyAI Evaluation Quickstart
* Runtime: ~15 minutes
* Difficulty: Easy

TrustyAI's LM-Eval framework brings popular open-source evaluation toolkits to OpenShift AI. Currently,
we support the [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness/tree/main) with
more toolkits on the way soon!

In this example, we'll deploy a Phi3 model and run an Arc-Easy evaluation against it.
[Arc](https://huggingface.co/datasets/allenai/ai2_arc) is an immensely popular evaluation that measures a model against a number of grade-school level, multiple-choice science questions.

---
## 1. Install RHOAI and all prerequisite operators for a GPU model deployment
You'll need to [set up your cluster for a GPU deployment.](https://github.com/trustyai-explainability/reference/tree/main/llm-deployment/vllm#install-the-gpu-operators)

---

## 2. Deploy RHOAI
The default data science cluster should work for this demo, or use the one provided here:

`oc apply -f dsc.yaml`

*Note: this demo was tested on RHOAI 2.19.2, but any version after **2.16.1** _should_ work*

---

## 3. Configure TrustyAI to allow downloading remote datasets from Huggingface
By default, TrustyAI prevents evaluation jobs from accessing the internet or running downloaded code.
A typical evaluation job will download two items from Huggingface:
1) The dataset of the evaluation task, and any dataset processing code
2) The tokenizer of your model

If you trust the source of your dataset and tokenizer, you can override TrustyAI's default setting.
In our case, we'll be downloading:
1) [allenai/ai2_arc](https://huggingface.co/datasets/allenai/ai2_arc)
2) [Phi-3-mini-4k-instruct's tokenizer](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct)

If you are happy for TrustyAI to automatically download those two resources, run:
```bash
oc patch configmap trustyai-service-operator-config -n redhat-ods-applications  \
--type merge -p '{"metadata": {"annotations": {"opendatahub.io/managed": "false"}}}'
oc patch configmap trustyai-service-operator-config -n redhat-ods-applications \
--type merge -p '{"data":{"lmes-allow-online":"true","lmes-allow-code-execution":"true"}}'
oc rollout restart deployment trustyai-service-operator-controller-manager -n redhat-ods-applications
```
Wait for your `trustyai-service-operator-controller-manager` pod in the `redhat-ods-applications` namespace
to restart, and then TrustyAI should be ready to go.


---
## 4. Deploy Phi3 Model
```bash
oc new-project model-namespace || oc project model-namespace
oc apply -f model_storage_container.yaml
```
The model container can take a while to spin up- it's downloading a [Phi-3-mini](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct)
from Huggingface and saving it into an emulated AWS data connection.

```bash
oc apply -f phi3.yaml
```
Wait for the model pod to spin up, should look something like `phi3-predictor-XXXXXX`

You can test the model by sending some inferences to it:

#### ❗NOTE: Run the following command in a *new terminal tab* 
```bash
oc port-forward $(oc get pods -o name | grep phi3) 8080:8080
```

#### Now return to your original terminal:
```bash
python3 ../common/prompt.py --url http://localhost:8080/v1/chat/completions --model phi3 --message "Hi, can you tell me about yourself?"
````

#### ❗NOTE: [`../common/prompt.py`](../common/prompt.py)is a Python script included in this repository for sending chat/completions requests to your deployed model. To run `prompt.py`, make sure the requests library is installed: `pip install requests`

---
## 5. Run the evaluation
To start an evaluation, apply an `LMEvalJob` custom resource:
```bash
oc apply -f mmlu_job.yaml
```

Check out [mmlujob.yaml](evaluation_job.yaml) to learn more about the `LMEvalJob` specification.

*Note: the evaluation job container image is quite large, so the first evaluation job you run on your cluster might take a while to start up*

If everything has worked, you should see a pod called `arc-easy-eval-job` running in your namespace. 
You can watch the progress of your evaluation job by running:

```bash
oc logs -f arc-easy-eval-job
```

---
## 6. Check out the results
After the evaluation finishes (it took about 8.5 minutes on my cluster), you can take a look at the results. These are stored in the `status.results` field of the LMEvalJob resource:

```bash
oc get LMEvalJob arc-easy-eval-job -o template --template '{{.status.results}}' | jq  .results
```
returns:
```json
{
  "arc_easy": {
    "alias": "arc_easy",
    "acc,none": 0.8186026936026936,
    "acc_stderr,none": 0.007907153952801706,
    "acc_norm,none": 0.7836700336700336,
    "acc_norm_stderr,none": 0.00844876352205705
  }
}
```

Now you're free to play around with evaluations! You can see the full list of evaluation supported by 
lm-evaluation-harness [here.](https://github.com/red-hat-data-services/lm-evaluation-harness/blob/main/lm_eval/tasks/README.md)
## More information
- [TrustyAI Notes Repo](https://github.com/trustyai-explainability/reference/tree/main)
- [TrustyAI Github](https://github.com/trustyai-explainability)
