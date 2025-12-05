import json
import re
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


def parse_generations_from_report_content(
    report_content: str,
    eval_threshold: float
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """Parse enhanced generations and score rows from report.jsonl content.
    
    Args:
        report_content: String content of report.jsonl file
        eval_threshold: Threshold for determining vulnerability (0-1 scale)
        
    Returns:
        Tuple of (generations, score_rows_by_probe)
        - generations: List of dicts with attempt details
        - score_rows_by_probe: Dict mapping probe_name → list of detector result dicts
    """
    generations = []
    score_rows_by_probe = {}
    
    for line in report_content.split("\n"):
        if not line.strip():
            continue
        
        try:
            entry = json.loads(line)
            
            # Only process completed attempts
            if entry.get("entry_type") == "attempt" and entry.get("status") == 2:
                probe_name = entry.get("probe_classname", "unknown")
                detector_results = entry.get("detector_results", {})
                outputs = entry.get("outputs", [])
                
                # Check if vulnerable based on any detector
                is_vulnerable = False
                for detector, scores in detector_results.items():
                    # Note: scores can be a list (multiple outputs per prompt)
                    scores_list = scores if isinstance(scores, list) else [scores]
                    if any(score >= eval_threshold for score in scores_list):
                        is_vulnerable = True
                        break
                
                # Build enhanced generation
                generation = {
                    "probe": probe_name,
                    "probe_category": probe_name.split('.')[0],
                    "goal": entry.get("goal", ""),
                    "vulnerable": is_vulnerable,
                    "prompt": entry.get("prompt", ""),
                    "responses": outputs,
                    "detector_results": detector_results,
                }
                generations.append(generation)
                
                # Collect score row for this attempt
                if probe_name not in score_rows_by_probe:
                    score_rows_by_probe[probe_name] = []
                
                score_rows_by_probe[probe_name].append(detector_results)
        
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON line in report: {e}")
            continue
        except Exception as e:
            logger.warning(f"Error parsing report line: {e}")
            continue
    
    return generations, score_rows_by_probe


def parse_aggregated_from_avid_content(avid_content: str) -> Dict[str, Dict[str, Any]]:
    """Parse probe-level aggregated info from AVID report content.
    
    Args:
        avid_content: String content of .avid.jsonl file (can be empty)
        
    Returns:
        Dict mapping probe_name → aggregated_results dict
    """
    if not avid_content:
        return {}
    
    aggregated_by_probe = {}
    
    for line in avid_content.split("\n"):
        if not line.strip():
            continue
        
        try:
            entry = json.loads(line)
            
            # Extract probe name from description
            desc = entry.get("problemtype", {}).get("description", {}).get("value", "")
            probe_match = re.search(r'probe `([^`]+)`', desc)
            probe_name = probe_match.group(1) if probe_match else "unknown"
            
            # Get metrics DataFrame
            metrics_list = entry.get("metrics", [])
            if not metrics_list:
                continue
            
            results = metrics_list[0].get("results", {})
            
            # Parse DataFrame columns to get summary statistics
            total_attempts = 0
            benign_responses = 0
            
            for idx_str in results.get("detector", {}).keys():
                passed = results["passed"][idx_str]
                total = results["total"][idx_str]
                
                total_attempts += total
                benign_responses += passed
            
            vulnerable_responses = total_attempts - benign_responses
            attack_success_rate = round((vulnerable_responses / total_attempts * 100), 2) if total_attempts > 0 else 0
            
            # Get AVID taxonomy
            impact = entry.get("impact", {}).get("avid", {})
            
            # Get model info
            artifacts = entry.get("affects", {}).get("artifacts", [])
            model_name = artifacts[0].get("name", "unknown") if artifacts else "unknown"
            deployer = entry.get("affects", {}).get("deployer", [])
            model_type = deployer[0] if deployer else "unknown"
            
            # Build aggregated results with clean hierarchy
            aggregated_by_probe[probe_name] = {
                # Core statistics (top level)
                "total_attempts": total_attempts,
                "benign_responses": benign_responses,
                "vulnerable_responses": vulnerable_responses,
                "attack_success_rate": attack_success_rate,
                
                # Metadata (grouped)
                "metadata": {
                    "avid_taxonomy": {
                        "risk_domain": impact.get("risk_domain", []),
                        "sep_view": impact.get("sep_view", []),
                        "lifecycle_view": impact.get("lifecycle_view", [])
                    },
                    "model": {
                        "type": model_type,
                        "name": model_name
                    }
                }
            }
        
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON line in AVID report: {e}")
            continue
        except Exception as e:
            logger.warning(f"Error parsing AVID line: {e}")
            continue
    
    return aggregated_by_probe


def calculate_detector_means(score_rows: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate per-detector mean scores from score rows.
    
    Args:
        score_rows: List of detector results per attempt
        
    Returns:
        Dict mapping detector_name_mean → average score (0-100 scale)
    """
    detector_sums = {}
    
    for row in score_rows:
        for detector, scores in row.items():
            scores_list = scores if isinstance(scores, list) else [scores]
            
            if detector not in detector_sums:
                detector_sums[detector] = []
            
            # For mean calculation, use max score from list if multiple outputs
            max_score = max(scores_list) if scores_list else 0
            detector_sums[detector].append(max_score)
    
    return {
        f"{detector}_mean": round((sum(scores) / len(scores)) * 100, 2)
        for detector, scores in detector_sums.items()
    }


def calculate_basic_aggregates(
    score_rows: List[Dict[str, Any]],
    eval_threshold: float
) -> Dict[str, Any]:
    """Calculate basic aggregates when AVID report not available.
    
    Args:
        score_rows: List of detector results per attempt
        eval_threshold: Threshold for determining vulnerability (0-1 scale)
        
    Returns:
        Basic aggregated statistics with same structure as AVID-enhanced results
    """
    total_attempts = len(score_rows)
    vulnerable_count = 0
    
    for row in score_rows:
        # Check if any detector flagged this attempt
        for detector, scores in row.items():
            scores_list = scores if isinstance(scores, list) else [scores]
            if any(score >= eval_threshold for score in scores_list):
                vulnerable_count += 1
                break  # Count attempt once if any detector flagged it
    
    detector_means = calculate_detector_means(score_rows)
    
    attack_success_rate = round((vulnerable_count / total_attempts * 100), 2) if total_attempts > 0 else 0
    
    return {
        # Core statistics
        "total_attempts": total_attempts,
        "benign_responses": total_attempts - vulnerable_count,
        "vulnerable_responses": vulnerable_count,
        "attack_success_rate": attack_success_rate,
        
        # Detector scores (grouped)
        "detector_scores": detector_means,
        
        # Metadata (minimal when AVID not available)
        "metadata": {}
    }


def combine_parsed_results(
    generations: List[Dict[str, Any]],
    score_rows_by_probe: Dict[str, List[Dict[str, Any]]],
    aggregated_by_probe: Dict[str, Dict[str, Any]],
    eval_threshold: float
) -> Dict[str, Any]:
    """Combine parsed data into final result structure.
    
    Args:
        generations: List of attempt details
        score_rows_by_probe: Dict mapping probe_name → score rows
        aggregated_by_probe: Dict mapping probe_name → aggregated stats (from AVID)
        eval_threshold: Threshold for vulnerability
        
    Returns:
        Dict with 'generations' and 'scores' keys
    """
    scores = {}
    
    for probe_name, score_rows in score_rows_by_probe.items():
        aggregated = aggregated_by_probe.get(probe_name, {})
        
        # If no AVID data, calculate basic stats from score_rows
        if not aggregated:
            aggregated = calculate_basic_aggregates(score_rows, eval_threshold)
        else:
            # AVID data exists - calculate detector_means from score_rows and add as nested dict
            detector_means = calculate_detector_means(score_rows)
            aggregated["detector_scores"] = detector_means
        
        scores[probe_name] = {
            "score_rows": score_rows,
            "aggregated_results": aggregated
        }
    
    return {
        "generations": generations,
        "scores": scores
    }

