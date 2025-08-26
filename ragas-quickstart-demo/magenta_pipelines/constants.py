from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

METRIC_MAPPING = {
    metric_func.name: metric_func
    for metric_func in [
        answer_relevancy,
        context_precision,
        faithfulness,
        context_recall,
        # TODO: add these later
        # "answer_correctness": AnswerCorrectness(),
        # "factual_correctness": FactualCorrectness(),
        # "summarization_score": SummarizationScore(),
        # "bleu_score": BleuScore(),
        # "rouge_score": RougeScore(),
    ]
}
