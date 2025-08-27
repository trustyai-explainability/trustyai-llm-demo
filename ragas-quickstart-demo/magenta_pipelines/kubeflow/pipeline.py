from typing import List

from kfp import dsl, kubernetes

from .components import (
    run_ragas_evaluation,
)


@dsl.pipeline()
def ragas_evaluation_pipeline(
    model: str,
    input_dataset_uri: str,
    output_dataset_uri: str,
    sampling_params: dict,
    embedding_model: str,
    metrics: List[str],
    inference_url: str,
):
    # TODO: consider a step here to validate that:
    # dataset exists, has data,
    # the requested embeddding and llm are available

    ragas_task = run_ragas_evaluation(
        model=model,
        sampling_params=sampling_params,
        embedding_model=embedding_model,
        metrics=metrics,
        inference_url=inference_url,
        input_dataset_uri=input_dataset_uri,
        output_dataset_uri=output_dataset_uri,
    )

    # the ragas_task needs to retrieve and store the results to S3
    kubernetes.use_secret_as_env(
        ragas_task,
        secret_name="aws-credentials",
        secret_key_to_env={
            "AWS_ACCESS_KEY_ID": "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY": "AWS_SECRET_ACCESS_KEY",
            "AWS_DEFAULT_REGION": "AWS_DEFAULT_REGION",
        },
    )


# TODO: add a pipeline that processes each dataset in parallel
#     # Process each dataset in parallel
#     with dsl.ParallelFor(dataset_ids) as dataset_id:
#         # Prepare dataset
#         dataset_prep = retrieve_data_from_llama_stack(
#             dataset_config={"dataset_id": dataset_id},
#             llama_stack_base_url=llama_stack_base_url,
#             num_examples=num_examples,
#         )
#         dataset_prep.set_display_name(f"Prepare Dataset {dataset_id}")

#         # Run evaluation
#         evaluation = run_ragas_evaluation(
#             input_dataset=dataset_prep.outputs["output_dataset"],
#             model_config=model_setup.outputs["output_config"],
#             evaluation_config={
#                 "metric_names": metric_names,
#                 "max_workers": max_workers,
#                 "timeout": 600,
#             },
#         )
#         evaluation.set_display_name(f"Evaluate {dataset_id}")
