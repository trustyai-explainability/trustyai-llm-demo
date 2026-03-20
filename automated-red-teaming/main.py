import marimo

__generated_with = "0.21.1"
app = marimo.App(width="full")

with app.setup(hide_code=True):
    import os
    from datetime import datetime, UTC
    from llama_stack_provider_trustyai_garak.utils import _ensure_xdg_vars
    import marimo as mo
    import pandas as pd
    from pathlib import Path
    import json

    _ensure_xdg_vars()
    project_root = Path.cwd() / "automated-red-teaming" if Path.cwd().name == "trustyai-llm-demo" else Path.cwd()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Automated Red Teaming

    yada yada
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.outline(label="Table of Contents")
    return


@app.cell
def _():
    taxonomy_dataset_file = project_root / "resources/taxonomy.json"
    taxonomy_dataset = pd.DataFrame(json.loads(taxonomy_dataset_file.read_text()))
    taxonomy_dataset[["policy_concept", "concept_definition"]]
    return (taxonomy_dataset,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # SDG Hub
    Using SDG Hub we'll generate a dataset of harmful prompts based on the taxonomy in input
    """)
    return


@app.cell
def _(taxonomy_dataset):
    from sdg_hub import Flow

    sdg_flow = Flow.from_yaml(project_root / "resources/sdg-flow.yaml")

    # Configure the model
    attacker_model = "hosted_vllm/gemma-2-2b-it-abliterated"
    attacker_api_base = "http://localhost:8000/v1"

    sdg_flow.set_model_config(
        model=attacker_model,
        api_base=attacker_api_base,
        # api_key="EMPTY",
    )

    harmful_prompts_dataset = sdg_flow.generate(taxonomy_dataset, max_concurrency=10)
    harmful_prompts_dataset = harmful_prompts_dataset.dropna(subset=["prompt"])
    return (harmful_prompts_dataset,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Here's a view of the dataset that has been generated
    """)
    return


@app.cell
def _(harmful_prompts_dataset):
    harmful_prompts_dataset[["policy_concept", "prompt", "why_prompt_harmful", "why_prompt_targets_demographic", "why_prompt_matches_expertise"]]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Harmful prompts → Garak intents
    """)
    return


@app.cell(hide_code=True)
def _(harmful_prompts_dataset):
    from llama_stack_provider_trustyai_garak.intents import generate_intents_from_dataset

    # Delete all intents that are already present
    intent_path = Path(os.environ["XDG_DATA_HOME"]) / "garak" / "data" / "cas" / "intent_stubs"
    for intent_file in intent_path.glob("*.json"):
        intent_file.unlink()

    generate_intents_from_dataset(
        harmful_prompts_dataset,
        category_column_name="policy_concept",
        prompt_column_name="prompt",
        category_description_column_name="concept_definition",
        take_per_category=5
    )

    mo.accordion({f.name: json.loads(f.read_text()) for f in sorted(intent_path.glob("*.json"))})
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Run Garak
    """)
    return


@app.cell
def _():
    import garak.cli

    config_path = project_root / "resources/garak.yaml"
    garak.cli.main(["--config", str(config_path)])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Explore results
    Here's an embedded view of the HTML output that gets generated
    """)
    return


@app.cell(hide_code=True)
def _():
    from llama_stack_provider_trustyai_garak.result_utils import generate_art_report

    garak_runs = Path(os.environ["XDG_DATA_HOME"]) / "garak" / "garak_runs"
    reports = list(filter(os.path.isfile, garak_runs.glob("*.report.jsonl")))
    reports.sort(key=lambda x: os.path.getmtime(x))  # Sort by modification time
    report_path = reports[-1]  # Get the latest

    assert report_path.exists(), f"Report not found: {report_path}"

    report_content = report_path.read_text()
    html = generate_art_report(report_content) # Generate the HTML report based on the Garak output

    html_path = report_path.with_name(report_path.name.replace(".jsonl", ".html"))
    html_path.write_text(html)

    # Display the HTML in the notebook via iframe
    mo.plain(mo.iframe(html, height="800px"))
    return (report_content,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Here's a low level overview of the actual messages that have been sent to the target LLM
    """)
    return


@app.cell(hide_code=True)
def _():
    filter_by = mo.ui.dropdown(
        label="Filter by outcome:",
        options=["complied", "refused"],
        value="complied",
    )
    return (filter_by,)


@app.cell(hide_code=True)
def _(filter_by, report_content):
    from llama_stack_provider_trustyai_garak.result_utils import parse_jsonl, vega_data

    report_raw_data = vega_data(parse_jsonl(report_content))
    complied_rows = list(filter(lambda x: x["outcome"] == filter_by.value, report_raw_data))
    complied_rows = pd.DataFrame(complied_rows)

    def extract_target_model_reply(conversations):
        try:
            return conversations[0]["turns"][-1]["content"]["text"]
        except (IndexError, KeyError, TypeError):
            return None

    if complied_rows.empty:
        result = mo.callout(f"Garak evaluation doesn't contain any {filter_by.value} row", kind="warn")
    else:
        complied_rows["target_model_reply"] = complied_rows["conversations"].apply(extract_target_model_reply)
        result = complied_rows[["probe_name", "intent_name", "stub", "target_model_reply", "detector_results", "outcome"]]

    mo.vstack([filter_by, result], align="stretch", gap=0)
    return


@app.cell
def _():
    return


if __name__ == "__main__":
    app.run()
