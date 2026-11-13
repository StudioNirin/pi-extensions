# pi-extensions

One **pi-package** carrying the extension stack that gives every pi runtime
(the CLI TUI and PiChamber) the same policy behaviour:

| Extension | Role |
| --- | --- |
| [`pi-workflow-modes`](extensions/pi-workflow-modes/README.md) | Per-session **plan / ask / build** modes: selection, the plan-file carve-out, Explore-only subagent dispatch, and model-visible mode transitions. |
| [`pi-veto`](extensions/pi-veto/README.md) | The **deny-only security floor**: catastrophic commands and credential/policy writes can never run, ask, or be allowed, including from `!cmd`. |

Policy is layered, one authority per concern:

```
pi-veto          hard denies, no dialogs, agent-immune      (this repo)
agent files      ask catalog per mode                       (agents/)
pi-workflow-modes mode selection + carve-out enforcement    (this repo)
pi-permission-system  asks, path rules, dialogs             (@gotgenes/pi-permission-system)
```

None of these fork pi-permission-system; enforcement stays separate from any
future UI (`pi-policy-console`).

## Layout

```
extensions/pi-workflow-modes/   mode selection, carve-out blocker, tests/
extensions/pi-veto/             deny-only floor + floor.schema.json
agents/                         generic example personas (build,
                                general-purpose, plan, ask, Explore)
install.sh                      register the package + seed agents/
```

The `agents/*.md` files are not a pi-package resource: `pi-permission-system`
reads their `permission:` frontmatter and `pi-subagents` reads their tool
lists, both from `~/.pi/agent/agents/`.

## Install

```sh
./install.sh          # seed personas only where none exist
./install.sh --force  # overwrite deployed personas with the examples here
```

That removes any loose copies of the two extensions from
`~/.pi/agent/extensions/` (duplicate tool names are fatal in pi), seeds the
personas, and runs `pi install <this repo>`. A local source is loaded from the
path without copying, so edits here are live after `/reload` or a restart.

`install.sh` also keeps this package first in `settings.json`, because load
order decides which handler sees a tool call first (see the load-order note in
`extensions/pi-workflow-modes/README.md`). If you run `pi update --extensions`
or edit `settings.json` by hand, re-run `install.sh` or confirm the order is
still ours, then pps.

## Personalize

The personas in this repo are **generic examples**, not a full policy you should
adopt unchanged. Two things are meant to be edited in your deployed copy
(`~/.pi/agent/agents/*.md`):

1. **The ask catalog.** It carries a union of common risky operations (file
   deletion via recursive search, privilege escalation, disk tools, git
   history rewrites, package managers, remote shells). Add your own hosts,
   paths, and tools. The LAN block is a placeholder:

   ```yaml
   # EXAMPLE: prompt before touching a personal LAN box. Replace the host
   # placeholders with your own hostname or RFC1918 address.
   "ssh *192.168.1.10*": ask
   "ssh *myhost.local*": ask
   ```

   The installed copies are the source of truth; `install.sh` keeps them
   unless you pass `--force`. Keep `build.md` and `general-purpose.md`
   byte-identical in that block, or `08-catalog-drift.py` fails.

2. **Project paths.** `path_write`, `external_directory_write`, and the global
   `bash` default are yours: keep the credential/policy denies, then add
   allows for your own data and model directories where external writes should
   stay silent. The global `external_directory_write` gate is what scopes
   `rm`/`rmdir`/`shred`/`truncate` by location, so there is no per-command
   deletion ask to maintain.

`pi-veto` needs no personalization. Its `floor.json` is additive:

```json
{ "deny": { "bash": ["docker system prune *"], "paths": ["~/work/clients/*"] } }
```

## Throughput meters

Not in this repo: the footer tok/s readout is two floating packages, listed in
`settings.json` without a version so `pi update --extensions` picks up their
fixes:

- `git:github.com/StudioNirin/pi-token-speed` writes one `setStatus` footer
  segment. This is a fork of `gsanhueza/pi-token-speed`, not the npm build: the
  npm version drops the reconciled end-of-turn render when a delta redrew within
  `updateInterval`, so the footer showed 703 tok against a real 890 (upstream
  issue #20, patch posted there; PRs are disabled on that repo). The fork clone
  lives at `LLM-Tools/pi-token-speed` with `upstream` pointing at the original;
  merge upstream into `master` there and push, and pi's git reconciliation picks
  it up on the next start since the spec floats. Configured by the
  `tokenSpeed` block in `~/.pi/agent/settings.json`: `updateInterval: 80`
  (it ships `0`, which redraws on every delta), `slidingWindow: 5000` with a
  wider `providerOverrides.basalt` window, `endTpsBehavior: "average"`, and
  `display: "full"` for the `(150 tok in 6.0s · TTFT: 450 ms)` suffix. The four
  modes are `tps`, `ttft`, `stats` and `full`, and they only change the suffix:
  the primary value is always the rate. Scenario 14 gates that the installed
  meter is still the fork carrying the fix.
- `npm:pi-token-rate` draws a sparkline widget with EMA smoothing, median,
  percentile, peak and cost, and folds in pi-subagents child usage. It has no
  settings key; use `/token-rate` for on/off, position, detail and window.

Where each one lands in PiChamber, from its `extension-bridge.js`: `setStatus`
publishes `extension.status` and renders as a footer chip, always visible next
to the mode chip. `setWidget` publishes `extension.widget` and renders as a card
in the Extensions panel, opened by the `1 widget` chip, with the `placement`
value shown as a label. No widget draws inline above the composer there, so the
footer is the only always-visible surface.

`pi-token-rate` renders through a component factory, which RPC mode ignores
(`rpc-extension-ui.md`: only string arrays are supported), so it draws in the
CLI TUI and in PiChamber and stays silent to a bare RPC client. Scenario 14
measures the meter that RPC *can* see, and fails if either one starts
registering a tool, which would hit the deny-by-default personas.

## Regression gate

Run after **any** bump of pi, pi-permission-system, pi-subagents, or
PiChamber:

```sh
extensions/pi-workflow-modes/tests/run.sh
```

Scenarios 01-11 cover mode switching, resume leaks, the `!cmd` gate, dialog
round-trips, plan-file carve-out, mode transitions, the veto floor, catalog
drift, load order, the read-only bash shapes (compound `cd && grep` allowed,
writer/executor flags denied), and the user `!cmd` gate in plan mode. Scenario
14 measures the throughput meters. They pin a model deliberately; set
`PI_TEST_CWD` to a scratch project if you do not want probe files in `$PWD`.
See `tests/README.md`.
