# Project Guidelines

## Scope
This workspace is a Python-based YOLO dataset preparation and screen-automation project. It contains multiple scripts (dataset preparation, recording, auto-labeling, ad skipping); no single file is the sole core.

## Working Style
- For Python requests, inspect the relevant workspace files before asking clarifying questions when the codebase can answer them.
- Prefer completing the task end-to-end when the request is actionable: explore, edit, and verify instead of stopping at a partial plan.
- Keep edits minimal and consistent with the current script-oriented style. Avoid unrelated refactors.
- When modifying Python files, avoid duplicate import statements; reuse existing imports and keep each module imported only once.
- State assumptions briefly only when they materially affect the result.


### Branching Policy
- **Never modify code directly on `main` or `master`. Select the working branch based on the current branch:**
		- If the current branch is already a non-`main`/`master` branch (e.g. an existing `feature/`, `hotfix/`, or `bugfix/` branch), make modifications directly on that existing branch — do NOT create an additional branch.
		- Only when the current branch is `main` or `master`: create and switch to a new branch before any code modification.
		- Recommended branch naming: one of the allowed prefixes `feature/`, `hotfix/`, or `bugfix/` followed by `YYYYMMDD-description` (e.g., `feature/20260528-fix-bug`). These three prefixes are the only ones accepted by `scripts/policy_check.py`.
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

- After code changes, automatically run the relevant test or validation command.
- If test or runtime errors are caused by the change, fix them and re-run verification before handoff.
- During functional testing, if errors are detected, automatically attempt fixes and re-run the same test until it passes or a clear blocker is identified.

## Project Context
- Start with `README.md` for workflow and expected inputs and outputs.
- For dataset preparation changes, inspect `auto_prepare_dataset.py`, `classes.txt`, `A/`, and `labels/` as needed.
- This workspace runs on Windows and has a task for dataset verification.

## Build And Test
- Canonical Python interpreter: the workspace `.venv` declared in `.vscode/settings.json` (`.venv\Scripts\python.exe`). Terminals auto-activate it, so bare `python` resolves to the `.venv` interpreter.
- For generic requests like "功能測試" without a specified target, validate the Python files changed by the current work using `python -m py_compile <changed_file.py>`.
- Prefer the existing `prepare-colab-dataset` task for validating dataset preparation behavior.
- If a task is not suitable, use `python auto_prepare_dataset.py` from the workspace root.
- After Python changes, report what was verified and what was not run.

## Terminal / Shell Conventions
- This workspace runs on **Windows** with **PowerShell** as the default integrated terminal, as declared in `.vscode/settings.json` (`terminal.integrated.defaultProfile.windows: "PowerShell"`).
- All terminal commands MUST use PowerShell syntax by default:
	- Chain commands with `;` (never `&&` or `||`).
	- Reference environment variables as `$env:NAME` (never `$NAME` or `export NAME=`).
	- Use PowerShell cmdlets: `Remove-Item`, `Copy-Item`, `New-Item`, `Get-Content`, `Get-ChildItem`, `Test-Path` (avoid `rm`, `cp`, `cat`, `ls`, `touch` as canonical forms).
	- Avoid bash-only constructs: `2>/dev/null`, backtick line-continuation, heredocs (`<<EOF`), and POSIX globbing semantics.
- Git Bash is optional and used ONLY when bash-style piping is required (e.g. `grep`/`xargs`); do not assume it as the default shell.
- The `.venv` auto-activates in new terminals, so bare `python` resolves to `.venv\Scripts\python.exe` — do not prefix commands with an explicit interpreter path unless necessary.

## Output Expectations
- Default to a complete answer with implementation summary and validation, not just the next suggested step.
- Include the concrete verification command when changes affect runtime behavior.

## Documentation Policy
- Do not automatically create any documentation files (including `.md` reports, guides, summaries, implementation reports, change logs, etc.) unless the user **explicitly requests** it in their instruction.
- "Explicitly requests" means the user's message shows a clear intent such as "write a doc / produce documentation / write a report / generate doc / update README".
- By default, reply with the implementation summary and verification results as text in the conversation only; do not persist them to files.
- If you believe a document would help maintenance, you may suggest it verbally, but only create it after the user agrees.
- **Exception (Sanctioned)**: Progress-tracking files under `docs/progress/` are exempt from this restriction. Per the **Progress Tracking Policy** below, the agent should maintain these files automatically during autopilot implementation (plan mode persists decisions to session memory only). The "no md unless explicitly requested" rule still applies to all other locations.

## Progress Tracking Policy
- Maintain English-language progress records under `docs/progress/`. Plan mode captures
  confirmed requirements/decisions in session memory only; the files below are written and
  updated during autopilot implementation.
- `docs/progress/INDEX.md` is the single source of truth: one row per feature/topic
  with Phase, Status, Branch, Last Updated, and a link to its details file.
- For each feature/topic, copy `docs/progress/_TEMPLATE.md` to `docs/progress/feature-<slug>.md`
  (lowercase-hyphenated slug matching the INDEX link).
- Plan mode: persist confirmed requirements and decisions to session memory only
  (no `docs/progress` writes).
- Autopilot: create the feature file from `_TEMPLATE.md` and register it in `INDEX.md`,
  then append Implementation Progress and Verification results to the feature file and
  update the `INDEX.md` row's Phase / Status / Last Updated as work advances.
- Consistency: before every handoff, reconcile the feature file and `INDEX.md` against the
  actual repository state (changed files, commands run, verification outcome).
- Split rule: keep one file per feature/topic; start a new file for a distinct topic rather
  than letting a single file grow to cover unrelated work.
- All progress content must be in English.

## Enforcement Contract
- Treat this file as the single source of truth for workspace behavior across all models.
- Non-negotiable rules:
		- Do not modify code on `main` or `master`. If the current branch is already a non-`main`/`master` branch, work directly on it; only when on `main`/`master` create a new branch first using one of the allowed prefixes `feature/`, `hotfix/`, or `bugfix/` (e.g. `feature/YYYYMMDD-description`).
		- Do not use destructive git commands (`git reset --hard`, `git checkout --`) unless explicitly requested. `git reset --mixed`/`--soft` are allowed but use them with caution.
	- Generate all terminal commands using PowerShell syntax per the **Terminal / Shell Conventions** section (`;` chaining, `$env:NAME`, PowerShell cmdlets). Never emit bash-only syntax (`&&`, `||`, `2>/dev/null`, `export`) unless the user explicitly switches to Git Bash. This rule applies uniformly to every model.
	- Do not create documentation files (`.md` reports, guides, summaries) unless the user explicitly requests them, **except** progress-tracking files under `docs/progress/`, which the agent maintains automatically per the Progress Tracking Policy.
		- Maintain `docs/progress/` records (feature files + `INDEX.md`) during autopilot implementation (plan mode persists to session memory), and keep them consistent with the actual repository state before handoff.
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
