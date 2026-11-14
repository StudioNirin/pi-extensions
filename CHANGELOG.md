# Changelog

## 0.4.5 - 2026-11-14

**Read-only personas now allow writes to `/dev/null` only.**

- Field denial: a plain `grep ... 2>/dev/null` in plan mode was blocked on
  `path_write` with decidingPath `/dev/null` (pps extracts redirect targets,
  including `2>`, and gates them as writes; the persona deny-all then wins).
  Every model emits `2>/dev/null` reflexively, so this was steady friction.
- `plan`, `ask` and `Explore` personas gain `"/dev/null": allow` in
  `path_write`: the kernel discards those bytes, no rule relaxation leaks
  anything. It is deliberately the exact path, not a wildcard, so stderr to
  a real file remains denied.
- Scenario 05 gains R13 (`cat file 2>/dev/null` must run, no dialog) and R14
  (`2>file` still blocked); both feed the PASS line. README carve-out
  section documents the stderr-redirect behaviour.
- Follow-up same day: the first deployment of the rule was inert, and R13
  caught it. pps's `parseSimpleYamlMap` only skips WHOLE-LINE comments, so an
  inline `allow   # note` parses the comment into the rule value, the action
  fails the allow|deny|ask validation and the entry is dropped tolerantly,
  leaving the deny-all to decide. Comments in persona frontmatter must stay
  on their own lines (a warning now sits in plan.md next to the rule).
  Notably pps itself already models `/dev/null` as the discard device
  (`path/safe-system-paths.ts`), so the allow matches upstream intent.
- Persona sync for the user-interactive tools (`ask_user_question`,
  `mockup_choice`): all five personas now name both with `allow`, seed and
  deployed. (An earlier build-only lean was reversed same day by user
  decision: any agent may put a question or a mockup pick to the user.)
  Scenario 08 grew a TOOL ACCESS GAP check asserting all five carry both
  lines, and its writer pin now simply requires both writers to hold them.

## 0.4.4 - 2026-11-13

**Breaking for the project-local plan directory.** `<cwd>/.plans/` is renamed to
`<cwd>/.pi/plans/`, with no alias: plan mode denies the old name from this
version on.

- Two reasons, both cosmetic in isolation and worth it together. The pair
  `~/.pi/plans/` and `<cwd>/.plans/` put one plan store inside pi's config
  directory and the other at the project root; `<cwd>/.pi/` is pi's own
  project-scoped location, the one pps already treats as pi infrastructure for
  `<cwd>/.pi/npm` and `<cwd>/.pi/git`. And a plan document at the project root
  added a second ignore entry next to `.pi/` in every project using plan mode,
  which is exactly the untracked noise report that prompted the change.
- pi core was not a factor: no plans directory appears anywhere in
  `/opt/pi-coding-agent/docs`, and the bundled `examples/extensions/plan-mode/`
  example never writes a plan file at all. Both names were this stack's, so the
  move settles an inconsistency between them rather than diverging from pi.
- `planPathAllowed()` now returns `~/.pi/plans` and `<cwd>/.pi/plans`; the
  `plan.md` persona allows `.pi/plans/*` in `path_write` and
  `external_directory_write`; scenario 05 probes the new paths; the README
  section gained the `test -d` finding, that an unclassifiable command's path
  token consults both surfaces, so plan mode cannot even stat a directory it may
  not write.
- Nothing to migrate: no `.plans` directory held any file on this box, and the
  empty one under `AI-APPS` was a harness leftover and is gone.
- The footer meter is no longer the npm `pi-token-speed`: its npm build drops
  the reconciled end-of-turn render, so the footer understated nearly every
  turn (measured 703 vs 890 at the shipped 80 ms interval). `settings.json`
  now installs `git:github.com/StudioNirin/pi-token-speed` floating, a fork
  carrying the one-line forced-render fix plus regression tests; the clone is
  `LLM-Tools/pi-token-speed` with an `upstream` remote for merging his future
  work. The bug and the patch are filed upstream (issue #20; that repo has pull
  requests disabled, so the fix is posted there as a patch). Scenario 14's P1
  now pins the source to the fork and a new P3 fails if the installed meter
  ever loses the fix.

## 0.4.3 - 2026-11-13

- `pi-workflow-modes` no longer carries Orbit mode-authority interop: the
  `orbit:workflow` entry comparison, the `ORBIT_BUNDLED_EXTENSIONS` /
  `ORBIT_WORKFLOW_MODE` detection, the mirror-through-`before_agent_start`
  branch and the `(Orbit chip)` status suffix are gone. `resolveMode` knows only
  our own `active_agent` entries and the `build` default, and
  `Resolution.authority` is `"own" | "default"`. Orbit is uninstalled.
- The `token-speed` path was still listed in `pi.extensions` after the vendored
  file was deleted. pi skips an unresolvable package-internal path with no
  warning, so nothing appeared broken. Scenario 09 gained M4, which fails if any
  listed extension path does not exist.
- Scenario 05 gained the plan-carve-out cases that were missing: an
  **absolute** `<cwd>/.plans/` write (agents pass absolute paths, and pps only
  matches the persona's relative `.plans/*` rule when the path lies inside the
  session cwd), a nested one, the bash `mkdir -p .plans && cat > .plans/x.md`
  shape an agent reaches for (denied: no rule can match a bare directory), the
  same write with the `mkdir` dropped, and a redirect outside the plan
  directories, which must be denied because an output redirect is a write. All
  twelve probes pass. `pi-workflow-modes/README.md` gained the matching
  "Authoring plan documents in plan mode" section.
- Scenario 14's width check now judges only the rate segment, up to `tok/s`,
  because `display: "full"` legitimately changes the whole line's length as the
  token and elapsed digits change. The total width is reported without a verdict.
- README documents the four `tokenSpeed.display` modes and where each meter
  lands in PiChamber: `setStatus` is a footer chip, `setWidget` is a card in the
  Extensions panel, and no widget draws inline above the composer there.

## 0.4.2 - 2026-11-13

- The footer tok/s readout is no longer vendored code: it is two floating
  packages (`npm:pi-token-speed`, `npm:pi-token-rate`), listed without a
  version so `pi update --extensions` picks up their fixes. No file in this
  repo now depends on unlicensed upstream code. A hand-rolled meter redrew on
  every delta, reported a raw instantaneous rate, used variable-width numbers,
  and blanked the readout for the whole of any tool run because the next
  `message_start` reset it; all four are handled upstream instead.
- New scenario `14-tps-meters`: both meters are installed floating, neither
  registers a tool, the `setStatus` meter redraws at most 15 times in any one
  second, its number does not jump more than 45% of its own observed range, and
  its rendered width stays inside 8 distinct lengths. The widget meter is
  checked as load-clean-and-silent, because RPC mode ignores component
  factories.

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
