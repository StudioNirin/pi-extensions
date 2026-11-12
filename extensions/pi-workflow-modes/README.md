# pi-workflow-modes

Per-session **workflow modes** (`plan` / `ask` / `build`) for every pi runtime
that loads `~/.pi/agent/extensions` - the CLI TUI, PiChamber, and Orbit. Zero
frontend modifications: everything rides pi's extension API. Policy is layered:
`pi-permission-system` ("pps") owns asks and the general policy, the
`pi-veto` extension owns the deny-only catastrophic floor, and this extension
owns the mode selection, the plan-file carve-out, and scout-only subagent
dispatch.

## How a mode works

A *mode* is a **primary-agent persona**. Two signals define it (both are what
pps natively reads to resolve "which agent's rules apply to this session"):

1. a session custom entry `{ type: "custom", customType: "active_agent", data: { name: "<mode>" } }`
2. the system-prompt tag `<active_agent name="<mode>"/>` (injected each turn;
   mirrors pi-subagents' child-agent vocabulary)

Division of labour - this extension is the **switch**, the agent files are the
**wiring diagrams**:

| Piece | Owns |
| --- | --- |
| `pi.registerCommand("plan"|"ask"|"build")` | selection: appends the `active_agent` entry (persisted - modes survive resume/close) |
| `before_agent_start` | injects `~/.pi/agent/agents/<mode>.md` body (behaviour prompt) + the tag |
| `~/.pi/agent/agents/<mode>.md` `permission:` frontmatter | the actual policy (pps reads these; flat v42 surfaces) |
| pps itself | tool hiding, bash/path/external-directory enforcement, ask dialogs, subagent forwarding. pps **never writes** the marker - that is why this extension must exist |

`/workflow-mode` prints the current mode and its authority. With no signals a
session is `build` (authority `default`) and behaves exactly like a plain pps
session - modes only change things when explicitly selected.

### Enforcement layers for read-only modes (plan/ask)

Five independent layers, all keyed off the same mode resolution (defence in
depth - a resumed session that smuggles a stale tool set still cannot write):

1. **pps tool filtering**: tools denied in the agent profile are removed from
   the model's tool list entirely.
2. **pps bash/path rules**: `"*": deny` bash + a path policy that denies
   everything outside the plan directories (plan) or everything (ask).
3. **this extension's `setActiveTools` subtraction** for ask mode (belt and
   braces below pps).
4. **this extension's `tool_call` blocker**, the leak-proof layer:
   - ask: `write/edit/subagent/steer_subagent/get_subagent_result` are blocked
     outright.
   - plan: `write/edit` are allowed **only** when the target path is under
     `~/.pi/plans/` or `<cwd>/.plans/`; `subagent` is allowed **only** for the
     read-only `scout` profile. This is what closes the `--continue` resume
     leak (`pps` once resolved such calls agent-null) while still letting a
     planning session write its own plan documents.
5. **pi-veto** (separate extension, below everything): hard-denies catastrophic
   commands and credential/policy writes for tools *and* `!cmd`. It never asks
   and no agent frontmatter can reach it.

`!`/`!!` user-bash (and the RPC `bash` command) is gated by the `user_bash`
handler: in plan/ask only a read-only command allowlist passes, with per-command
flag denies (`find -delete/-exec`, `rg --pre`, `sort -o`, `sed -i`, `tree -o`)
since a bare name check would let `find . -delete` through; a `cd` segment is
benign because every other segment of the chain is still judged on its own.
Unparseable shapes fail closed; build mode passes through to pps. `pi-veto`
checks the same commands first and blocks its floor in every mode.

**Load order is load-bearing.** Extension handlers run in load order, and a
blocked `tool_call` stops later handlers. The package lists `pi-veto` first and
`install.sh` keeps the package ahead of `pi-permission-system` in
`settings.json`, so a veto block fires before pps can open an ask dialog. The
catalog's deny mirrors would suppress most of those dialogs anyway; the order
makes it true for every veto-covered command, including the ones the mirrors
cannot express without matching legitimate paths.

### Orbit interop (single authority)

Sessions created by Orbit carry `orbit:workflow` chip entries. Rule: if the
newest `orbit:workflow` entry is **newer** than our newest `active_agent`
entry, Orbit's chip is the authority - we *mirror* it into an `active_agent`
entry (so pps profiles and dialogs follow you) but never inject our own prompt
(Orbit supplies mode guidance and tool scoping itself). Typing `/plan` etc.
flips authority back to you (your entry becomes newest). Orbit sessions are
also detected via `ORBIT_BUNDLED_EXTENSIONS` / `ORBIT_WORKFLOW_MODE` env.

Orbit's own bundled subagent extension is disabled by
`chmod 000 ~/.orbit-pi/subagents-extension/index.js` so the same-author
`@gotgenes/pi-subagents` package can register the `subagent` tool (pi treats
duplicate tool names as a fatal conflict in either order). Restore with:

```sh
chmod 644 ~/.orbit-pi/subagents-extension/index.js   # then restart Orbit
```

Recommended Orbit access mode: **Full-access** so pps is the sole prompter
(no double prompts).

### Global policy shape (why it looks so permissive)

The global pps config is deliberately thin:

```json
{ "permission": { "*": "allow", "bash": { "*": "allow" }, "path_write": { ...denies... } } }
```

- The **ask catalog lives in the agent files** (`build.md`, `worker.md`,
  `general-purpose.md`, kept byte-identical by `08-catalog-drift.py`), because
  every ask must be mode-aware and could not live globally without leaking into
  plan/ask.
- The explicit `"bash": { "*": "allow" }` is what the top-level `"*": "allow"`
  already meant. pps's permissive-bash detector only inspects this global
  merge (not per-agent frontmatter), so stating it silences a warning that was
  structurally unable to be right for this layout. Do not drop it: without it
  the operator gets that advisory on every session start.
- `path_write` keeps the credential/policy denies as the last-resort layer
  below pi-veto.

## Adding a 4th mode (recipe)

1. Create `~/.pi/agent/agents/<name>.md` with frontmatter
   (`name`, `description`, `mode: primary`, `enabled: false`, plus a flat
   `permission:` block - copy `plan.md` or `ask.md` and adjust) and a body =
   the behaviour prompt.
2. Add the name to `MODES` in `index.ts`. If the mode is read-only, also add
   it to the checks in `before_agent_start` (ask-style removal) and the
   `tool_call` blocker + `user_bash` gate (both name `"plan" || "ask"`).
3. Restart any live pi sessions (PiChamber: restart its session daemon or the
   app). Nothing else - selection, injection, status line, pps profiles all
   follow.

Agents with `mode: primary` + `enabled: false` are personas for the *parent*
session; they stay out of pi-subagents' delegatable list (scout/worker are the
delegatable ones and live in the same directory).

## Tests / upgrade gate

`tests/` holds a headless RPC regression suite (scenario scripts + `run.sh`).
Run after **any** version change to pi, pps, pi-subagents, PiChamber, or
Orbit - pps's config format has broken across majors before (see its
`docs/migration/legacy-to-flat.md`). Scenario map:

| Script | Proves |
| --- | --- |
| `01-mode-switch.py` | `/plan` keeps the carve-out tool set; `/build` restores; entries persist |
| `02-resume-and-gate.py` | resume keeps plan mode; RPC `bash` (`!cmd`) gate blocks `touch`, passes `ls` |
| `03-resume-leak.py` | resumed plan session cannot write project files (`tool_call` blocker) |
| `04-dialogs-subagents.py` | fresh session default; pps ask-dialog approve/deny round-trip over RPC; worker forwarded approval (`sh -c`); scout child cannot write |
| `05-plan-carveout.py` | plan writes are silent-denied outside the plan dirs, allowed inside them, and no `permission_request.waiting` ever appears |
| `06-mode-transition.py` | switching plan->build injects `<workflow_mode_changed>` and the model acts on the new mode |
| `07-veto.py` | pi-veto blocks `wipefs` (a command pps does not know) and `dd of=/dev/*` via `!cmd`; floor.json adds denies and ignores non-deny shapes |
| `08-catalog-drift.py` | `build.md`, `worker.md`, and `general-purpose.md` carry byte-identical catalogs |
| `09-load-order.py` | the package lists `pi-veto` first, settings lists the package before pps, and no loose copies shadow it (a block must preempt an ask dialog) |
| `10-readonly-bash.py` | plan-mode compound `cd && grep` runs on both bash paths, while `find -delete`, `rg --pre`, `sed -n -i`, `$(...)` and `&& touch` leave every probe intact |

They pin `--model basalt/Qwen3.8-Flash-Next-NVFP4` deliberately: pi's global
"last used model" drifts with GUI use, and a wrong/empty model makes every
scenario fail as "model never called the tool" (observed 2026-11-11 with
kimi-k2.7-code returning empty messages). Override with `PI_TEST_MODEL` to use
another provider/model; set `PI_TEST_CWD` to keep probe files out of `$HOME`.

**Upgrade note (2026-11-12):** the old nested `pi-codemode@1.0.4` re-pin is
**obsolete from PiChamber 1.0.6 onward**. PiChamber 1.0.7 bundles
`pi-coding-agent@1.5.0`, which pins `pi-codemode` to exactly `1.5.0`, so npm
resolves the tree correctly and the old nested pin is discarded with it. Do not
restore the 1.0.4 nested copy after an update; run `tests/run.sh` instead.

## Known quirks

- **Resumed sessions list removed tools in the prompt** - the stale `<tools>`
  section in a resumed context is cosmetic; the `tool_call` blocker stops
  execution regardless. Judge enforcement by files-on-disk and dialogs seen,
  never by model narration (local models confabulate tool calls and denial
  quotes).
- **pps debug log**: `~/.pi/agent/extensions/pi-permission-system/logs/`
  (`permission.decision` events; terse allow lines carry no agent field).
  Toggle via `debugLog` in that extension's `config.json`.
- The live pps policy is the flat `permission:` block inside
  `~/.pi/agent/extensions/pi-permission-system/config.json` (v42 format).
  `pi-permissions.jsonc` and the `defaultPolicy`/nested-`tools` format are the
  **legacy upstream (MasuRii) format** - not loaded by v42.
