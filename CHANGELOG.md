# Changelog

## 0.4.1 - 2026-11-13

Policy consolidation after a review of the permission review log (93 asks,
about a third of them probe traffic) and the pps 42.0.0 merge order.

- Global pps config now carries the fail-closed base instead of relying on a
  permissive default: `bash: { "*": "ask" }` for any agent with no profile
  (the built-in `Plan` was falling through to allow), the 14 catastrophic
  veto mirrors moved down from the three writer personas, and narrow
  `path_read` denies for credential stores.
- `external_directory_read: { "*": "allow" }` and
  `external_directory_write: { "*": "ask", "/tmp/*": "allow",
  "~/.cache/*": "allow" }`, with `commandEffects` for the everyday readers
  (`git log/show/diff/...`, `file`, `tree`, `du`, `df`, `jq`, `cut`,
  `readlink`, `lsof`). This removes the 30 path asks the log showed, almost
  all of them reads of an unproven command or scratch work in `/tmp`.
- `rm`/`rmdir`/`unlink`/`shred`/`truncate` are no longer per-command asks in
  `build.md` or `general-purpose.md`: the write-direction gate already scopes
  them by location (silent in the project and in `/tmp`, ask outside both).
  `dd` is scoped the same way (`dd if=*` allowed, `dd * of=*` ask).
- personas: `worker.md` and `scout.md` deleted (redundant with
  `general-purpose` and `Explore`); plan mode now dispatches `Explore`.
  `uniq` and `sed` removed from every read-only allowlist (a positional
  output and a `w`/`e` script write without any option), the writer-flag
  denies from the `!cmd` gate mirrored into the personas, and the git
  listing forms those modes actually need allowlisted (`branch -a/-v/-r/
  --show-current`, `tag -n`, `remote show`).
- `!cmd` gate: `env`, `sed`, and `uniq` dropped; `git` limited to its read
  subcommands with `branch`/`tag`/`remote` constrained to listing forms;
  `git --output`, `file -C`, `date -s` screened; a single `&` and
  newline-separated units fail closed. The README no longer claims build-mode
  `!cmd` is pps-gated (pps registers no `user_bash` handler; pi-veto covers
  it).
- Tests: `08` now pins the writer catalog plus the read-only surface and
  fails on a `uniq`/`sed` leak; `03`/`04` use `Explore`/`general-purpose`;
  `04` exercises the ask dialog with `chmod` (location-scoped `rm` no longer
  prompts); new `11-user-bash-gate.py` pins the gate matrix.
- Prompt timeouts: `promptTimeoutMs` 15 min to 3 min, `forwardingTimeoutMs`
  10 min to 4 min (prompt wait must stay below the child's forwarded-ask
  wait), plus `promptNotifications: ["bell", "osc9"]`.

## 0.4.0 - 2026-11-12

- Read-only bash compounds in plan/ask no longer die on `cd`. The
  "plan mode blocks grep" class of failures was always the command shape
  `cd /abs/path && grep ...`: pps splits chains on `&&`/`;`/`|` and judges
  every unit separately, so the leading `cd` unit hit `"*": deny` and
  killed the whole command even though `grep` itself is allowlisted.
  `plan.md`, `ask.md`, `scout.md`, and `Explore.md` now allowlist `cd`,
  `cd *`, `printf`, and `printf *` (allowing `cd` cannot smuggle writes:
  later chain units are still judged by their own rules).
- Personas deny `rg *--pre*` and `rg *--hostname-bin*`. pps's read-only
  effect guards cover `find -delete/-exec`, `sort -o`, and sed in-place,
  but `rg --pre` (which EXECUTES a program per file) matches a plain
  `"rg *"` allow on the assistant-bash path; the personas close that now.
- `pi-workflow-modes` read-only gate (the `!cmd`/RPC `bash` path, where
  this extension is the only read-only check) hardened the same way:
  `printf` allowlisted, a bare `cd` segment is benign, and a per-command
  flag denylist rejects writer/executor flags that the old name-only
  check passed - notably `find -delete`, `rg --pre`, `sort -o`,
  `sed -n -i` (the old `-n` prefix test let `-i` ride), and `tree -o`.
  Long-flag abbreviations and `--flag=value` attachments are screened.
- New scenario `10-readonly-bash.py`: plan-mode assertions on both bash
  paths (assistant tool-bash through pps personas, `!cmd` through this
  extension) that compound read-only chains run while every probe file
  survives `find -delete`, `rg --pre`, `sed -n -i`, `$(touch ...)`, and
  `&& touch`.

## 0.3.0 - 2026-11-12

- Removed `pi-opencode-free-sidecar` (and with it the vendored
  `@rabden/pi-opencode-zen` provider and the Bun transport relay).
  Rationale: the OpenCode Zen free tier only serves third-party hosts a
  heavily gated chat-lite shape (no native tools, assistant-role turns
  refused, short history caps; measured rules are in the 0.2.0-era
  extension README history). In practice the free models were unusable
  for agentic work from pi, so the lane was dropped rather than
  maintained. Free-model access on pi is now delegated to third-party
  catalogs (for example `pi-freeflow`), which are outside this repo's
  scope. Scenario 10 (relay contract) is retired with the extension;
  `run.sh` discovery is by glob, so nothing else changes.
- `install.sh` no longer seeds a Zen baseUrl; `models.json` provider
  config is entirely the user's own.

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
