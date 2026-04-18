# Project Guidelines

## Scope
This workspace is a Python-based YOLO dataset preparation project centered on `auto_prepare_dataset.py`.

## Working Style
- For Python requests, inspect the relevant workspace files before asking clarifying questions when the codebase can answer them.
- Prefer completing the task end-to-end when the request is actionable: explore, edit, and verify instead of stopping at a partial plan.
- Keep edits minimal and consistent with the current script-oriented style. Avoid unrelated refactors.
- State assumptions briefly only when they materially affect the result.
- For any code change, create and work on a temporary branch first.
- Never merge into `main` automatically; merge only after explicit human approval.
- When executing Git commands, use Git Bash.
- After code changes, automatically run the relevant test or validation command.
- If test or runtime errors are caused by the change, fix them and re-run verification before handoff.
- During functional testing, if errors are detected, automatically attempt fixes and re-run the same test until it passes or a clear blocker is identified.

## Project Context
- Start with `README.md` for workflow and expected inputs and outputs.
- For dataset preparation changes, inspect `auto_prepare_dataset.py`, `classes.txt`, `A/`, and `labels/` as needed.
- This workspace runs on Windows and has a task for dataset verification.

## Build And Test
- Prefer the existing `prepare-colab-dataset` task for validating dataset preparation behavior.
- If a task is not suitable, use `C:\Users\User\miniconda3\python.exe auto_prepare_dataset.py` from the workspace root.
- After Python changes, report what was verified and what was not run.

## Output Expectations
- Default to a complete answer with implementation summary and validation, not just the next suggested step.
- Include the concrete verification command when changes affect runtime behavior.
