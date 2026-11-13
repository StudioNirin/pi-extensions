# pi-workflow-modes

Per-session **workflow modes** (`plan` / `ask` / `build`) for every pi runtime
that loads `~/.pi/agent/extensions` - the CLI TUI and PiChamber. Zero
frontend modifications: everything rides pi's extension API. Policy is layered:
`pi-permission-system` ("pps") owns asks and the general policy, the
`pi-veto` extension owns the deny-only catastrophic floor, and this extension
owns the mode selection, the plan-file carve-out, and Explore-only subagent
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
     `~/.pi/plans/` or `<cwd>/.pi/plans/`; `subagent` is allowed **only** for the
     read-only `Explore` profile. This is what closes the `--continue` resume
     leak (`pps` once resolved such calls agent-null) while still letting a
     planning session write its own plan documents.
5. **pi-veto** (separate extension, below everything): hard-denies catastrophic
   commands and credential/policy writes for tools *and* `!cmd`. It never asks
   and no agent frontmatter can reach it.

`!`/`!!` user-bash (and the RPC `bash` command) is gated by the `user_bash`
handler: in plan/ask only a read-only command allowlist passes, with per-command
flag denies (`find -delete/-exec/-fprint`, `rg --pre`, `sort -o`, `tree -o`,
`file -C`, `git --output`) since a bare name check would let `find . -delete`
through; a `cd` segment is benign because every other segment of the chain is
still judged on its own. `uniq`, `sed`, and `env` are not on the list at all:
`uniq IN OUT` writes a file, a sed script can carry `w`/`e`, and `env CMD` is a
wrapper. `git` is read-only only for the read subcommands, with `branch`, `tag`,
and `remote` limited to their listing forms. Unparseable shapes, a single `&`,
and newline-separated units fail closed.

Build mode passes through **without a pps check**: pps registers no `user_bash`
handler, so a build-mode `!cmd` is covered by pi-veto's floor and nothing else.
That is deliberate (`!cmd` is typed by the user and runs in their own shell),
but do not describe it as pps-governed.

**Load order is load-bearing.** Extension handlers run in load order, and a
blocked `tool_call` stops later handlers. The package lists `pi-veto` first and
`install.sh` keeps the package ahead of `pi-permission-system` in
`settings.json`, so a veto block fires before pps can open an ask dialog. The
catalog's deny mirrors would suppress most of those dialogs anyway; the order
makes it true for every veto-covered command, including the ones the mirrors
cannot express without matching legitimate paths.

### Authoring plan documents in plan mode

Plan mode exists to write plan documents, so the carve-out is the one thing in
the read-only posture that must not surprise you. Two directories, both chosen
by this stack: `~/.pi/plans/` for plans that outlive a project, and
`<cwd>/.pi/plans/` for plans that belong to one. The project-side name follows
pi's own project-scoped convention, the one pps already recognises for
`<cwd>/.pi/npm` and `<cwd>/.pi/git`; pi core has no plans directory of its own.
Verified by scenario 05:

- **Use `write`.** Any path under `<cwd>/.pi/plans/` or `~/.pi/plans/` is allowed,
  at any depth, and `write` creates the directories it needs on the way.
- **`mkdir -p <cwd>/.pi/plans` is denied, and always will be.** `.pi/plans/*`
  compiles to `^\.pi/plans/.*$`, which needs the separator, so no rule can match
  the bare directory that `mkdir` names; `"*": deny` wins. This is the denial
  that reads like "the carve-out is broken". It is not: drop the `mkdir` and the
  same write succeeds.
- A bash **output redirect** consults the `path_write` surface, so
  `cat > <cwd>/.pi/plans/x.md` works and `cat > <cwd>/x.md` is denied. It is pps's
  rule though, not this extension's: the `tool_call` blocker only inspects
  `write`/`edit` paths, so the redirect stays inside the carve-out exactly as
  long as `path_write` says it does.
- Two different messages, both correct. A command whose effect pps cannot
  classify reports a **path** denial naming the directory; a bare relative
  filename is not a path candidate at all (only absolute, `~/`, `..`-bearing,
  separator-bearing tokens and redirect targets are extracted), so that one
  reports the **command** rule instead. An unclassifiable command's path token
  consults *both* surfaces, so in plan mode even `test -d <plan dir>` is refused:
  it may not write there, so it may not stat there either.
- `<cwd>/.pi/plans` means **this session's** cwd. pps derives a project-relative
  alias for an absolute path only when the path lies strictly inside the session
  cwd (`access-intent/path-normalization.ts:97`), so another project's
  `.pi/plans` has nothing to match the persona's relative rule and is denied.
  `~/.pi/plans/` is absolute and works from anywhere, which is why it looks like
  the only one that works when a session is opened in the wrong place.
- Both live under a dot-directory projects usually ignore, so plan documents do
  not turn up as untracked noise: `~/.pi` needs no entry, and adding `.pi/` to a
  project's `.gitignore` covers the project-side one.

### Global policy shape

The global pps config is the fail-closed base; the personas narrow or widen it
per mode:

```json
{
  "permission": {
    "*": "allow",
    "bash": { "*": "ask", "...": "hard denies (veto mirrors)" },
    "external_directory_read": { "*": "allow" },
    "external_directory_write": { "*": "ask", "/tmp/*": "allow", "~/.cache/*": "allow" },
    "path_read": { "...": "credential denies" },
    "path_write": { "...": "credential/policy denies" }
  },
  "commandEffects": { "...": "git readers, file, tree, du, df, jq, cut, readlink, lsof" }
}
```

- `bash: { "*": "ask" }` is the default for an agent with **no profile**: the
  built-in `Plan`, or a subagent type with no agent file. Every persona states
  its own `*` (`allow` for build/general-purpose, `deny` for
  plan/ask/Explore), and agent entries merge after the global ones, so the
  packaged personas are unaffected while an unprofiled agent stops running
  bash silently.
- The catastrophic deny mirrors (`mkfs`, `fdisk`, `dd of=/dev/*`, `reboot`,
  ...) live here once instead of once per persona. pi-veto is still the
  authority and fires first; the mirrors only stop pps from offering a dialog
  for something the veto will refuse.
- `external_directory_read: allow` plus `commandEffects` for the everyday
  readers (`git log/show/diff/...`, `file`, `tree`, `du`, `df`, `jq`, `cut`,
  `readlink`, `lsof`) is what stops a read outside the project from prompting.
  `external_directory_write` scopes the rest: silent in the project, silent in
  `/tmp` and `~/.cache`, ask anywhere else. That gate, not a per-command rule,
  is what scopes `rm`/`rmdir`/`unlink`/`shred`/`truncate`, so they are absent
  from the catalogs.
- The ask catalog lives in the agent files (`build.md` and
  `general-purpose.md`, kept byte-identical by `08-catalog-drift.py`), because
  every ask must be mode-aware and could not live globally without leaking into
  plan/ask.
- `promptTimeoutMs` (3 min) is the wait for a human before an unanswered prompt
  becomes a denial; `forwardingTimeoutMs` (4 min) must stay above it so a
  child's forwarded ask does not expire while the parent dialog is still open.
  `promptNotifications` rings the terminal when a prompt opens.
- `path_read`/`path_write` keep the credential denies as the last-resort layer
  below pi-veto. A persona that grants `path_read: { "*": allow }` must repeat
  those denies **after** the grant: agent entries merge last, so the grant
  would otherwise shadow the global denies.

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
session; they stay out of pi-subagents' delegatable list (`general-purpose` and
`Explore` are the delegatable ones and live in the same directory).

## Tests / upgrade gate

`tests/` holds a headless RPC regression suite (scenario scripts + `run.sh`).
Run after **any** version change to pi, pps, pi-subagents, or PiChamber -
pps's config format has broken across majors before (see its
`docs/migration/legacy-to-flat.md`). Scenario map:

| Script | Proves |
| --- | --- |
| `01-mode-switch.py` | `/plan` keeps the carve-out tool set; `/build` restores; entries persist |
| `02-resume-and-gate.py` | resume keeps plan mode; RPC `bash` (`!cmd`) gate blocks `touch`, passes `ls` |
| `03-resume-leak.py` | resumed plan session cannot write project files (`tool_call` blocker) |
| `04-dialogs-subagents.py` | fresh session default; pps ask-dialog approve/deny round-trip over RPC (`chmod`); `general-purpose` forwarded approval (`sh -c`); `Explore` child cannot write |
| `05-plan-carveout.py` | plan writes are silent-denied outside the plan dirs, allowed inside them, and no `permission_request.waiting` ever appears |
| `06-mode-transition.py` | switching plan->build injects `<workflow_mode_changed>` and the model acts on the new mode |
| `07-veto.py` | pi-veto blocks `wipefs` (a command pps does not know) and `dd of=/dev/*` via `!cmd`; floor.json adds denies and ignores non-deny shapes |
| `08-catalog-drift.py` | `build.md`/`general-purpose.md` catalogs and the plan/ask/Explore read-only surface are byte-identical, with no `uniq`/`sed` leak |
| `09-load-order.py` | the package lists `pi-veto` first, settings lists the package before pps, and no loose copies shadow it (a block must preempt an ask dialog) |
| `10-readonly-bash.py` | plan-mode compound `cd && grep` runs on both bash paths, while `find -delete`, `rg --pre`, `sed -n -i`, `$(...)` and `&& touch` leave every probe intact |
| `11-user-bash-gate.py` | `!cmd`/RPC-bash gate: readers pass; `uniq IN OUT`, `sort -o`, `file -C`, `git tag/branch/remote` mutations, `git --output`, `date -s`, `env`, `sed`, single `&`, and newline units are blocked |

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
