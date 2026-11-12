# pi-extensions

One **pi-package** carrying the extension stack that gives every pi runtime
(the CLI TUI, PiChamber, Orbit) the same policy behaviour:

| Extension | Role |
| --- | --- |
| [`pi-workflow-modes`](extensions/pi-workflow-modes/README.md) | Per-session **plan / ask / build** modes: selection, the plan-file carve-out, scout-only subagent dispatch, and model-visible mode transitions. |
| [`pi-veto`](extensions/pi-veto/README.md) | The **deny-only security floor**: catastrophic commands and credential/policy writes can never run, ask, or be allowed, including from `!cmd`. |
| [`pi-opencode-free-sidecar`](extensions/pi-opencode-free-sidecar/README.md) | **OpenCode Zen free models on every host**: vendored provider (`@rabden/pi-opencode-zen`, MIT) plus an on-demand Bun transport relay, because Zen classifies free-tier clients by transport fingerprint and refuses Node-hosted pi. Replaces `npm:@rabden/pi-opencode-zen`. |

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
extensions/pi-opencode-free-sidecar/  Zen provider (vendor/) + Bun relay
                                (relay.js) + tests/
agents/                         generic example personas (build, worker,
                                general-purpose, plan, ask, scout, Explore)
install.sh                      register the package + seed agents/ +
                                seed the Zen relay baseUrl
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
   deletion, privilege escalation, disk tools, git history rewrites, package
   managers, remote shells). Add your own hosts, paths, and tools. The LAN
   block is a placeholder:

   ```yaml
   # EXAMPLE: prompt before touching a personal LAN box. Replace the host
   # placeholders with your own hostname or RFC1918 address.
   "ssh *192.168.1.10*": ask
   "ssh *myhost.local*": ask
   ```

   The installed copies are the source of truth; `install.sh` keeps them
   unless you pass `--force`. Keep `build.md`, `worker.md`, and
   `general-purpose.md` byte-identical in that block, or
   `08-catalog-drift.py` fails.

2. **Project paths.** `path_write` and `external_directory_write` are yours:
   keep the credential/policy denies, then add allows for your own data and
   model directories where external writes should stay silent.

`pi-veto` needs no personalization. Its `floor.json` is additive:

```json
{ "deny": { "bash": ["docker system prune *"], "paths": ["~/work/clients/*"] } }
```

## Regression gate

Run after **any** bump of pi, pi-permission-system, pi-subagents, PiChamber, or
Orbit:

```sh
extensions/pi-workflow-modes/tests/run.sh
```

Scenarios 01-09 cover mode switching, resume leaks, the `!cmd` gate, dialog
round-trips, plan-file carve-out, mode transitions, the veto floor, catalog
drift, and load order. Scenario 10 covers the Zen relay (auth, idle exit,
provider load contract, one live Zen call; prints a skip note if `bun` is
not installed). They pin a model deliberately; set `PI_TEST_CWD` to a
scratch project if you do not want probe files in `$PWD`. See `tests/README.md`.

## Zen free models

`pi-opencode-free-sidecar` needs `bun` available on PATH or at
`~/.local/bin/bun` (relay runtime only; pi itself does not use it), and
replaces `npm:@rabden/pi-opencode-zen`: if that npm entry is still in
`~/.pi/agent/settings.json`, remove it. See the
[extension README](extensions/pi-opencode-free-sidecar/README.md) for the
relay lifecycle, token gating, and `/opencode-free-sidecar`.
