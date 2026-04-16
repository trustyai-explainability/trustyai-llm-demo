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

    This notebook demonstrates an end-to-end automated red teaming pipeline for LLM safety evaluation.

    We start with a **harm taxonomy** that defines categories of unsafe behavior (e.g., illegal activity, fraud).
    Using **SDG Hub**, we generate diverse adversarial prompts that attempt to elicit harmful responses.
    These prompts are then fed into **Garak**, a security testing framework that probes the target LLM.

    The final output is an interactive report showing which attacks succeeded or failed.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.outline(label="Table of Contents")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## LLMs setup

    Configure the two models used in this pipeline:

    - **Challenger LLM** — Generates adversarial prompts (via SDG Hub) and judges target responses (via Garak detectors)
    - **Target LLM** — The model under test that will be probed for unsafe behavior
    """)
    return


@app.cell(hide_code=True)
def _():
    challenger_model = mo.ui.text(label="Challenger LLM model:", value="gemma-2-2b-it-abliterated", full_width=True)
    challenger_api_base = mo.ui.text(label="Challenger LLM API base:", value="http://localhost:8000/v1", full_width=True)
    challenger_api_key = mo.ui.text(label="Challenger LLM API key:", value="sk-1234", full_width=True)

    mo.vstack([challenger_model, challenger_api_base, challenger_api_key])
    return challenger_api_base, challenger_api_key, challenger_model


@app.cell(hide_code=True)
def _():
    target_name = mo.ui.text(label="Target system:", value="openai/gpt-oss-20b", full_width=True)
    target_api_base = mo.ui.text(label="Target system API base:", value="http://localhost:8000/v1", full_width=True)
    target_api_key = mo.ui.text(label="Target system API key:", value="sk-1234", full_width=True)

    mo.vstack([target_name, target_api_base, target_api_key])
    return target_api_base, target_api_key, target_name


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

    SDG Hub is a synthetic data generation framework that creates adversarial prompts from a taxonomy.

    The flow samples across multiple dimensions: demographics, expertise level, geography, and language style.
    This produces realistic attack scenarios that mimic how real users might attempt to misuse the model.

    Each taxonomy category (e.g., "Fraud") gets expanded into multiple prompt variations.
    """)
    return


@app.cell(hide_code=True)
def _():
    num_samples = mo.ui.number(label="Number of samples per category:", value=10, start=1, stop=100)

    num_samples
    return (num_samples,)


@app.cell
def _(
    challenger_api_base,
    challenger_api_key,
    challenger_model,
    num_samples,
    taxonomy_dataset,
):
    from sdg_hub import Flow

    sdg_flow = Flow.from_yaml(project_root / "resources/sdg-flow.yaml")

    custom_cfg = sdg_flow.blocks[0].get_config()
    custom_cfg["num_samples"] = num_samples.value
    sdg_flow.blocks[0] = sdg_flow.blocks[0].from_config(custom_cfg)

    sdg_flow.set_model_config(
        model="hosted_vllm/" + challenger_model.value,
        api_base=challenger_api_base.value,
        api_key=challenger_api_key.value,
    )

    harmful_prompts_dataset = sdg_flow.generate(taxonomy_dataset, max_concurrency=10)
    harmful_prompts_dataset = harmful_prompts_dataset.dropna(subset=["prompt"])
    return (harmful_prompts_dataset,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    Below is the generated dataset of adversarial prompts.

    Each row includes the prompt text and metadata explaining why it targets a specific harm category.
    """)
    return


@app.cell
def _(harmful_prompts_dataset):
    harmful_prompts_dataset[["policy_concept", "prompt", "why_prompt_harmful", "why_prompt_targets_demographic", "why_prompt_matches_expertise"]]
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Harmful Prompts → Garak Intents

    Garak uses "intents" to define what harmful behavior it should test for.
    Here we convert our SDG-generated prompts into Garak's intent format.

    Each intent file contains prompts grouped by harm category, ready for security testing.
    """)
    return


@app.cell(hide_code=True)
def _(harmful_prompts_dataset, num_samples):
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
        take_per_category=num_samples.value
    )

    mo.accordion({f.name: json.loads(f.read_text()) for f in sorted(intent_path.glob("*.json"))})
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Run Garak

    Garak is an LLM vulnerability scanner that probes models for unsafe behavior.

    It applies multiple attack strategies (probes) to each intent and uses a judge model to classify responses.
    Responses are categorized as: **complied**, **rejected**, **alternative**, or **other**.
    """)
    return


@app.cell(hide_code=True)
def _():
    max_dan_samples = mo.ui.number(label="Max DAN samples per intent:", value=5, start=1, stop=100)
    max_dan_samples
    return (max_dan_samples,)


@app.cell(hide_code=True)
def _(
    challenger_api_base,
    challenger_model,
    max_dan_samples,
    target_api_base,
    target_api_key,
    target_name,
):
    import garak.cli
    import yaml
    import tempfile

    # Load base config
    config_path = project_root / "resources/garak.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Wire target LLM
    config["plugins"]["target_name"] = target_name.value
    config["plugins"]["generators"]["openai"]["OpenAICompatible"]["uri"] = target_api_base.value

    # Wire detector (challenger) LLM
    config["plugins"]["detectors"]["judge"]["detector_model_name"] = challenger_model.value
    config["plugins"]["detectors"]["judge"]["detector_model_config"]["uri"] = challenger_api_base.value

    # Wire TAP probe models (also use challenger)
    tap_cfg = config["plugins"]["probes"]["tap"]["TAPIntent"]
    tap_cfg["attack_model_name"] = challenger_model.value
    tap_cfg["attack_model_config"]["uri"] = challenger_api_base.value
    tap_cfg["evaluator_model_name"] = challenger_model.value
    tap_cfg["evaluator_model_config"]["uri"] = challenger_api_base.value

    # Wire SPO probe settings
    config["plugins"]["probes"]["spo"]["SPOIntent"]["max_dan_samples"] = max_dan_samples.value

    # Set API keys
    os.environ["OPENAICOMPATIBLE_API_KEY"] = target_api_key.value

    # Write updated config and run
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
        yaml.dump(config, tmp)
        tmp_config_path = tmp.name

    garak.cli.main(["--config", tmp_config_path])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Explore Results

    The interactive report below visualizes Garak's findings.

    It shows pass/fail rates across harm categories and attack strategies.
    Use this to identify which types of attacks your model is most vulnerable to.
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
    The table below shows the raw conversation data from Garak's evaluation.

    You can filter by outcome to inspect specific cases where the model complied or refused.
    This helps understand exactly how the model responded to each adversarial prompt.
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
