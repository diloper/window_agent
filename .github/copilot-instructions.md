# Project Guidelines

## Scope
This workspace is a Python-based YOLO dataset preparation and screen-automation project. It contains multiple scripts (dataset preparation, recording, auto-labeling, ad skipping); no single file is the sole core.

## Working Style
- Inspect relevant workspace files before asking clarifying questions when the codebase can answer them.
- Prefer completing the task end-to-end when the request is actionable: explore, edit, and verify instead of stopping at a partial plan.
- Keep edits minimal and consistent with the current script-oriented style. Avoid unrelated refactors.
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
- This workspace runs on Windows and has a task for dataset verification.
- Python and dataset-specific rules (interpreter, `py_compile`, dataset files, validation tasks) live in `.github/instructions/python.instructions.md` (auto-applies to `*.py`).

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
- **Exception (Sanctioned)**: Progress-tracking files under `docs/progress/` are exempt from this restriction. Per the **Progress Tracking** section, the agent maintains these files automatically during autopilot implementation (plan mode persists decisions to session memory only). The "no md unless explicitly requested" rule still applies to all other locations.

## Progress Tracking
- During autopilot implementation, maintain English progress records under `docs/progress/` (`INDEX.md` + per-feature files copied from `_TEMPLATE.md`). Plan mode persists confirmed requirements/decisions to session memory only.
- Full workflow is in `.github/instructions/progress-tracking.instructions.md` (auto-applies under `docs/progress/`); read it before writing progress files.

## Enforcement Contract
- Treat this file as the single source of truth for workspace behavior across all models.
- Non-negotiable rules (defined in the sections above; binding for every model):
	- The Branching, Terminal / Shell, Documentation, and Progress Tracking policies above are mandatory.
	- Never use destructive git commands (`git reset --hard`, `git checkout --`) unless explicitly requested. `git reset --mixed`/`--soft` are allowed but used with caution.
	- Always report which verification command was run and whether it passed.
- Operational guardrails:
	- Local hooks run `scripts/policy_check.py` at `pre-commit` and `pre-push`.
	- Team CI should run the same policy check in pull requests.

