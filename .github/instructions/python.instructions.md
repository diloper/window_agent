---
applyTo: "**/*.py"
---
# Python & Dataset Rules

- Avoid duplicate import statements; reuse existing imports and import each module only once.
- Canonical interpreter: the workspace `.venv` from `.vscode/settings.json` (`.venv\Scripts\python.exe`); terminals auto-activate it, so bare `python` resolves to it.
- For generic "功能測試" without a specified target, validate the changed Python files with `python -m py_compile <changed_file.py>`.
- For dataset-preparation work, inspect `auto_prepare_dataset.py`, `classes.txt`, `A/`, and `labels/` as needed; prefer the `prepare-colab-dataset` task for validation, else run `python auto_prepare_dataset.py` from the workspace root.
- After Python changes, report what was verified and what was not run.
