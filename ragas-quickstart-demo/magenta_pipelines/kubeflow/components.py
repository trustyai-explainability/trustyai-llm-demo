import os
from typing import List, Optional

from dotenv import load_dotenv
from kfp import dsl

load_dotenv()


@dsl.component(base_image=os.environ["KUBEFLOW_BASE_IMAGE"])
def retrieve_data_from_llama_stack(
    dataset_id: str,
    llama_stack_base_url: str,
    output_dataset: dsl.Output[dsl.Dataset],
    num_examples: int = -1,  # TODO: parse this
):
    import pandas as pd
    from llama_stack_client import LlamaStackClient

    client = LlamaStackClient(base_url=llama_stack_base_url)
    dataset = client.datasets.retrieve(dataset_id=dataset_id)
    df = pd.DataFrame(dataset.source.rows)
    df.to_json(output_dataset.path, orient="records", lines=True)


@dsl.component(base_image=os.environ["KUBEFLOW_BASE_IMAGE"])
def run_ragas_evaluation(
    model: str,
    sampling_params: dict,
    embedding_model: str,
    metrics: List[str],
    inference_url: str,
    input_dataset: Optional[dsl.Input[dsl.Dataset]] = None,
    input_dataset_uri: Optional[str] = None,
    output_dataset_uri: Optional[str] = None,
):
    import logging

    import pandas as pd
    from langchain_ollama import OllamaEmbeddings, OllamaLLM
    from ragas import EvaluationDataset, evaluate
    from ragas.dataset_schema import EvaluationResult
    from ragas.embeddings.base import LangchainEmbeddingsWrapper
    from ragas.llms.base import LangchainLLMWrapper
    from ragas.run_config import RunConfig

    from magenta_pipelines.constants import METRIC_MAPPING
    from magenta_pipelines.logging_utils import render_dataframe_as_table

    logger = logging.getLogger(__name__)

    llm = LangchainLLMWrapper(
        OllamaLLM(
            model=model,
            base_url=inference_url,
            # TODO: add sampling params
        )
    )
    embeddings = LangchainEmbeddingsWrapper(
        OllamaEmbeddings(
            model=embedding_model,
            base_url=inference_url,
        )
    )

    metrics = [METRIC_MAPPING[m] for m in metrics]
    run_config = RunConfig(max_workers=1)

    if input_dataset is not None:
        with open(input_dataset.path) as f:
            df_input = pd.read_json(f, lines=True)
    elif input_dataset_uri is not None:
        df_input = pd.read_json(input_dataset_uri, lines=True)
    else:
        raise ValueError("Either input_dataset or input_dataset_uri must be provided")

    eval_dataset = EvaluationDataset.from_list(df_input.to_dict(orient="records"))

    ragas_output: EvaluationResult = evaluate(
        dataset=eval_dataset,
        metrics=metrics,
        llm=llm,
        embeddings=embeddings,
        run_config=run_config,
    )

    df_output = ragas_output.to_pandas()
    table_output = render_dataframe_as_table(df_output, "Ragas Evaluation Results")
    logger.info(f"Ragas evaluation completed:\n{table_output}")

    df_output.to_json(output_dataset_uri, orient="records", lines=True)
