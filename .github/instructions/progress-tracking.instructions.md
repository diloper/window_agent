---
applyTo: "docs/progress/**"
---
# Progress Tracking Workflow

- Maintain English-language progress records under `docs/progress/`.
- `docs/progress/INDEX.md` is the single source of truth: one row per feature/topic with Phase, Status, Branch, Last Updated, and a link to its details file.
- For each feature/topic, copy `docs/progress/_TEMPLATE.md` to `docs/progress/feature-<slug>.md` (lowercase-hyphenated slug matching the INDEX link).
- Plan mode: persist confirmed requirements and decisions to session memory only (no `docs/progress` writes).
- Autopilot: create the feature file from `_TEMPLATE.md`, register it in `INDEX.md`, then append Implementation Progress and Verification results to the feature file and update the `INDEX.md` row's Phase / Status / Last Updated as work advances.
- Before every handoff, reconcile the feature file and `INDEX.md` against the actual repository state (changed files, commands run, verification outcome).
- Keep one file per feature/topic; start a new file for a distinct topic rather than letting one file cover unrelated work.
- All progress content must be in English.
