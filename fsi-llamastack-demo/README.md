# TrustyAI Llama-Stack Financial Services Demo
This demo shows all of TrustyAI's current Llama Stack features:
1) LM-Eval-Harness
2) NVIDIA Garak
3) NVIDIA NeMo-Guardrails
4) Ragas

We'll use all four of these tools in a financial services use-case, walking through initial capability
assessment, risk analysis, risk mitigation, and continuous RAG evaluations. Everything runs self-hosted in OpenShift AI.

## Viewing the Demo
1) If you'd just like to see the visual material for the demo, you can view the accompanying presentation in your browser: 
   
   > [Presentation](https://rawcdn.githack.com/trustyai-explainability/trustyai-llm-demo/8bd6f7bc82904b62e3ed42a86712fc424dc596d5/fsi-llamastack-demo/notebooks/fsi_safety_demo_presentation.html) 

   This will let you see the workflow and visualizations without needing to run or set anything up.
2) You can view the [pre-computed notebook here.](notebooks/fsi_safety_demo_notebook.ipynb)
3) If you'd like to replicate the demo in your own environment, follow the steps below.

## Pre-requisites
An OpenShift cluster with 2 GPU nodes:
1) 1 node needs at least 4 GPUs, I'd recommend a `g5.12xlarge` AWS node
2) 1 node needs a single GPU, e.g., a `g4dn.2xlarge` AWS node.

## Setup
1) Install RHOAI as described in [../docs/installing_rhoai.md](../docs/installing_rhoai.md). In the 
DataScienceCluster, make sure that:
    1) TrustyAI is set to `Removed`
   2) DataSciencePipelines is set to `Managed`
   3) The llama-stack-operator is set to `Managed`
2) This demo uses a combination of existing and preview TrustyAI 
features, so we'll install a custom deployment of the TrustyAI operator:
    ```shell
    oc apply -f deployment/trustyai_bundle.yaml -n redhat-ods-applications`
    ```
3. Start our Kubeflow Pipeline server, create the required service accounts, and download the necessary model artifacts:
    ```shell
    oc new-project model-namespace || oc project model-namespace || true
    oc apply -f deployment/kfp.yaml -n model-namespace
    oc apply -f deployment/serviceaccount.yaml -n model-namespace
    oc apply -f deployment/model_storage_container.yaml -n model-namespace
    echo "Waiting for model and dataset downloads to finish..."
    oc wait --for=condition=Available deployment/model-s3-storage-emulator --timeout=600s
    ```
4. Deploy the models. We'll be using a [Qwen/Qwen3-30B-Instruct](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507) model for inference and a [Qwen/Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) for embedding:
    ```shell
    oc apply -f deployment/models/qwen3-30.yaml -n model-namespace
    sleep 5 # wait for Qwen3-30b model to schedule
    oc apply -f deployment/models/embedding_model.yaml -n model-namespace
    echo "Waiting for model deployment readiness..."
    oc wait --for=condition=Available deployment/qwen3-predictor --timeout=600s
    oc wait --for=condition=Available deployment/embedding-predictor --timeout=600s
    ```
5. Deploy Llama stack:
    ```shell
    oc create configmap llama-stack-config --from-file=deployment/llama_stack/run.yaml -n model-namespace
    oc apply -f deployment/llama_stack/lls_distro.yaml
    ```

## Running the Demo
Refer to the demo notebook: [notebooks/fsi_safety_demo_notebook.ipynb](notebooks/fsi_safety_demo_notebook.ipynb).