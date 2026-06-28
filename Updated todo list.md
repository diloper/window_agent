Updated todo list

I'll analyze the .github directory contents for contradictions and improvement opportunities. Let me explore the structure and read the key files. 

Read [](file:///r%3A/SAM/.github)

Read [](file:///r%3A/SAM/.github/skills)

Read [](file:///r%3A/SAM/.github/workflows)

Read [](file:///r%3A/SAM/.github/copilot-instructions.md)

Read [](file:///r%3A/SAM/.github/workflows/policy-check.yml)

Now let me read the policy check script and the skill files to compare documented rules against enforced rules.  

Read [](file:///r%3A/SAM/scripts/policy_check.py)

Let me read the skill files to check for workflow conflicts.    

Read skill [python-task-flow](file:///r%3A/SAM/.github/skills/python-task-flow/SKILL.md?vscodeLinkType%3Dskill)

Read skill [auto-label-video](file:///r%3A/SAM/.github/skills/auto-label-video/SKILL.md?vscodeLinkType%3Dskill)

Searched for files matching `**/docs/progress/**`, 4 matches

I've reviewed all .github governance files plus the enforcement script. Here's the analysis.

## Files reviewed
- copilot-instructions.md (Branching, Build/Test, Documentation, Progress Tracking, Enforcement Contract)
- policy-check.yml
- policy_check.py
- Skills: python-task-flow, auto-label-video, greeting, image-serpapi-analysis
- Confirmed progress (INDEX, _TEMPLATE, feature file) exists.

## Contradictions / logical conflicts

**1. Branch-prefix rules disagree (doc vs. enforcement)**
- Instructions say *"always use `feature/YYYYMMDD-description`"* and only ever mention `feature/`.
- But policy_check.py allows `feature/`, `hotfix/`, `bugfix/`, and the policy-check.yml allows the same three.
- Neither enforcer validates the `YYYYMMDD` date the docs "require." → The single-source-of-truth claim in the Enforcement Contract is violated: three prefixes are allowed but only one is documented.

**2. Plan-mode vs. Progress Tracking Policy is unsatisfiable**
- Progress Tracking Policy says *"Plan mode: write the confirmed Requirements and Decisions into the feature file"* and register it in INDEX.md.
- But Plan mode only permits the memory tool — it **cannot write repo files**. So the policy instructs an action the mode forbids. (This bit us this session.) → Either persist to memory in Plan mode, or only write progress during autopilot.

**3. "Always use Git Bash" conflicts with the actual environment**
- The workspace default is PowerShell, and `bash` resolves to WSL (not installed). The rule gives no Git Bash path, so plain `bash -c` fails. → Plain `git` works fine in PowerShell; Git Bash is only needed for `grep`/`xargs`-style piping. The blanket rule causes avoidable failures.

**4. Python interpreter is inconsistent**
- Instructions use bare `python` (`python -m py_compile ...`).
- SKILL.md hardcodes `C:\Users\User\miniconda3\python.exe`.
- python-task-flow says *"reuse existing interpreter paths"* — ambiguous. → No canonical interpreter; risks wrong-env or "python not found."

**5. "Central file" vs. verification baseline mismatch**
- Scope calls the project *"centered on auto_prepare_dataset.py"*, but the mandated baseline check and default "功能測試" target are screen_event_recorder.py. → The non-negotiable verification never compiles the file declared central, and CI only ever compiles screen_event_recorder.py.

**6. Duplicated branch logic can drift**
- CI re-implements branch validation as an inline regex *and* policy_check.py has `ALLOWED_BRANCH_PREFIXES`. Two copies → guaranteed eventual drift.

## Gaps (not contradictions, but missing)
- **History rewrite / force-push** unmentioned despite a PR-branch workflow (no rule for `git rebase`, commit deletion, `push --force`, or "never force-push main").
- `git reset --mixed/--soft` not addressed — only `--hard` is called out as destructive.
- Verification only covers one file; changed Python scripts aren't compiled/linted.

## Suggested better workflow to adopt
1. **One source of truth for branches**: list `hotfix/`/`bugfix/` in the instructions (or drop them from the checker), and have CI call policy_check.py *without* `--skip-branch-check` instead of its own regex.
2. **Fix the Plan-mode clause**: "Plan mode → persist to memory; write progress files during autopilot only."
3. **Relax the Git Bash rule**: "Use plain `git` in PowerShell; use Git Bash only for bash piping (`grep`/`xargs`), invoking `C:\Program Files\Git\bin\bash.exe`."
4. **Define one interpreter** referenced everywhere (replace the hardcoded miniconda path in the skill, or declare it canonical).
5. **Broaden verification**: `py_compile` (or `ruff`) over *changed* Python files, not just screen_event_recorder.py; consider adding the central auto_prepare_dataset.py.
6. **Add a Git-safety section**: never force-push `main`; history rewrite / force-push require explicit approval; prefer `--mixed`/`--soft` over `--hard`.

These are analysis-only findings — I haven't changed any files. Want me to implement a specific subset (e.g., items 1–3) on a feature branch?

Created 4 todos