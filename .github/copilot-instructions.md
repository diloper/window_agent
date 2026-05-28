# Project Guidelines

## Scope
This workspace is a Python-based YOLO dataset preparation project centered on `auto_prepare_dataset.py`.

## Working Style
- For Python requests, inspect the relevant workspace files before asking clarifying questions when the codebase can answer them.
- Prefer completing the task end-to-end when the request is actionable: explore, edit, and verify instead of stopping at a partial plan.
- Keep edits minimal and consistent with the current script-oriented style. Avoid unrelated refactors.
- When modifying Python files, avoid duplicate import statements; reuse existing imports and keep each module imported only once.
- State assumptions briefly only when they materially affect the result.

### 分支管理規範（Branching Policy）
- **所有程式碼修改前，必須先建立並切換到新分支，不可直接在 main 分支作業。**
		- 建議分支命名：`feature/日期-描述`（如：feature/20260528-fix-bug）
		- 建立分支指令：
			```bash
			git checkout main
			git pull
			git checkout -b feature/20260528-描述
			```
- 完成修改後，需經人工審查（PR/Code Review）才可合併回 main。
- 合併後，僅刪除本地剛合併的臨時分支（不可刪除 main，也不可預設刪除遠端分支）。
- 刪除分支前，請確認：
		1. 當前分支為 main
		2. 目標分支不是 main
		3. 目標分支已出現在 `git branch --merged main` 結果中
- 刪除指令：
	```bash
	git branch -d <branch>
	```
- 僅在使用者明確同意下，才可強制刪除（`-D`）。
- 執行 Git 指令時，請使用 Git Bash。

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

<skills>
Here is a list of skills that contain domain specific knowledge on a variety of topics.
Each skill comes with a description of the topic and a file path that contains the detailed instructions.
When a user asks you to perform a task that falls within the domain of a skill, use the 'read_file' tool to acquire the full instructions from the file URI.
<skill>
<name>auto-label-video</name>
<description>Use when user triggers auto-labeling workflow with patterns like "自動標註 XXX.mp4" or "autolabel XXX.mp4". Standardizes video frame extraction and SerpAPI-based class inference with minimal parameter entry.</description>
<file>.github\skills\auto-label-video\SKILL.md</file>
</skill>
</skills>
