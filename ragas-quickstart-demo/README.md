# Ragas Quickstart Demo

This demo shows how to run Ragas evaluation on Kubeflow Pipelines.

## Setup

- Setup your RHOAI cluster with Data Science Pipelines enabled.
- Install the demo environment:
    ```bash
    uv venv
    uv sync
    ```

- Create a `.env` file with the following:
    - `INFERENCE_URL`
        - This is the url of the inference server that Ragas will use to run the evaluation (LLM generations and embeddings, etc.). If you are an inference server locally (eg., Llama Stack or Ollama), you can use [ngrok](https://ngrok.com/) to expose it.
    - `KUBEFLOW_PIPELINES_ENDPOINT`
        - You can get this via `kubectl get routes -A | grep -i pipeline` on your Kubernetes cluster.
    - `KUBEFLOW_NAMESPACE`
        - This is the name of the data science project where the Kubeflow Pipelines server is running.
    - `KUBEFLOW_BASE_IMAGE`
        - This is the image used to run the Ragas evaluation in Kubeflow. See `Containerfile` for details. There is a public version of this image at `quay.io/diegosquayorg/magenta-kfp-pipelines:latest`.
