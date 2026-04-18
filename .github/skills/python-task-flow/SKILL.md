---
name: python-task-flow
description: "Use when handling Python work such as bugfix, debugging, refactor, script update, dataset pipeline, YOLO preprocessing, CLI scripts, tests, pandas, typing, or code cleanup. Also use for Chinese requests like Python 除錯, 重構, 腳本修改, 資料處理, 減少互動, 一次完成."
argument-hint: "Describe the Python task, target file, and expected behavior."
user-invocable: true
---

# Python Task Flow

## Purpose
Reduce back-and-forth on Python tasks by gathering context first, making the smallest viable change, and returning verification steps by default.

## When To Use
- Fix a Python bug or runtime error
- Update a script or CLI workflow
- Refactor Python code without changing intent
- Add or adjust tests for Python code
- Modify data processing, dataset preparation, or YOLO-related scripts
- Handle requests where the user wants fewer clarification rounds and a more complete first pass

## Default Procedure
1. Inspect the local context before asking questions.
   - Read the task-relevant Python entry points first.
   - Check `README.md` and any nearby config or task definitions.
   - Look for existing validation commands before inventing new ones.
2. Decide whether the task is already actionable.
   - If the expected behavior can be inferred from the codebase, proceed without asking for more detail.
   - Ask only when a missing requirement would materially change the implementation.
3. Make focused edits.
   - Solve the root cause instead of patching symptoms when the cause is clear.
   - Avoid unrelated cleanup.
4. Validate by default.
   - Run the existing task, test, or script when practical.
   - If validation cannot be run, say so explicitly and provide the exact command.
5. Return a complete handoff.
   - Summarize the change.
   - State what was verified.
   - Mention any remaining assumption or risk only if it matters.

## Python-Specific Heuristics
- Prefer reading the main script and README before proposing dataset or pipeline changes.
- Follow the current project structure unless the request explicitly asks for a redesign.
- Reuse existing commands, interpreter paths, and tasks when available.
- For data pipeline work, verify inputs, outputs, and file naming assumptions.

## Output Shape
- Understanding in one or two sentences
- Implemented change or concrete next action
- Verification command or result
- Residual risk only if needed
