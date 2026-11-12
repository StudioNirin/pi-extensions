# Changelog

## 0.1.0 - 2026-11-11

First packaging of the policy stack as one pi-package.

- `pi-workflow-modes`: per-session plan/ask/build selection, plan-file carve-out
  (writes only under `~/.pi/plans/` or `<cwd>/.plans/`), scout-only subagent
  dispatch in plan mode, and model-visible mode-transition notices.
- `pi-veto`: deny-only security floor for catastrophic commands and
  credential/policy writes, covering tool calls and `!cmd`, with an additive
  `floor.json` and no dialogs.
- `agents/`: the policy personas (build, worker, general-purpose, plan, ask,
  scout, Explore) deployed by `install.sh`.
- `extensions/pi-workflow-modes/tests/`: 8-scenario headless regression suite.
