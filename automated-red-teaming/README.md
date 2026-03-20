# Automated Red Teaming

This uses [marimo](https://marimo.io/) an alternative to jupyter notebooks.

## Quickstart

You'll need the following env variables:
```dotenv
OPENAI_API_KEY=xyz
OPENAICOMPATIBLE_API_KEY=xyz
# Garak will use this to store runs results
XDG_DATA_HOME=/a/valid/path
```

```bash
uv venv .venv
uv sync
source .venv/bin/activate
marimo run main.py
```