import io
import json
import time
import uuid

import matplotlib.pyplot as plt
import pandas as pd

from datetime import datetime
from IPython.display import display, HTML
import pickle as pkl


def save_or_load(scope, var_name, force_cache_load=False):
    import os
    local_var = scope.get(var_name)
    cache_path = os.path.join("cached_results", f"{var_name}.pkl")
    if local_var is None or force_cache_load:
        print(f"🔄 Loading {var_name} from cache")

        if os.path.exists(cache_path):
            with open(cache_path, "rb") as f:
                return pkl.load(f)
        else:
            raise FileNotFoundError(cache_path)
    else:
        print(f"💾 Caching {var_name} to {cache_path}")
        with open(cache_path, "wb") as f:
            pkl.dump(local_var, f)
        return local_var



def monitor_job_status(client, evaluation_dict=None, benchmark_id=None, job=None):
    loop_idx = 0
    start_t = time.time()

    if evaluation_dict:
        benchmark_id = evaluation_dict["benchmark_id"]
        job = evaluation_dict["job"]

    while True:
        if loop_idx % 20 == 0:
            job = client.alpha.eval.jobs.status(job_id=job.job_id, benchmark_id=benchmark_id)
        if job.status == 'failed':
            print(f"\r❌ {benchmark_id} job {job.job_id} failed"+" "*50)
            break
        elif job.status == 'completed':
            results = client.alpha.eval.jobs.retrieve(job_id=job.job_id, benchmark_id=benchmark_id)
            if getattr(job, "metadata", None):
                delta_t = datetime.fromisoformat(job.metadata["finished_at"]) - datetime.fromisoformat(
                    job.metadata["created_at"])
                delta_t_string = " ".join([item+"hms"[i] for i, item in enumerate(f"{delta_t!s}".split(":")) if int(item)!=0])
                print(f"\n✅ {benchmark_id} job {job.job_id} finished in {delta_t_string}!"+" "*50)
            else:
                delta_t = int(time.time() - start_t)
                minutes = delta_t // 60
                seconds = delta_t % 60
                print(f"\n✅ {benchmark_id} job {job.job_id} finished in {minutes}m {seconds}s!" + " " * 50)
            if evaluation_dict:
                 evaluation_dict['results'] = results
            else:
                return results
            break
        else:
            emoji = "🕛🕐🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚"[loop_idx %12]
            print(f"\r️{emoji*3} {benchmark_id} job {job.job_id} running...", end="")
        loop_idx += 1
        time.sleep(.25)

## LM EVAL ================================================
def  display_eval_results(model_name, evaluation):
    benchmark_id = evaluation["benchmark_id"]
    benchmark_name = evaluation["label"]
    eval_response = evaluation["results"]

    """One-stop visualization of evaluation results"""
    # Parse results
    scores = eval_response.scores
    results = []

    for key, scoring_result in scores.items():
        if ':acc' in key and 'stderr' not in key and 'norm' not in key:
            subject = key.replace(benchmark_id.split("::")[1], benchmark_name)
            if subject == benchmark_id.split("::")[1]:
                subject += ": Overall"



            acc = scoring_result.aggregated_results.get('acc', 0)

            # Get corresponding stderr
            stderr_key = key.replace(':acc', ':acc_stderr')
            stderr = scores.get(stderr_key, {}).aggregated_results.get('acc_stderr', 0) if stderr_key in scores else 0

            results.append({
                'Subject': subject,
                'Accuracy': acc,
                'Std Error': stderr
            })

    df = pd.DataFrame(results).sort_values('Accuracy', ascending=False)

    # Print summary
    print(f"\n{'=' * 70}")
    print(f"  {benchmark_name.upper()} RESULTS")
    print(f"{'=' * 70}")
    print(f"  Model: {model_name}")
    print(f"  Accuracy: {df['Accuracy'].mean() * 100:.2f}%")
    print(f"{'=' * 70}\n")


def compare_mmlu_evaluation_runs(client, evaluations: dict, benchmark_name="Benchmark"):
    """
    Compare multiple evaluation runs side-by-side

    Args:
        client: Llama Stack client
        evaluations: Dict of {"label": label: "job": job, "benchmark_id": benchmark_id} for each evaluation run
                    Example: {"English": job1, "Turkish": job2}
        benchmark_name: Name of the benchmark for display

    Returns:
        dict: Dictionary of {label: dataframe} for each run, plus 'comparison' dataframe
    """

    if len(evaluations) != 2:
        raise ValueError("Currently only supports comparing exactly 2 evaluation runs")

    labels = [evaluation["label"].title() for evaluation in evaluations]
    first_label, second_label = labels[0], labels[1]

    # Get results from both jobs
    dataframes = {}

    for evaluation in evaluations:
        benchmark_id = evaluation["benchmark_id"]
        response = client.alpha.eval.jobs.retrieve(job_id=evaluation["job"].job_id, benchmark_id=benchmark_id)
        results = []

        for key, scoring_result in response.scores.items():
            if ':acc' in key and 'stderr' not in key and 'norm' not in key:
                # Extract subject name
                subject_original = key.split(':')[0]

                subject_normalized = subject_original;
                for content in ["global_mmlu_full_", "_turkish", "_english", "tr", "en"]:
                    subject_normalized = subject_normalized.replace(content, "")
                subject_normalized = subject_normalized.replace('_', ' ').strip()
                subject_normalized = subject_normalized.title() if subject_normalized!="global mmlu finance" else "Overall Score"

                acc = scoring_result.aggregated_results.get('acc', 0)
                stderr_key = key.replace(':acc', ':acc_stderr')
                stderr = response.scores.get(stderr_key, {}).aggregated_results.get('acc_stderr', 0) if stderr_key in response.scores else 0

                results.append({
                    'Subject': subject_normalized,
                    'Subject_Original': subject_original,
                    'Accuracy': acc,
                    'Std Error': stderr
                })

        dataframes[evaluation["label"].title()] = pd.DataFrame(results)


    # Merge for comparison
    comparison_df = dataframes[first_label].merge(
        dataframes[second_label],
        on='Subject',
        suffixes=(f'_{first_label}', f'_{second_label}')
    )

    # Calculate delta
    comparison_df['Delta'] = comparison_df[f'Accuracy_{second_label}'] - comparison_df[f'Accuracy_{first_label}']
    comparison_df['Delta_pct'] = (comparison_df['Delta'] / comparison_df[f'Accuracy_{first_label}']) * 100

    # Display comparison table
    display_df = comparison_df.copy()
    display_df[f'{first_label} (%)'] = (display_df[f'Accuracy_{first_label}'] * 100).round(2)
    display_df[f'{second_label} (%)'] = (display_df[f'Accuracy_{second_label}'] * 100).round(2)
    display_df['Δ (pp)'] = (display_df['Delta'] * 100).round(2)

    display_html = display_df[['Subject', f'{first_label} (%)', f'{second_label} (%)', 'Δ (pp)']].to_html(index=False)

    # Create single figure with 2 rows: top row has side-by-side comparison, bottom row has delta
    fig = plt.figure(figsize=(16, 9), dpi=250)
    axes_label_size = 14
    gs = fig.add_gridspec(2, 2, height_ratios=[1, 1], hspace=0.4, wspace=0.07 )

    ax1 = fig.add_subplot(gs[0, 0])
    ax2 = fig.add_subplot(gs[0, 1])
    ax3 = fig.add_subplot(gs[1, :])  # Delta chart spans both columns

    # First run chart
    colors_first = ['#51cf66' if acc >= 0.7 else '#ffd43b' if acc >= 0.5 else '#ff6b6b'
                    for acc in comparison_df[f'Accuracy_{first_label}'].values]

    ax1.barh(comparison_df['Subject'], comparison_df[f'Accuracy_{first_label}'] * 100,
             xerr=comparison_df[f'Std Error_{first_label}'] * 100,
             color=colors_first, alpha=0.7, edgecolor='black', capsize=5)
    ax1.set_title(f'{first_label}', fontsize=14, fontweight='bold')
    ax1.set_xlim(0, 100)
    ax1.grid(axis='x', alpha=0.3)
    ax1.set_xticklabels([f"{i}%" for i in range(0, 101, 20)])
    ax1.tick_params(axis='both', labelsize=axes_label_size)

    # Second run chart
    colors_second = ['#51cf66' if acc >= 0.7 else '#ffd43b' if acc >= 0.5 else '#ff6b6b'
                     for acc in comparison_df[f'Accuracy_{second_label}'].values]

    ax2.barh(comparison_df['Subject'], comparison_df[f'Accuracy_{second_label}'] * 100,
             xerr=comparison_df[f'Std Error_{second_label}'] * 100,
             color=colors_second, alpha=0.7, edgecolor='black', capsize=5)
    ax2.set_title(f'{second_label}', fontsize=14, fontweight='bold')
    ax2.set_xlim(0, 100)
    ax2.grid(axis='x', alpha=0.3)
    ax2.tick_params(axis='both', labelsize=axes_label_size)
    ax2.set_xticklabels([f"{i}%" for i in range(0, 101, 20)])
    ax2.set_yticklabels([])  # Hide y-axis labels on right chart

    # Delta chart
    delta_colors = ['#51cf66' if d >= 0 else '#ff6b6b' for d in comparison_df['Delta'].values]

    ax3.barh(comparison_df["Subject"], comparison_df['Delta'] * 100,
            color=delta_colors, alpha=0.7, edgecolor='black')

    ax3.set_xlabel('<- Turkish Worse            Turkish Better ->', fontsize=axes_label_size)
    ax3.set_title(f'{second_label} vs {first_label} Performance - Accuracy Delta (percentage points)',
                 fontsize=14, fontweight='bold')
    ax3.axvline(x=0, color='black', linestyle='-', linewidth=1)
    ax3.set_xlim(-30, 30)
    ax3.grid(axis='x', alpha=0.3)
    ax3.set_xticklabels(["-30", "-20", "-10", "0", "+10", "+20", "+30"])

    ax3.tick_params(axis='both', labelsize=axes_label_size)

    # Add value labels inside bars
    for bar, delta in zip(ax3.containers[0], comparison_df['Delta'].values):
        width = bar.get_width()
        if width < 0:
            label_x = width + 1.5
            ha = 'left'
        else:
            label_x = width - 1.5
            ha = 'right'

        ax3.text(label_x, bar.get_y() + bar.get_height()/2,
                f'{delta*100:+.1f}pp',
                ha=ha,
                va='center', fontsize=10,
                color='black')

    # Overall title
    fig.suptitle(f'{benchmark_name} Accuracy Comparison', fontsize=16, fontweight='bold', y=.94)

    # Save and close
    plt.close(fig)

    return fig


def visualize_lendingclub_confusion_matrix(response, benchmark_id, save_path=None):
    """
    Visualize LendingClub evaluation results with confusion matrix

    Args:
        client: Llama Stack client
        eval_job_dict: Dict with "job", "benchmark_id", "label"
        save_path: Optional path to save visualization

    Returns:
        dict: Results summary with confusion matrix data
    """

    # Extract confusion matrix components from scores
    tp = response.scores.get('cra_lending_club:true_positive', {}).aggregated_results.get('true_positive', 0)
    tn = response.scores.get('cra_lending_club:true_negative', {}).aggregated_results.get('true_negative', 0)
    fp = response.scores.get('cra_lending_club:false_positive', {}).aggregated_results.get('false_positive', 0)
    fn = response.scores.get('cra_lending_club:false_negative', {}).aggregated_results.get('false_negative', 0)
    accuracy = response.scores.get('cra_lending_club:acc', {}).aggregated_results.get('acc', 0)

    total = tp + tn + fp + fn

    # Calculate additional metrics
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0

    # Print summary
    # print(f"\n{'=' * 80}")
    # print(f"  FINANCEBENCH EVALUATION RESULTS")
    # print(f"{'=' * 80}")
    # print(f"  Total Samples: {total}")
    # print(f"  Accuracy:      {accuracy*100:.2f}%")
    # print(f"  Precision:     {precision*100:.2f}%")
    # print(f"  Recall:        {recall*100:.2f}%")
    # print(f"  ")
    # print(f"  Confusion Matrix:")
    # print(f"    True Positives:  {int(tp)}")
    # print(f"    True Negatives:  {int(tn)}")
    # print(f"    False Positives: {int(fp)}")
    # print(f"    False Negatives: {int(fn)}")
    # print(f"{'=' * 80}\n")

    # Create visualization
    label_size = 14
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 9), dpi=250)

    # 1. Confusion Matrix
    confusion_matrix = [[tn, fp], [fn, tp]]
    max_val = max(tp, tn, fp, fn) if total > 0 else 1

    im = ax1.imshow(confusion_matrix, cmap='viridis', alpha=0.7, vmin=0, vmax=max_val)

    # Turn off default grid
    ax1.grid(False)

    # Add grid lines between cells - draw on top of image
    ax1.axhline(y=0.5, color='black', linestyle='-', linewidth=2, zorder=3)
    ax1.axvline(x=0.5, color='black', linestyle='-', linewidth=2, zorder=3)

    # Add text annotations
    for i in range(2):
        for j in range(2):
            value = confusion_matrix[i][j]
            percentage = (value / total * 100) if total > 0 else 0
            ax1.text(j, i, f'{int(value)}\n({percentage:.1f}%)',
                    ha="center", va="center", color="black",
                    fontsize=16, zorder=4)

    ax1.set_xticks([0, 1])
    ax1.set_yticks([0, 1])
    ax1.set_xticklabels(['Bad', 'Good'], fontsize=label_size)
    ax1.set_yticklabels(['Bad', 'Good'], fontsize=label_size)
    ax1.set_xlabel('Predicted Loan Judgement', fontsize=label_size+2)
    ax1.set_ylabel('Ground Truth Loan Judgement', fontsize=label_size+2)
    ax1.set_title('Confusion Matrix', fontsize=label_size+4, fontweight='bold')

    # 2. Distribution Pie Chart
    correct = tp + tn
    incorrect = fp + fn

    if correct > 0 or incorrect > 0:
        ax2.pie([correct, incorrect],
                labels=[f'Correct\n({int(correct)})', f'Incorrect\n({int(incorrect)})'],
                colors=['#51cf66', '#ee0000'],
                autopct='%1.1f%%',
                textprops={'fontsize': label_size},
                startangle=90,
                explode=(0.05, 0.05),
                shadow=False)

    ax2.set_title('Overall Results Distribution', fontsize=label_size+4, fontweight='bold')

    # Overall title
    plt.suptitle('CRA Lending Club Results - Qwen3-30b',
                 fontsize=18, fontweight='bold')

    plt.tight_layout()
    plt.subplots_adjust(wspace=0.2)
    plt.show()


## GARAK ===================
bcolor_dict = {
    "PURPLE":   '\033[95m',
    "BLUE":     '\033[94m',
    "CYAN":     '\033[96m',
    "GREEN":    '\033[92m',
    "YELLOW":   '\033[93m',
    "RED":      '\033[91m',
    "ENDC":     '\033[0m',
    "BOLD":     '\033[1m',
    "UNDERLINE":'\033[4m'
}
def bcolor(key, string):
    return bcolor_dict[key.upper()] + string + bcolor_dict['ENDC']

def visualize_garak_results(garak_report):
    """
    Visualize NVIDIA Garak security evaluation results

    Args:
        client: Llama Stack client
        garak_job: Job object from garak evaluation
        benchmark_id: Benchmark ID for the garak evaluation

    Returns:
        dict: Dictionary containing parsed results and dataframes
    """

    # Parse the report data
    results = []

    if isinstance(garak_report, list):
        rows = garak_report
    else:
        rows = garak_report.generations

    for entry in rows:
        # Each entry contains probe information
        probe_name = entry['probe']
        failed = int(entry['vulnerable'])
        total = 1
        passed = total - failed

        # Extract category from probe name (e.g., "encoding.InjectAscii85" -> "encoding")
        category = probe_name.split('.')[0] if '.' in probe_name else 'Other'

        results.append({
            'Probe': probe_name,
            'Category': category,
            'Passed': passed,
            'Failed': failed,
            'Total': total,
            'Failure_Rate': (failed / total * 100) if total > 0 else 0
        })

    df = pd.DataFrame(results)

    if df.empty:
        print("⚠️  No results found in report")
        return None

    # Print summary
    total_tests = df['Total'].sum()
    total_passes = df['Passed'].sum()
    total_failures = df['Failed'].sum()
    overall_failure_rate = (total_failures / total_tests * 100) if total_tests > 0 else 0
    overall_success_rate = (total_passes / total_tests * 100) if total_tests > 0 else 0

    print(f"\n{'=' * 80}")
    print(f"  GARAK SECURITY EVALUATION RESULTS")
    print(f"{'=' * 80}")
    print(f"  Total Attacks:             {total_tests:,}")
    print("  Total Attack Penetrations: "+bcolor("RED", f"{total_failures:,} ({overall_failure_rate:.2f}%)"))
    print(f"  Total Attacks Defended:    "+bcolor("GREEN", f"{total_passes:,} ({overall_success_rate:.2f}%)"))

    print(f"  Unique Probes:             {df['Probe'].nunique()}")
    print(f"  Categories Tested:         {df['Category'].nunique()}")
    print(f"{'=' * 80}\n")

    # Aggregate by category
    category_stats = df.groupby('Category').agg({
        'Total': 'sum',
        'Failed': 'sum',
        'Passed': 'sum'
    }).reset_index()
    category_stats = category_stats[category_stats["Total"] > 0]
    category_stats['Failure_Rate'] = (category_stats['Failed'] / category_stats['Total'] * 100)
    category_stats = category_stats.sort_values('Category', ascending=False)

    # Display category table
    display_df = category_stats.copy()
    display_df['Attack Penetration Rate (%)'] = display_df['Failure_Rate'].round(2)
    #print("\n📊 Results by Category:\n")
    #display(HTML(display_df[['Category', 'Total', 'Passed', 'Failed', 'Failure Rate (%)']].to_html(index=False)))

    # Create visualizations
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 9), dpi=250)

    # Chart 1: Failure rate by category
    colors = ['#ff6b6b' if rate > 50 else '#ffd43b' if rate > 20 else '#51cf66'
              for rate in category_stats['Failure_Rate'].values]

    bars1 = ax1.barh(category_stats['Category'], category_stats['Failure_Rate'],
                     color=colors, alpha=0.7, edgecolor='black')

    ax1.set_xlabel('Penetration Rate (%)', fontsize=12, fontweight='bold')
    ax1.set_title('Vulnerability Detection Rate by Category', fontsize=14, fontweight='bold')
    ax1.set_xlim(0, 100)
    ax1.axvline(x=50, color='gray', linestyle='--', alpha=0.5, label='50% threshold')
    ax1.axvline(x=20, color='gray', linestyle=':', alpha=0.5, label='20% threshold')
    ax1.grid(axis='x', alpha=0.3)
    ax1.legend()

    # Add percentage labels on bars
    for bar, rate in zip(bars1, category_stats['Failure_Rate'].values):
        width = bar.get_width()
        ax1.text(width + 2, bar.get_y() + bar.get_height()/2,
                f'{rate:.1f}%', ha='left', va='center', fontsize=10, fontweight='bold')

    # Chart 2: Test volume by category (stacked: passed vs failed)
    categories = category_stats['Category']
    x_pos = range(len(categories))

    ax2.barh(x_pos, category_stats['Passed'], label='Defended',
             color='#51cf66', alpha=0.7, edgecolor='black')
    ax2.barh(x_pos, category_stats['Failed'], left=category_stats['Passed'],
             label='Penetrated', color='#ff6b6b', alpha=0.7, edgecolor='black')

    ax2.set_yticks(x_pos)
    ax2.set_yticklabels(categories)
    ax2.set_xlabel('Number of Attacks', fontsize=12, fontweight='bold')
    ax2.set_title('Attack Volume by Category', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(axis='x', alpha=0.3)


    plt.tight_layout()
    plt.close(fig)
    #plt.show()

    # Top 10 most vulnerable probes
    probe_stats = df.groupby('Probe').agg({
        'Total': 'sum',
        'Failed': 'sum',
        'Passed': 'sum',
        'Failure_Rate': 'mean'
    }).reset_index()
    top_vulnerable_df = probe_stats.nlargest(10, 'Failure_Rate')[['Probe', 'Total', 'Failed', 'Failure_Rate']].copy()

    if not top_vulnerable_df.empty:
        #print("\n⚠️  Top 10 Most Vulnerable Probes:\n")
        display_vulnerable = top_vulnerable_df.copy()
        display_vulnerable['Failure Rate (%)'] = display_vulnerable['Failure_Rate'].round(2)
        vulnerable_probes = HTML(display_vulnerable[['Probe', 'Total', 'Failed', 'Failure Rate (%)']].to_html(index=False))

        # Visualize top vulnerable probes
        top_vulnerable_df = top_vulnerable_df.sort_values('Failure_Rate', ascending=True)
        fig2, ax = plt.subplots(figsize=(16, 9), dpi=250)

        failure_rates = top_vulnerable_df['Failure_Rate'].tolist()
        probe_names = top_vulnerable_df['Probe'].tolist()

        colors_vuln = ['#ff6b6b' if rate > 50 else '#ffd43b' if rate > 20 else '#51cf66'
                       for rate in failure_rates]

        ax.barh(range(len(top_vulnerable_df)), failure_rates,
                color=colors_vuln, alpha=0.7, edgecolor='black')

        ax.set_yticks(range(len(top_vulnerable_df)))
        ax.set_yticklabels(probe_names)
        ax.set_xlabel('Attack Penetration Rate (%)', fontsize=12, fontweight='bold')
        ax.set_title('Top 10 Most Vulnerable Probes', fontsize=14, fontweight='bold')
        ax.set_xlim(0, 100)
        ax.axvline(x=50, color='gray', linestyle='--', alpha=0.5)
        ax.grid(axis='x', alpha=0.3)

        # Add percentage labels
        for i, rate in enumerate(failure_rates):
            ax.text(rate + 2, i, f'{rate:.1f}%', ha='left', va='center',
                   fontsize=10, fontweight='bold')

        plt.tight_layout()
        plt.close(fig2)

    return fig, vulnerable_probes, fig2

def compare_garak_scans(protected_report, baseline_label="Without Guardrails", protected_label="With Guardrails"):
    """
    Compare two garak scans to show granular attack mitigation from guardrails

    Args:
        baseline_report: Garak report from unprotected model
        protected_report: Garak report from guardrailed model
        baseline_label: Label for baseline scan (default: "Without Guardrails")
        protected_label: Label for protected scan (default: "With Guardrails")

    Returns:
        tuple: (comparison_fig, mitigation_fig, stats_dict)
    """
    # Parse baseline report
    results = []
    for entry in protected_report:
        probe_name = entry['probe']

        model_failed = int(entry['model_vulnerable'])
        model_passed = 1-model_failed

        guardrail_failed = int(entry['guardrail_vulnerable'])
        guardrail_passed = 1-guardrail_failed

        system_failed = int(entry['vulnerable'])
        system_passed = 1-system_failed

        category = probe_name.split('.')[0] if '.' in probe_name else 'Other'


        results.append({
            'Probe': probe_name,
            'Category': category,
            'Total': 1,
            'Model_Failed': model_failed,
            'Model_Passed': model_passed,
            'Guardrail_Failed': guardrail_failed,
            'Guardrail_Passed': guardrail_passed,
            'Guardrail_Latency': entry['guardrail_latency'],
            'System_Failed': system_failed,
            'System_Passed': system_passed,
        })

    df = pd.DataFrame(results)

    # Categorize each probe by protection source
    df['Protection_Source'] = 'Neither'  # Default
    df.loc[(df['Model_Passed'] == 1) & (df['Guardrail_Passed'] == 0), 'Protection_Source'] = 'Model Only'
    df.loc[(df['Model_Passed'] == 0) & (df['Guardrail_Passed'] == 1), 'Protection_Source'] = 'Guardrail Only'
    df.loc[(df['Model_Passed'] == 1) & (df['Guardrail_Passed'] == 1), 'Protection_Source'] = 'Both'

    # Overall statistics
    total_attacks = len(df)
    total_model_failed = df['Model_Failed'].sum()
    total_model_passed = df['Model_Passed'].sum()
    total_system_failed = df['System_Failed'].sum()
    total_system_passed = df['System_Passed'].sum()

    attacks_mitigated = total_model_failed - total_system_failed
    mitigation_rate = (attacks_mitigated / total_model_failed * 100) if total_model_failed > 0 else 0

    # Print summary
    print(f"\n{'=' * 80}")
    print(f"  GARAK GUARDRAIL EFFECTIVENESS COMPARISON")
    print(f"{'=' * 80}")
    print(f"\n  {baseline_label} (Model Only):")
    print(f"    Total Attacks:        {total_attacks:,}")
    print(f"    Attacks Penetrated:   " + bcolor("RED", f"{total_model_failed:,} ({total_model_failed/total_attacks*100:.1f}%)"))
    print(f"    Attacks Defended:     " + bcolor("GREEN", f"{total_model_passed:,} ({total_model_passed/total_attacks*100:.1f}%)"))

    print(f"\n  {protected_label} (Model + Guardrails):")
    print(f"    Total Attacks:        {total_attacks:,}")
    print(f"    Attacks Penetrated:   " + bcolor("RED", f"{total_system_failed:,} ({total_system_failed/total_attacks*100:.1f}%)"))
    print(f"    Attacks Defended:     " + bcolor("GREEN", f"{total_system_passed:,} ({total_system_passed/total_attacks*100:.1f}%)"))

    print(f"\n  Guardrail Impact:")
    print(f"    Attacks Mitigated:    " + bcolor("GREEN", f"{int(attacks_mitigated):,} ({mitigation_rate:.1f}% of baseline vulnerabilities)"))

    # Category statistics
    category_stats = df.groupby('Category').agg({
        'Total': 'sum',
        'Model_Failed': 'sum',
        'Model_Passed': 'sum',
        'System_Failed': 'sum',
        'System_Passed': 'sum'
    }).reset_index()


    # Create visualizations
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 9), dpi=250)

    # Chart 1: Overall Attack Defense Comparison
    labels = [f'{baseline_label}\n(Model Only)', f'{protected_label}\n(Model + Guardrails)']
    penetrated = [total_model_failed, total_system_failed]
    defended = [total_model_passed, total_system_passed]

    x = range(len(labels))
    width = 0.6

    ax1.bar(x, defended, width, label='Defended', color='#51cf66', alpha=0.8, edgecolor='black')
    ax1.bar(x, penetrated, width, bottom=defended, label='Penetrated', color='#ff6b6b', alpha=0.8, edgecolor='black')

    ax1.set_ylabel('Number of Attacks', fontsize=12, fontweight='bold')
    ax1.set_title('Overall Attack Defense Comparison', fontsize=14, fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.legend()
    ax1.grid(axis='y', alpha=0.3)

    # Add value labels
    for i, (def_val, pen_val) in enumerate(zip(defended, penetrated)):
        total = def_val + pen_val
        if pen_val > 0:
            ax1.text(i, def_val + pen_val/2, f'{int(pen_val):,}\n({pen_val/total*100:.1f}%)',
                    ha='center', va='center', color='white', fontweight='bold', fontsize=11)

    # Chart 2: Attack Penetration by Category
    category_stats['Improvement'] = category_stats['Model_Failed'] - category_stats['System_Failed']
    category_stats = category_stats[category_stats['Total'] > 0].sort_values('Model_Failed', ascending=True)

    # Toggle for normalized view (percentage vs raw count)
    normalize_category_chart = True

    y_pos = range(len(category_stats))
    width = 0.35

    if normalize_category_chart:
        # Calculate penetration rates as percentages
        category_stats['Model_Failed_Pct'] = (category_stats['Model_Failed'] / category_stats['Total']) * 100
        category_stats['System_Failed_Pct'] = (category_stats['System_Failed'] / category_stats['Total']) * 100

        ax2.barh([y - width/2 for y in y_pos], category_stats['Model_Failed_Pct'],
                 width, label='Model Only', color='#ff6b6b', alpha=0.7, edgecolor='black')
        ax2.barh([y + width/2 for y in y_pos], category_stats['System_Failed_Pct'],
                 width, label='Model + Guardrails', color='#51cf66', alpha=0.8, edgecolor='black')

        ax2.set_xlabel('Penetration Rate (%)', fontsize=12, fontweight='bold')
        ax2.set_xlim(0, 100)
    else:
        ax2.barh([y - width/2 for y in y_pos], category_stats['Model_Failed'],
                 width, label='Model Only', color='#ff6b6b', alpha=0.7, edgecolor='black')
        ax2.barh([y + width/2 for y in y_pos], category_stats['System_Failed'],
                 width, label='Model + Guardrails', color='#51cf66', alpha=0.8, edgecolor='black')

        ax2.set_xlabel('Penetrated Attacks', fontsize=12, fontweight='bold')

    ax2.set_yticks(y_pos)
    ax2.set_yticklabels(category_stats['Category'])
    ax2.set_title('Attack Penetration by Category', fontsize=14, fontweight='bold')
    ax2.legend(fontsize=10)
    ax2.grid(axis='x', alpha=0.3)

    # Chart 3: Protection Source Breakdown
    protection_counts = df['Protection_Source'].value_counts()
    colors_map = {
        'Model Only': '#4dabf7',
        'Guardrail Only': '#ffd43b',
        'Both': '#51cf66',
        'Neither': '#ff6b6b'
    }

    # Ensure all categories present
    for source in ['Model Only', 'Guardrail Only', 'Both', 'Neither']:
        if source not in protection_counts:
            protection_counts[source] = 0

    protection_counts = protection_counts[['Model Only', 'Guardrail Only', 'Both', 'Neither']]
    colors = [colors_map[source] for source in protection_counts.index]

    # Custom autopct function to show both count and percentage
    def make_autopct(values):
        def my_autopct(pct):
            total = sum(values)
            val = int(round(pct*total/100.0))
            return f'{val:,}\n({pct:.1f}%)'
        return my_autopct

    # Create pie chart with larger radius to fill more of the subplot
    wedges, texts, autotexts = ax3.pie(protection_counts.values,
                                         labels=protection_counts.index,
                                         autopct=make_autopct(protection_counts.values),
                                         startangle=0,
                                         colors=colors,
                                         radius=1.3,  # Increase radius to make pie bigger
                                         textprops={'fontsize': 9, 'fontweight': 'bold'},
                                         labeldistance=1.03,  # Position labels further from center
                                         pctdistance=0.82)    # Position percentages closer to edge

    ax3.set_title('Protection Source: What Caught Each Attack?', fontsize=14, fontweight='bold', pad=20)

    # Chart 4: Guardrail Latency Analysis - Necessary vs Unnecessary
    necessary_guardrails = df[df['Protection_Source'] == 'Guardrail Only']  # Only guardrail caught it
    unnecessary_guardrails = df[df['Protection_Source'].isin(['Model Only', 'Both'])]  # Model caught it

    latency_data = []
    labels_latency = []

    if len(necessary_guardrails) > 0:
        total_necessary = necessary_guardrails['Guardrail_Latency'].sum()
        avg_necessary = necessary_guardrails['Guardrail_Latency'].mean()
        latency_data.append(total_necessary)
        labels_latency.append(f'Critical\n(Model was vulnerable to attack)\nn={len(necessary_guardrails)}')

    if len(unnecessary_guardrails) > 0:
        total_unnecessary = unnecessary_guardrails['Guardrail_Latency'].sum()
        avg_unnecessary = unnecessary_guardrails['Guardrail_Latency'].mean()
        latency_data.append(total_unnecessary)
        labels_latency.append(f'Redundant\n(Model was not vulnerable to attack)\nn={len(unnecessary_guardrails)}')

    colors_latency = ['#ffd43b', '#4dabf7']

    # Convert latency data to minutes for display
    latency_data_minutes = [val / 60 for val in latency_data]
    bars = ax4.bar(range(len(latency_data_minutes)), latency_data_minutes, color=colors_latency,
                   alpha=0.8, edgecolor='black', width=0.6)

    ax4.set_xticks(range(len(labels_latency)))
    ax4.set_xticklabels(labels_latency, fontsize=10)
    ax4.set_ylabel('Total Latency (minutes)', fontsize=12, fontweight='bold')
    ax4.set_title('Guardrail Latency Impact: Critical vs Redundant', fontsize=14, fontweight='bold')
    ax4.grid(axis='y', alpha=0.3)

    # Add value labels - position inside the bars to avoid overlap with title
    for i, (bar, val_seconds) in enumerate(zip(bars, latency_data)):
        height = bar.get_height()
        n_attacks = len(necessary_guardrails) if i == 0 else len(unnecessary_guardrails)
        avg_val = val_seconds / n_attacks if n_attacks > 0 else 0

        # Format time as minutes and seconds
        minutes = int(val_seconds // 60)
        seconds = int(val_seconds % 60)
        time_str = f'{minutes}m {seconds}s'

        # Position text at the top inside the bar
        ax4.text(bar.get_x() + bar.get_width() / 2, height * 0.95,
                 f'{time_str}\navg: {avg_val:.3f}s',
                 ha='center', va='top', fontweight='bold', fontsize=9, color='black')


    plt.tight_layout(pad=2.0)
    plt.close(fig)

    # Statistics dictionary
    stats_dict = {
        'total_attacks': total_attacks,
        'total_model_failed': int(total_model_failed),
        'total_model_passed': int(total_model_passed),
        'total_system_failed': int(total_system_failed),
        'total_system_passed': int(total_system_passed),
        'attacks_mitigated': int(attacks_mitigated),
        'mitigation_rate': mitigation_rate,
        'protection_breakdown': df['Protection_Source'].value_counts().to_dict(),
        'necessary_guardrail_latency': necessary_guardrails['Guardrail_Latency'].sum() if len(necessary_guardrails) > 0 else 0,
        'unnecessary_guardrail_latency': unnecessary_guardrails['Guardrail_Latency'].sum() if len(unnecessary_guardrails) > 0 else 0,
        'df': df
    }

    return fig, stats_dict

## RAGAS ==========
def populate_vector_db(client, dataset_df):
    """
    Populate a vector database with context documents using OpenAI-compatible API

    Args:
        client: LlamaStackClient instance
        dataset_df: Pandas DataFrame with 'references' column
        vector_store_id: ID for the vector database

    Returns:
        dict: Statistics about the ingestion process with file_id
    """


    contexts = set()
    for reference in dataset_df["references"]:
        contexts.update(reference)
    contexts = list(contexts)
    total_docs = len(contexts)

    # Clean previous vector stores
    stores = client.vector_stores.list()
    for store in stores:
        if store.name == "finder_db":
            client.vector_stores.delete(vector_store_id=store.id)
            print(f"Cleaning existing vector store: {store.id}")

    # Create vector store
    vs = client.vector_stores.create(name="finder_db", extra_body={
        "embedding_model": "vllm-embedding/embedding",
        "embedding_dimension": 1024,
        "provider_id": "milvus",
    })
    chunking_strategy = {
        "type": "static",
        "static": {
            "max_chunk_size_tokens": 4096,
            "chunk_overlap_tokens": 400
        }
    }
    batch = []
    for i, context in enumerate(contexts):
        print(f"\rUploading context document {i+1}/{total_docs}", end="")
        # Upload document
        pseudo_file = io.BytesIO(context.encode('utf-8'))
        file_id = client.files.create(file=(f"context_{i}.txt", pseudo_file, "text/plain"), purpose="assistants").id
        batch.append(file_id)

        if len(batch) > 50:
            upload_result = client.vector_stores.file_batches.create(
                vector_store_id=vs.id,
                file_ids=batch,
                chunking_strategy=chunking_strategy,

            )
            if upload_result.status not in ["completed", "in_progress"]:
                print(upload_result)
            batch = []
    return client.vector_stores.retrieve(vector_store_id=vs.id)

def generate_rag_samples(client, vector_store, dataset_df, num_references):
    ragas_dataset = []
    # Explicitly search vector store via REST API
    for i, (_, row) in enumerate(dataset_df.iterrows()):
        print(f"\rGenerating RAG samples: {i+1}/{len(dataset_df)}", end="")

        task_description = "'Given a search query, retrieve relevant passages."
        query = f'Instruct: {task_description}\nQuery:{row['text']}'

        search_results = client.vector_stores.search(
            vector_store_id=vector_store.id,
            query=query,
            max_num_results=num_references,
        )
        contexts = [r.content[0].text for r in search_results.data if r.content]
        context = "\n\n".join(contexts)

        # Manually construct prompt with context
        completion = client.chat.completions.create(
            model="vllm/qwen3",
            messages=[
                {"role": "system", "content": "Use the provided context to answer queries. Keep answers brief."},
                {"role": "user", "content": f"Context:\n{context}\n\nQuery: {row['text']}"}
            ],
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            temperature=.7,
            top_p=.8,
            max_tokens=250,
        )

        ragas_dataset.append({
            "user_input": row['text'],
            "response": completion.choices[0].message.content,
            "retrieved_contexts": contexts,
            "reference": row['answer']
        })
    print(" Done!")
    pd.DataFrame(ragas_dataset).to_csv(f"ragas_dataset_{num_references}.csv")
    return ragas_dataset


def register_ragas_dataset(client, ragas_dataset):
    from datetime import datetime

    # De-register the dataset and benchmark if it already exists
    dataset_id = "FinDER-RAGAS"
    benchmark_id = f"trustyai_ragas::FinDER_{str(uuid.uuid4())}"
    try:
        client.beta.datasets.unregister(dataset_id)
    except Exception as e:
        pass

    client.beta.datasets.register(
        dataset_id=dataset_id,
        purpose="eval/question-answer",  # RAG evaluation purpose
        source={"type": "rows", "rows": ragas_dataset},
        metadata={
            "provider_id": "localfs",
            "description": "FinDER Dataset",
            "size": len(ragas_dataset),
            "format": "ragas",
            "created_at": datetime.now().isoformat(),
        },
    );

    client.alpha.benchmarks.register(
        benchmark_id=benchmark_id,
        dataset_id=dataset_id,
        scoring_functions=[
            "answer_relevancy",  # How relevant is the answer to the question?
        ],
        provider_id="trustyai_ragas_inline",
    );
    return benchmark_id


def visualize_ragas_results(ragas_results):
    """
    Visualize RAGAS evaluation results

    Args:
        client: Llama Stack client
        ragas_job: Job object from RAGAS evaluation
        benchmark_id: Benchmark ID for the RAGAS evaluation
        save_path: Optional path to save the visualization

    Returns:
        dict: Dictionary containing parsed results and statistics
    """

    # Extract scores for all metrics
    all_metrics = {}

    for metric_name, metric_data in ragas_results.scores.items():
        if hasattr(metric_data, 'score_rows') and hasattr(metric_data, 'aggregated_results'):
            scores = [row['score'] for row in metric_data.score_rows]
            aggregated = metric_data.aggregated_results.get(metric_name, 0)

            all_metrics[metric_name] = {
                'scores': scores,
                'aggregated': aggregated
            }

    if not all_metrics:
        print("❌ No RAGAS metrics found in results")
        return None

    # Process primary metric (first one found, typically answer_relevancy)
    primary_metric = list(all_metrics.keys())[0]
    metric_data = all_metrics[primary_metric]
    scores = metric_data['scores']
    aggregated_score = metric_data['aggregated']

    # Calculate statistics
    total_samples = len(scores)
    zero_scores = sum(1 for s in scores if s == 0.0)
    non_zero_scores = [s for s in scores if s > 0.0]
    non_zero_count = len(non_zero_scores)

    if non_zero_scores:
        avg_non_zero = sum(non_zero_scores) / len(non_zero_scores)
        sorted_scores = sorted(non_zero_scores)
        median_non_zero = sorted_scores[len(sorted_scores) // 2]
        variance = sum((x - avg_non_zero) ** 2 for x in non_zero_scores) / len(non_zero_scores)
    else:
        avg_non_zero = median_non_zero = std_non_zero = min_score = max_score = 0.0

    # # Print summary
    # print(f"\n{'=' * 80}")
    # print(f"  RAGAS EVALUATION RESULTS - {primary_metric.upper()}")
    # print(f"{'=' * 80}")
    # print(f"  Total Samples: {total_samples}")
    # print(f"  Relevant Answers: {non_zero_count} ({non_zero_count/total_samples*100:.1f}%)")
    # print(f"  Irrelevant Answers (score=0): {zero_scores} ({zero_scores/total_samples*100:.1f}%)")
    # print(f"  Aggregated Score: {aggregated_score:.4f}")
    # if non_zero_scores:
    #     print(f"  Avg (relevant only): {avg_non_zero:.4f}")
    #     print(f"  Median (relevant only): {median_non_zero:.4f}")
    # print(f"{'=' * 80}\n")

    # Create visualization
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 10), dpi=250)

    # 1. Score Distribution Histogram
    bins = [i/20 for i in range(21)]  # 0 to 1 in steps of 0.05
    n, bin_edges, patches = ax1.hist(scores, bins=bins, edgecolor='black', alpha=0.7, color='steelblue')

    # Color zero bin differently
    if bin_edges[0] < 0.05:
        patches[0].set_facecolor('coral')

    ax1.axvline(aggregated_score, color='red', linestyle='--', linewidth=2,
                label=f'Aggregated: {aggregated_score:.3f}')
    if non_zero_scores:
        ax1.axvline(avg_non_zero, color='green', linestyle='--', linewidth=2,
                    label=f'Avg (non-zero): {avg_non_zero:.3f}')

    ax1.set_xlabel('Score', fontsize=12, fontweight='bold')
    ax1.set_ylabel('Frequency', fontsize=12, fontweight='bold')
    ax1.set_title(f'{primary_metric.replace("_", " ").title()} Distribution',
                  fontsize=14, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)

    # 2. Relevance Distribution Pie Chart
    labels = [f'Relevant\n({non_zero_count})', f'Irrelevant\n({zero_scores})']
    sizes = [non_zero_count, zero_scores]
    colors = ['#51cf66', '#ee0000']
    explode = (0.05, 0.05)

    wedges, texts, autotexts = ax2.pie(sizes, explode=explode, labels=labels, colors=colors,
                                         autopct='%1.1f%%', shadow=False, startangle=90)
    for autotext in autotexts:
        autotext.set_color('white')
        autotext.set_fontweight('bold')
        autotext.set_fontsize(11)

    ax2.set_title('Answer Relevance Distribution', fontsize=14, fontweight='bold')

    # 3. Score Range Breakdown (bar chart)
    ranges = {
        'Zero\n(0.0)': zero_scores,
        'Poor\n(0.0-0.4)': sum(1 for s in non_zero_scores if 0 < s < 0.4),
        'Fair\n(0.4-0.6)': sum(1 for s in non_zero_scores if 0.4 <= s < 0.6),
        'Good\n(0.6-0.8)': sum(1 for s in non_zero_scores if 0.6 <= s < 0.8),
        'Excellent\n(0.8-1.0)': sum(1 for s in non_zero_scores if s >= 0.8)
    }

    range_colors = ['#ee0000', '#ff6b6b', '#ffa94d', '#ffd43b', '#51cf66']
    bars = ax3.bar(range(len(ranges)), list(ranges.values()),
                  color=range_colors, alpha=0.7, edgecolor='black')

    ax3.set_xticks(range(len(ranges)))
    ax3.set_xticklabels(list(ranges.keys()), fontsize=10)
    ax3.set_ylabel('Count', fontsize=12, fontweight='bold')
    ax3.set_title('Score Distribution by Range', fontsize=14, fontweight='bold')
    ax3.set_xlabel("Answer Relevance")
    ax3.grid(axis='y', alpha=0.3)

    # Add count labels on bars
    for bar in bars:
        height = bar.get_height()
        if height > 0:
            ax3.text(bar.get_x() + bar.get_width()/2., height,
                    f'{int(height)}',
                    ha='center', va='bottom', fontweight='bold')

    # 4. Sequential Score Plot
    x = list(range(1, len(scores) + 1))
    colors_seq = ['coral' if s == 0 else 'steelblue' for s in scores]
    ax4.scatter(x, scores, c=colors_seq, alpha=0.6, s=40)
    ax4.axhline(aggregated_score, color='red', linestyle='--', linewidth=1.5, alpha=0.7,
                label=f'Aggregated: {aggregated_score:.3f}')
    if non_zero_scores:
        ax4.axhline(avg_non_zero, color='green', linestyle='--', linewidth=1.5, alpha=0.7,
                    label=f'Avg (non-zero): {avg_non_zero:.3f}')

    ax4.set_xlabel('Sample Index', fontsize=12, fontweight='bold')
    ax4.set_ylabel('Score', fontsize=12, fontweight='bold')
    ax4.set_title('Scores by Sample', fontsize=14, fontweight='bold')
    ax4.set_ylim([-0.05, 1.05])
    ax4.legend(fontsize=10, loc='lower right')
    ax4.grid(True, alpha=0.3)

    plt.suptitle(f'RAGAS Evaluation - {primary_metric.replace("_", " ").title()}',
                 fontsize=16, fontweight='bold')

    plt.tight_layout()
    plt.show()
