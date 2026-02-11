"""
Custom metrics for FinanceBench binary classification task
"""


def confusion_matrix_metrics(items):
    """
    Compute confusion matrix components for binary classification

    Args:
        items: List of (prediction, reference) tuples

    Returns:
        dict: Confusion matrix components (TP, TN, FP, FN)
    """
    tp = fp = tn = fn = 0

    for pred, ref in items:
        # Normalize predictions and references
        pred_val = 1 if pred == 1 or pred == "good" or pred == 1.0 else 0
        ref_val = 1 if ref == 1 or ref == "good" or ref == 1.0 else 0

        if pred_val == 1 and ref_val == 1:
            tp += 1
        elif pred_val == 0 and ref_val == 0:
            tn += 1
        elif pred_val == 1 and ref_val == 0:
            fp += 1
        elif pred_val == 0 and ref_val == 1:
            fn += 1

    return {
        'tp': tp,
        'tn': tn,
        'fp': fp,
        'fn': fn,
        'total': len(items)
    }


def true_positives(items):
    """Count true positives"""
    result = confusion_matrix_metrics(items)
    return result['tp']


def true_negatives(items):
    """Count true negatives"""
    result = confusion_matrix_metrics(items)
    return result['tn']


def false_positives(items):
    """Count false positives"""
    result = confusion_matrix_metrics(items)
    return result['fp']


def false_negatives(items):
    """Count false negatives"""
    result = confusion_matrix_metrics(items)
    return result['fn']

def count(x):
    """For whatever reason, lm-eval-harness does not provide a sum aggregation, so define one here"""
    return sum(x)