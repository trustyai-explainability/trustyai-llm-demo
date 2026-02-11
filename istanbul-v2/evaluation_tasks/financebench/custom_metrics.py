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


def precision_score(items):
    """Compute precision: TP / (TP + FP)"""
    result = confusion_matrix_metrics(items)
    tp = result['tp']
    fp = result['fp']
    return tp / (tp + fp) if (tp + fp) > 0 else 0.0


def recall_score(items):
    """Compute recall: TP / (TP + FN)"""
    result = confusion_matrix_metrics(items)
    tp = result['tp']
    fn = result['fn']
    return tp / (tp + fn) if (tp + fn) > 0 else 0.0


def f1_score(items):
    """Compute F1 score: 2 * (precision * recall) / (precision + recall)"""
    prec = precision_score(items)
    rec = recall_score(items)
    return 2 * (prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0


def specificity_score(items):
    """Compute specificity (true negative rate): TN / (TN + FP)"""
    result = confusion_matrix_metrics(items)
    tn = result['tn']
    fp = result['fp']
    return tn / (tn + fp) if (tn + fp) > 0 else 0.0
