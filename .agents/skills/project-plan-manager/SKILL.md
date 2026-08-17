---
name: project-plan-manager
description: Keep PROJECT_PLAN.md synchronized with the actual Chabot repository state. Use for every implementation, fix, refactor, configuration, infrastructure, deployment, test, or roadmap change in this repository, and whenever reporting project progress or deciding future work. Read the plan before acting and update it after completed work or changed decisions.
---

# Project Plan Manager

Use `PROJECT_PLAN.md` as the authoritative progress and roadmap ledger for this repository.

## Required workflow

1. Locate the repository root and read `PROJECT_PLAN.md` completely before changing code, configuration, infrastructure, tests, or documentation.
2. Follow any applicable repository instructions that are already available.
3. Identify which phase, task, completion condition, risk, or decision the requested work affects.
4. Inspect the implementation and current environment. Do not accept an existing checklist or summary as proof that work is complete.
5. Perform the requested work and verify it in proportion to risk.
6. Before finishing, inspect the actual diff and verification results, then update `PROJECT_PLAN.md`.
7. In the final response, state whether `PROJECT_PLAN.md` was updated and summarize the affected progress item.

## Updating PROJECT_PLAN.md

- Set the update date to the current date when making a material plan change.
- Mark `[x]` only when the stated outcome is implemented and its required verification succeeded.
- For partially completed work, explicitly separate `コード実装済み`, `ローカル検証済み`, `E2E未確認`, and `本番未反映` as applicable.
- Add newly discovered blockers, risks, follow-up work, and changed decisions to the appropriate P0/P1/phase section.
- Move postponed work to `[保留]`; do not leave it described as current work.
- Keep production state distinct from local, uncommitted, staging, and test-mode state.
- Preserve stable identifiers such as phase names and task headings when they remain useful.
- Keep secrets and credential values out of the plan.
- Keep the plan concise enough to scan, removing or correcting stale statements that contradict the repository.
- Treat `app/core/pricing.py` as the source of truth for plan limits unless the user explicitly changes that decision.

## Evidence rules

- Use code inspection, tests, command output, deployment state, or external service state as evidence.
- Record failed or unavailable verification honestly; do not convert implementation into completion merely because syntax checks pass.
- Do not claim deployment, Firestore initialization, Stripe configuration, or LINE E2E success without checking the relevant environment.
- When a command cannot run because of tooling or environment constraints, record the exact remaining verification task.

## When not to edit the plan

For a purely explanatory or read-only request that creates no new decision and changes no project state, read the plan for context but do not manufacture a plan change. State that no update was necessary.

## Completion checklist

Before returning the final response, confirm:

- [ ] `PROJECT_PLAN.md` was read before work.
- [ ] The actual diff and relevant status were inspected.
- [ ] Verification results were captured accurately.
- [ ] Completed, partial, blocked, and postponed work were labeled correctly.
- [ ] `PROJECT_PLAN.md` was updated if implementation or plans changed.
- [ ] The final response mentions the plan update.
