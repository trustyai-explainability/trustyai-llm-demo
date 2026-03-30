# Automated Red Teaming

Interactive [marimo](https://marimo.io/) notebook for automated LLM security testing.

## What it does

1. **Load harm taxonomy** — Reads predefined harm categories (fraud, illegal activity, etc.) from `resources/taxonomy.json`
2. **Generate adversarial prompts** — Uses SDG Hub to expand each category into diverse attack prompts, varying demographics, expertise, geography, and language style
3. **Convert to Garak intents** — Transforms generated prompts into Garak's intent format for security probing
4. **Run Garak** — Executes vulnerability scans using multiple attack strategies (TAP, SPO probes) against the target LLM
5. **Visualize results** — Displays pass/fail rates by category and lets you inspect individual responses

## Quickstart

Environment variables:
```dotenv
OPENAI_API_KEY=xyz
OPENAICOMPATIBLE_API_KEY=xyz
XDG_DATA_HOME=/path/to/store/garak/results
```

```bash
uv venv .venv
uv sync
source .venv/bin/activate
marimo run notebook-run-locally.py
```

## Configuration

The notebook exposes UI controls for:

- **Challenger LLM** — Model used for prompt generation and response judging
- **Target LLM** — Model under test
- **Samples per category** — Number of adversarial prompts to generate
- **Max DAN samples** — Limit for jailbreak attempts per intent

## Key dependencies

- `sdg_hub` — Synthetic data generation for adversarial prompts
- `garak` — LLM vulnerability scanner
- `llama_stack_provider_trustyai_garak` — Intent generation and result parsing utilities