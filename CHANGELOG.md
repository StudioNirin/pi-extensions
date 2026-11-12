# Changelog

## 0.2.0 - 2026-11-12

- `pi-opencode-free-sidecar`: OpenCode Zen free models for any pi host.
  Vendores `@rabden/pi-opencode-zen` 0.3.0 (MIT, `vendor/`, byte-identical)
  and adds a Bun transport relay so Node-hosted pi (PiChamber's session
  daemon) passes the free-tier client-class check: Zen accepts Bun-built
  clients and answers Node/undici clients with `429 FreeUsageLimitError`
  regardless of request shape (evidence table in the extension README).
  Relay lifecycle is on-demand (spawn, idle self-exit, guarded restart),
  writes to it are token-gated, and `models.json` seeding got a new
  `install.sh` step. Replaces `npm:@rabden/pi-opencode-zen`; the two must
  not coexist.
- Test gate now spans extension dirs: `run.sh` also runs
  `../../*/tests/*.py` in scenario order; new scenario
  `10-opencode-free-sidecar.py` covers relay auth/idle/single-instance and
  the provider load contract, with one live Zen round trip.

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
