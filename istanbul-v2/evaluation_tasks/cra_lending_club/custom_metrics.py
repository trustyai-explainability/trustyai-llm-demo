"""
Custom metrics for FinanceBench binary classification task
"""

def argmax(array, idx=None):
    """Implement argmax to avoid importing numpy"""
    max = None
    max_idx = -1
    for i, tup in enumerate(array):
        val = tup[idx] if idx is not None else tup
        if max is None or val > max:
            max = val
            max_idx = i
    return max_idx

def evaluate(doc, loglikelihoods):
    result = {"false_positive": 0, "true_positive": 0, "true_negative": 0, "false_negative": 0, "acc": 0}
    model_answer = argmax(loglikelihoods, 0)
    if doc['answer'] == "good" and model_answer == 0:
        result['true_positive'] = 1
        result['acc'] = 1
    elif doc['answer'] == "good" and model_answer == 1:
        result['false_positive'] = 1
    elif doc['answer'] == "bad" and model_answer == 0:
        result['false_negative'] = 1
    else:
        result['true_negative'] = 1
        result['acc'] = 1
    return result

def count(x):
    """For whatever reason, lm-eval-harness does not provide a sum aggregation, so define one here"""
    return sum(x)