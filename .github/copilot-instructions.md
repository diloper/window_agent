# Project Guidelines

## Scope
This workspace is a Python-based YOLO dataset preparation project centered on `auto_prepare_dataset.py`.

## Working Style
- For Python requests, inspect the relevant workspace files before asking clarifying questions when the codebase can answer them.
- Prefer completing the task end-to-end when the request is actionable: explore, edit, and verify instead of stopping at a partial plan.
- Keep edits minimal and consistent with the current script-oriented style. Avoid unrelated refactors.
- When modifying Python files, avoid duplicate import statements; reuse existing imports and keep each module imported only once.
- State assumptions briefly only when they materially affect the result.


### Branching Policy
- **Before any code modification, you must create and switch to a new branch. Never work directly on the main branch.**
		- Recommended branch naming: `feature/YYYYMMDD-description` (e.g., feature/20260528-fix-bug)
		- Branch creation commands:
			```bash
			git checkout main
			git pull
			git checkout -b feature/20260528-description
			```
- After completing your changes, submit them for manual review (PR/Code Review) before merging back to main.
- After merging, only delete the just-merged local temporary branch (never delete main, and do not delete remote branches by default).
- Before deleting a branch, ensure all of the following:
		1. You are currently on the main branch
		2. The target branch is not main
		3. The target branch appears in the output of `git branch --merged main`
- Branch deletion command:
	```bash
	git branch -d <branch>
	```
- Only use force delete (`-D`) with explicit user approval.
- Always use Git Bash for Git commands.

- After code changes, automatically run the relevant test or validation command.
- If test or runtime errors are caused by the change, fix them and re-run verification before handoff.
- During functional testing, if errors are detected, automatically attempt fixes and re-run the same test until it passes or a clear blocker is identified.

## Project Context
- Start with `README.md` for workflow and expected inputs and outputs.
- For dataset preparation changes, inspect `auto_prepare_dataset.py`, `classes.txt`, `A/`, and `labels/` as needed.
- This workspace runs on Windows and has a task for dataset verification.

## Build And Test
- For generic requests like "功能測試" without a specified target, default to validating `screen_event_recorder.py` first.
- For `screen_event_recorder.py` validation, prefer `python -m py_compile screen_event_recorder.py` as the baseline check.
- Prefer the existing `prepare-colab-dataset` task for validating dataset preparation behavior.
- If a task is not suitable, use `python auto_prepare_dataset.py` from the workspace root.
- After Python changes, report what was verified and what was not run.

## Output Expectations
- Default to a complete answer with implementation summary and validation, not just the next suggested step.
- Include the concrete verification command when changes affect runtime behavior.

## Enforcement Contract
- Treat this file as the single source of truth for workspace behavior across all models.
- Non-negotiable rules:
	- Do not modify code on `main` or `master`; always use `feature/YYYYMMDD-description` style branches.
	- Run baseline verification after Python-related changes. At minimum, run `python -m py_compile screen_event_recorder.py`.
	- Do not use destructive git commands (`git reset --hard`, `git checkout --`) unless explicitly requested.
	- Report which verification command was run and whether it passed.
- Operational guardrails:
	- Local hooks run `scripts/policy_check.py` at `pre-commit` and `pre-push`.
	- Team CI should run the same policy check in pull requests.

<skills>
Here is a list of skills that contain domain specific knowledge on a variety of topics.
Each skill comes with a description of the topic and a file path that contains the detailed instructions.
When a user asks you to perform a task that falls within the domain of a skill, use the 'read_file' tool to acquire the full instructions from the file URI.
<skill>
<name>auto-label-video</name>
<description>Use when user triggers auto-labeling workflow with patterns like "自動標註 XXX.mp4" or "autolabel XXX.mp4". Standardizes video frame extraction and SerpAPI-based class inference with minimal parameter entry.</description>
<file>.github\skills\auto-label-video\SKILL.md</file>
</skill>
<skill>
<name>python-task-flow</name>
<description>Use for Python work such as debugging, refactoring, script updates, dataset processing, and end-to-end implementation plus validation.</description>
<file>.github\skills\python-task-flow\SKILL.md</file>
</skill>
<skill>
<name>greeting</name>
<description>Use when the user greets (hello, hi, 哈囉) and provide a brief response in the same language.</description>
<file>.github\skills\greeting\SKILL.md</file>
</skill>
<skill>
<name>image-serpapi-analysis</name>
<description>Use when the task requires analyzing an image with SerpApi image search results and structured interpretation.</description>
<file>.github\skills\image-serpapi-analysis\SKILL.md</file>
</skill>
</skills>
