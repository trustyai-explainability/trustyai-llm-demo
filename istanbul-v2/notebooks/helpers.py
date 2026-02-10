import time
import io
import pandas as pd
import matplotlib.pyplot as plt
from IPython.display import display, HTML
import json
import datetime

def monitor_job_status(client, evaluation):
    loop_idx = 0
    start_t = time.time()

    benchmark_id = evaluation["benchmark_id"]
    job = evaluation["job"]

    while True:
        if loop_idx % 20 == 0:
            job = client.alpha.eval.jobs.status(job_id=job.job_id, benchmark_id=benchmark_id)
        if job.status == 'failed':
            print(f"\r❌ {benchmark_id} job {job.job_id} failed"+" "*50)
            break
        elif job.status == 'completed':
            if "metadata" in job:
                delta_t = datetime.datetime.fromisoformat(job.metadata["finished_at"]) - datetime.datetime.fromisoformat(
                    job.metadata["created_at"])
                delta_t_string = " ".join([item+"hms"[i] for i, item in enumerate(f"{delta_t!s}".split(":")) if int(item)!=0])
                print(f"\n✅ {benchmark_id} job {job.job_id} finished in {delta_t_string}!"+" "*50)
            else:
                delta_t = int(time.time() - start_t)
                minutes = delta_t // 60
                seconds = delta_t % 60
                print(f"\n✅ {benchmark_id} job {job.job_id} finished in {minutes}m {seconds}s!" + " " * 50)
            break
        else:
            emoji = "🕛🕐🕑🕒🕓🕔🕕🕖🕗🕘🕙🕚"[loop_idx %12]
            print(f"\r️{emoji*3} {benchmark_id} job {job.job_id} running...", end="")
        loop_idx += 1
        time.sleep(.25)


def compare_evaluation_runs(client, evaluations: dict, benchmark_name="Benchmark"):
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

    # Sort by first run's accuracy
    #comparison_df = comparison_df.sort_values(f'Accuracy_{first_label}', ascending=False)

    # Print summary
    # print(f"\n{'=' * 80}")
    # print(f"  {benchmark_name.upper()} COMPARISON: {first_label} vs {second_label}")
    # print(f"{'=' * 80}")
    # print(f"  {first_label} Average: {comparison_df[f'Accuracy_{first_label}'].mean() * 100:.2f}%")
    # print(f"  {second_label} Average: {comparison_df[f'Accuracy_{second_label}'].mean() * 100:.2f}%")
    # print(f"  Average Delta: {comparison_df['Delta'].mean() * 100:.2f}% ({comparison_df['Delta'].mean() * 100:+.2f} percentage points)")
    # print(f"{'=' * 80}\n")

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
    plt.savefig(f'{benchmark_name}_comparison.png', dpi=300, bbox_inches='tight')
    plt.close(fig)

    return display_html, fig



def visualize_garak_results(client, garak_job, benchmark_id="trustyai_garak::standard"):
    """
    Visualize NVIDIA Garak security evaluation results

    Args:
        client: Llama Stack client
        garak_job: Job object from garak evaluation
        benchmark_id: Benchmark ID for the garak evaluation

    Returns:
        dict: Dictionary containing parsed results and dataframes
    """

    # Get job status to retrieve file IDs
    job_status = client.alpha.eval.jobs.status(
        job_id=garak_job.job_id,
        benchmark_id=benchmark_id
    )

    if job_status.status != 'completed':
        print(f"⚠️  Job status: {job_status.status}")
        return None

    # Find the report.jsonl file
    report_file_id = None
    result_file_id = None

    for key, value in job_status.metadata.items():
        if 'scan.report.jsonl' in key:
            report_file_id = value
        elif 'scan_result.json' in key:
            result_file_id = value

    if not report_file_id:
        print("❌ Could not find report file in job metadata")
        return None

    # Download and parse the report file
    print(f"📥 Downloading garak results...")

    try:
        # Use the correct client.files.content() method
        content = client.files.content(report_file_id)

        # Parse JSONL (each line is a JSON object)
        report_lines = [json.loads(line) for line in content.strip().split('\n') if line.strip()]

    except Exception as e:
        print(f"❌ Error downloading report: {e}")
        return None

    # Parse the report data
    results = []

    for entry in report_lines:
        # Each entry contains probe information
        probe_name = entry.get('probe', 'Unknown')
        detector_name = entry.get('detector', 'Unknown')
        passed = entry.get('passed', 0)
        total = entry.get('total', 0)
        failed = total - passed

        # Extract category from probe name (e.g., "encoding.InjectAscii85" -> "encoding")
        category = probe_name.split('.')[0] if '.' in probe_name else 'Other'

        results.append({
            'Probe': probe_name,
            'Detector': detector_name,
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
    total_failures = df['Failed'].sum()
    overall_failure_rate = (total_failures / total_tests * 100) if total_tests > 0 else 0

    print(f"\n{'=' * 80}")
    print(f"  GARAK SECURITY EVALUATION RESULTS")
    print(f"{'=' * 80}")
    print(f"  Total Tests: {total_tests:,}")
    print(f"  Total Failures: {total_failures:,} ({overall_failure_rate:.2f}%)")
    print(f"  Total Passed: {df['Passed'].sum():,}")
    print(f"  Unique Probes: {df['Probe'].nunique()}")
    print(f"  Categories Tested: {df['Category'].nunique()}")
    print(f"{'=' * 80}\n")

    # Aggregate by category
    category_stats = df.groupby('Category').agg({
        'Total': 'sum',
        'Failed': 'sum',
        'Passed': 'sum'
    }).reset_index()
    category_stats['Failure_Rate'] = (category_stats['Failed'] / category_stats['Total'] * 100)
    category_stats = category_stats.sort_values('Failure_Rate', ascending=False)

    # Display category table
    display_df = category_stats.copy()
    display_df['Failure Rate (%)'] = display_df['Failure_Rate'].round(2)
    print("\n📊 Results by Category:\n")
    display(HTML(display_df[['Category', 'Total', 'Passed', 'Failed', 'Failure Rate (%)']].to_html(index=False)))

    # Create visualizations
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    # Chart 1: Failure rate by category
    colors = ['#ff6b6b' if rate > 50 else '#ffd43b' if rate > 20 else '#51cf66'
              for rate in category_stats['Failure_Rate'].values]

    bars1 = ax1.barh(category_stats['Category'], category_stats['Failure_Rate'],
                     color=colors, alpha=0.7, edgecolor='black')

    ax1.set_xlabel('Failure Rate (%)', fontsize=12, fontweight='bold')
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

    ax2.barh(x_pos, category_stats['Passed'], label='Passed',
             color='#51cf66', alpha=0.7, edgecolor='black')
    ax2.barh(x_pos, category_stats['Failed'], left=category_stats['Passed'],
             label='Failed', color='#ff6b6b', alpha=0.7, edgecolor='black')

    ax2.set_yticks(x_pos)
    ax2.set_yticklabels(categories)
    ax2.set_xlabel('Number of Tests', fontsize=12, fontweight='bold')
    ax2.set_title('Test Volume by Category', fontsize=14, fontweight='bold')
    ax2.legend()
    ax2.grid(axis='x', alpha=0.3)

    plt.tight_layout()
    plt.show()

    # Top 10 most vulnerable probes
    top_vulnerable_df = df.nlargest(10, 'Failure_Rate')[['Probe', 'Total', 'Failed', 'Failure_Rate']].copy()

    if not top_vulnerable_df.empty:
        print("\n⚠️  Top 10 Most Vulnerable Probes:\n")
        display_vulnerable = top_vulnerable_df.copy()
        display_vulnerable['Failure Rate (%)'] = display_vulnerable['Failure_Rate'].round(2)
        display(HTML(display_vulnerable[['Probe', 'Total', 'Failed', 'Failure Rate (%)']].to_html(index=False)))

        # Visualize top vulnerable probes
        _, ax = plt.subplots(figsize=(12, 8))

        failure_rates = top_vulnerable_df['Failure_Rate'].tolist()
        probe_names = top_vulnerable_df['Probe'].tolist()

        colors_vuln = ['#ff6b6b' if rate > 50 else '#ffd43b' if rate > 20 else '#51cf66'
                       for rate in failure_rates]

        ax.barh(range(len(top_vulnerable_df)), failure_rates,
                color=colors_vuln, alpha=0.7, edgecolor='black')

        ax.set_yticks(range(len(top_vulnerable_df)))
        ax.set_yticklabels(probe_names)
        ax.set_xlabel('Failure Rate (%)', fontsize=12, fontweight='bold')
        ax.set_title('Top 10 Most Vulnerable Probes', fontsize=14, fontweight='bold')
        ax.set_xlim(0, 100)
        ax.axvline(x=50, color='gray', linestyle='--', alpha=0.5)
        ax.grid(axis='x', alpha=0.3)

        # Add percentage labels
        for i, rate in enumerate(failure_rates):
            ax.text(rate + 2, i, f'{rate:.1f}%', ha='left', va='center',
                   fontsize=10, fontweight='bold')

        plt.tight_layout()
        plt.show()

    return {
        'all_results': df,
        'category_stats': category_stats,
        'top_vulnerable': top_vulnerable_df
    }


def populate_vector_db(client, dataset_df, column):
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
    for reference in dataset_df[column]:
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



def perform_rag_inferences(client, dataset_df, vector_db_id="finder_contexts",
                          model_id="vllm/qwen3", num_samples=100):
    """
    Perform RAG inferences on dataset questions

    Args:
        client: LlamaStackClient instance
        dataset_df: DataFrame with 'question' column
        vector_db_id: ID of the vector database to query
        model_id: Model to use for generation
        num_samples: Number of samples to evaluate

    Returns:
        DataFrame with questions, contexts, answers, and ground truth
    """

    print(f"🔍 Performing RAG inferences on {num_samples} samples...")

    # Sample questions from dataset
    sample_df = dataset_df.sample(n=min(num_samples, len(dataset_df)), random_state=42).copy()

    results = []

    for idx, row in sample_df.iterrows():
        question = row['question']
        ground_truth = row.get('answer', '')

        try:
            # Retrieve relevant contexts from vector DB
            retrieved_docs = client.vector_io.query(
                vector_db_id=vector_db_id,
                query=question,
                k=3  # Retrieve top 3 most relevant documents
            )

            # Extract context text
            contexts = [doc['content'] for doc in retrieved_docs.get('documents', [])]
            context_text = "\n\n".join(contexts)

            # Generate answer using RAG
            messages = [
                {
                    "role": "system",
                    "content": "You are a helpful financial assistant. Answer the question based on the provided context."
                },
                {
                    "role": "user",
                    "content": f"Context:\n{context_text}\n\nQuestion: {question}\n\nAnswer:"
                }
            ]

            response = client.inference.chat_completion(
                model_id=model_id,
                messages=messages,
                sampling_params={
                    "temperature": 0.1,
                    "max_tokens": 256
                }
            )

            answer = response.completion_message.content

            results.append({
                'question': question,
                'contexts': contexts,
                'answer': answer,
                'ground_truth': ground_truth
            })

            print(f"\r  • Completed {len(results)}/{num_samples} inferences...", end="")

        except Exception as e:
            print(f"\n  ⚠️  Error on question {idx}: {e}")
            continue

    print(f"\n✅ RAG inferences complete!")

    return pd.DataFrame(results)


def run_ragas_evaluation(rag_results_df, metrics=None):
    """
    Run RAGAS evaluation on RAG results

    Args:
        rag_results_df: DataFrame with columns: question, contexts, answer, ground_truth
        metrics: List of RAGAS metrics to compute (default: all core metrics)

    Returns:
        dict: RAGAS evaluation results and visualizations
    """

    try:
        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall
        )
        from datasets import Dataset
    except ImportError:
        print("❌ RAGAS library not installed. Install with: pip install ragas")
        return None

    if metrics is None:
        metrics = [faithfulness, answer_relevancy, context_precision, context_recall]

    print(f"📊 Running RAGAS evaluation with {len(metrics)} metrics...")

    # Convert to HuggingFace Dataset format expected by RAGAS
    ragas_dataset = Dataset.from_pandas(rag_results_df)

    # Run evaluation
    try:
        results = evaluate(ragas_dataset, metrics=metrics)

        print(f"\n{'=' * 80}")
        print(f"  RAGAS EVALUATION RESULTS")
        print(f"{'=' * 80}")

        # Display results
        results_dict = {}
        for metric_name, score in results.items():
            results_dict[metric_name] = score
            print(f"  {metric_name}: {score:.4f}")

        print(f"{'=' * 80}\n")

        # Create visualization
        visualize_ragas_results(results_dict)

        return {
            'scores': results_dict,
            'detailed_results': results
        }

    except Exception as e:
        print(f"❌ Error running RAGAS evaluation: {e}")
        return None


def visualize_ragas_results(scores_dict):
    """
    Visualize RAGAS evaluation scores

    Args:
        scores_dict: Dictionary of metric names to scores
    """

    # Create DataFrame for visualization
    df = pd.DataFrame([
        {'Metric': metric.replace('_', ' ').title(), 'Score': score}
        for metric, score in scores_dict.items()
    ]).sort_values('Score', ascending=False)

    # Display table
    display_df = df.copy()
    display_df['Score (%)'] = (display_df['Score'] * 100).round(2)
    print("\n📊 RAGAS Metrics Summary:\n")
    display(HTML(display_df[['Metric', 'Score (%)']].to_html(index=False)))

    # Create visualization
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))

    # Bar chart
    colors = ['#51cf66' if score >= 0.7 else '#ffd43b' if score >= 0.5 else '#ff6b6b'
              for score in df['Score'].values]

    bars = ax1.barh(df['Metric'], df['Score'] * 100, color=colors, alpha=0.7, edgecolor='black')
    ax1.set_xlabel('Score (%)', fontsize=12, fontweight='bold')
    ax1.set_title('RAGAS Metrics Performance', fontsize=14, fontweight='bold')
    ax1.set_xlim(0, 100)
    ax1.axvline(x=70, color='green', linestyle='--', alpha=0.5, label='Good (70%)')
    ax1.axvline(x=50, color='orange', linestyle='--', alpha=0.5, label='Fair (50%)')
    ax1.grid(axis='x', alpha=0.3)
    ax1.legend()

    # Add percentage labels
    for bar, score in zip(bars, df['Score'].values):
        width = bar.get_width()
        ax1.text(width + 2, bar.get_y() + bar.get_height()/2,
                f'{score*100:.1f}%', ha='left', va='center', fontsize=10, fontweight='bold')

    # Radar chart
    metrics_list = df['Metric'].tolist()
    scores_list = df['Score'].tolist()

    angles = [n / len(metrics_list) * 2 * 3.14159 for n in range(len(metrics_list))]
    scores_list += scores_list[:1]  # Complete the circle
    angles += angles[:1]

    ax2 = plt.subplot(122, polar=True)
    ax2.plot(angles, scores_list, 'o-', linewidth=2, color='#ee0000', label='Scores')
    ax2.fill(angles, scores_list, alpha=0.25, color='#ee0000')
    ax2.set_xticks(angles[:-1])
    ax2.set_xticklabels(metrics_list, size=10)
    ax2.set_ylim(0, 1)
    ax2.set_yticks([0.25, 0.5, 0.75, 1.0])
    ax2.set_yticklabels(['25%', '50%', '75%', '100%'])
    ax2.set_title('RAGAS Metrics Radar', fontsize=14, fontweight='bold', pad=20)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.show()

    return df
