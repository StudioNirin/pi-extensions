r"""05-plan-carveout: plan mode writes plan documents and nothing else, silently.

Pass criteria in printed output:
  - bash `touch` in plan mode: blocked, no file, no dialog
  - write tool to a project path: blocked, no file
  - write tool to <cwd>/.plans/: allowed
  - write tool to ~/.pi/plans/: allowed
  - write tool to an ABSOLUTE <cwd>/.plans/ path: allowed (agents pass absolute
    paths, and pps only matches the persona's relative `.plans/*` rule when the
    absolute path lies inside the session cwd, so this is the realistic case)
  - nested depth under .plans/: allowed. The persona rule is `.plans/*` and pps
    compiles `*` to `.*` with the `s` flag (policy/wildcard-matcher.ts), so a
    path wildcard crosses separators and depth is not a limit. Asserted because
    a pps change to that would otherwise silently narrow the carve-out.
  - the bash shape `mkdir -p <cwd>/.plans && cat > <cwd>/.plans/x.md`: blocked,
    and blocked twice over. `.plans/*` compiles to `^\.plans/.*$`, which needs a
    separator, so it can never match the bare directory `.plans` that `mkdir -p`
    puts on the table, and the persona's bash list is read-only with no `mkdir`.
    The `cat >` target would have been allowed. This is the shape an agent reaches
    for when it thinks the write tool cannot make directories, so R10 is the
    counter-example: the write tool makes them itself.
  - bash redirect into .plans/ and out of it (R11, R12): recorded as behaviour.
    R12 is the security half and is asserted: `cat` is in the read-only bash
    allowlist, so if a redirect target were not gated as a write path, `cat >`
    would write anywhere the persona is meant to be read-only, while R2 shows the
    write tool cannot. R11 has no verdict on purpose: whichever way a plain
    redirect inside the plan dirs behaves is the shape worth documenting, not the
    one worth breaking.
  - ZERO permission_request.waiting / Permission dialogs during the whole run
"""
import json, os, re, subprocess, sys, threading, time

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
SESSION_GLOB = os.path.join(AGENT_DIR, "sessions",
    "--" + CWD.lstrip("/").replace("/", "-") + "--", "*.jsonl")
PROBES = {
    "bash": os.path.join(CWD, "plan-bash-probe.txt"),
    "project": os.path.join(CWD, "plan-write-probe.md"),
    "cwd_plans": os.path.join(CWD, ".plans", "plan-write-ok.md"),
    "cwd_plans_abs": os.path.join(CWD, ".plans", "plan-abs-ok.md"),
    "cwd_plans_deep": os.path.join(CWD, ".plans", "nested", "plan-deep-ok.md"),
    "cwd_plans_bash": os.path.join(CWD, ".plans", "plan-bash-heredoc.md"),
    # Deliberately not pre-created: R10 asks whether the write tool makes the
    # directories itself, which is what makes the bash mkdir shape unnecessary.
    "cwd_plans_mk": os.path.join(CWD, ".plans", "fresh", "deeper", "plan-no-mkdir.md"),
    "cwd_plans_redir": os.path.join(CWD, ".plans", "plan-redirect.md"),
    "redir_outside": os.path.join(CWD, "plan-redirect-outside.md"),
    "home_plans": os.path.expanduser("~/.pi/plans/plan-write-ok.md"),
}
for path in PROBES.values():
    try: os.remove(path)
    except OSError: pass
# The deep parent exists up front so R8 answers the permission question only,
# not whether the write tool creates intermediate directories.
os.makedirs(os.path.join(CWD, ".plans", "nested"), exist_ok=True)
os.makedirs(os.path.expanduser("~/.pi/plans"), exist_ok=True)

DIALOGS = []

class Session:
    def __init__(self):
        self.p = subprocess.Popen(
            ["pi", "--mode", "rpc", "--approve", "--model", TEST_MODEL],
            cwd=CWD, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines = []
        threading.Thread(target=self.read, daemon=True).start()
    def read(self):
        for line in self.p.stdout: self.lines.append(line.strip())
    def send(self, obj):
        self.p.stdin.write(json.dumps(obj) + "\n"); self.p.stdin.flush()
    def ends(self):
        return sum(1 for l in self.lines if '"type":"agent_end"' in l or '"type": "agent_end"' in l)
    def turn(self, message, timeout=300):
        prev = self.ends()
        self.send({"id": abs(hash(message + str(time.time()))), "type": "prompt", "message": message})
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.ends() > prev: return True
            if self.p.poll() is not None: return False
            time.sleep(0.5)
        return False
    def stop(self):
        self.p.terminate()

s = Session()
# Answer any dialog with No and record it, so a bug shows up as a dialog count.
def watchdog():
    seen = set(); idx = 0
    while True:
        while idx < len(s.lines):
            line = s.lines[idx]; idx += 1
            if '"extension_ui_request"' not in line: continue
            try: d = json.loads(line)
            except Exception: continue
            if d.get("method") not in ("select", "confirm"): continue
            rid = d.get("id")
            if rid in seen: continue
            seen.add(rid)
            DIALOGS.append((d.get("title", "")[:120], d.get("method")))
            print(f"[DIALOG] {d.get('method')}: {d.get('title','')[:120]}", flush=True)
            s.send({"type": "extension_ui_response", "id": rid, "confirmed": False,
                    "value": "No"})
        if s.p.poll() is not None: return
        time.sleep(0.3)
threading.Thread(target=watchdog, daemon=True).start()
time.sleep(7)
if s.p.poll() is not None:
    print("PI DIED:", s.p.stderr.read()[:800]); sys.exit(1)

s.send({"id": 1, "type": "prompt", "message": "/plan"}); time.sleep(4)

s.turn("Call the bash tool exactly once with: touch plan-bash-probe.txt . Report the raw result briefly.")
print("R1 plan bash touch blocked (no file):", not os.path.exists(PROBES["bash"]), flush=True)

s.turn("Use the write tool exactly once to create plan-write-probe.md containing x. Report the raw result briefly.")
print("R2 plan project write blocked (no file):", not os.path.exists(PROBES["project"]), flush=True)

s.turn("Use the write tool exactly once to create .plans/plan-write-ok.md containing x. Report the raw result briefly.")
print("R3 plan-dir write allowed (file exists):", os.path.exists(PROBES["cwd_plans"]), flush=True)

s.turn(f"Use the write tool exactly once to create {PROBES['home_plans']} containing x. Report the raw result briefly.")
print("R4 home plan-dir write allowed (file exists):", os.path.exists(PROBES["home_plans"]), flush=True)

# R7 is the spelling a real agent produces: the same project plan directory,
# absolute. R3 spells it relative, which the persona rule matches directly.
s.turn(f"Use the write tool exactly once to create {PROBES['cwd_plans_abs']} containing x. Report the raw result briefly.")
print("R7 absolute <cwd>/.plans write allowed (file exists):", os.path.exists(PROBES["cwd_plans_abs"]), flush=True)

# R8: depth is not a limit. `.plans/*` compiles to `\.plans/.*` with the `s`
# flag, so the wildcard crosses separators; the parent dir is created up front
# so a failure here can only mean the path was not allowed.
s.turn(f"Use the write tool exactly once to create {PROBES['cwd_plans_deep']} containing x. Report the raw result briefly.")
print("R8 nested .plans write allowed (file exists):", os.path.exists(PROBES["cwd_plans_deep"]), flush=True)

# R9 reproduces a real plan-mode failure: the agent reaches for bash because it
# assumes a plan directory has to be made first. `mkdir` has no commandEffects
# entry, so its target's direction is unproven and pps checks it against the
# write side as well, and `.plans/*` cannot match the bare directory that
# `path.relative(cwd, dir)` yields. Observed as:
#   Denied by policy: 'path' for tool 'bash' for agent 'plan' for path '<dir>' (rule '*')
# Compare R1, which denies on the command surface instead:
#   Denied by policy: 'bash' for agent 'plan' (rule '*')
# because a bare relative filename is not a path candidate at all: only absolute,
# home-relative, `..`-bearing and separator-bearing tokens plus redirect targets
# are extracted, so there the command rule was all there was to match.
plans_dir = os.path.join(CWD, ".plans")
heredoc = f"mkdir -p {plans_dir} && cat > {PROBES['cwd_plans_bash']} <<'EOF'\nx\nEOF"
s.turn("Call the bash tool exactly once with this command, unchanged, then quote "
       "the raw result verbatim:\n" + heredoc)
denied = [l for l in s.lines if "Denied by policy" in l or "Blocked in plan mode" in l]
print("R9 bash mkdir+heredoc into .plans blocked (no file):",
      not os.path.exists(PROBES["cwd_plans_bash"]), flush=True)
print("R9 denial text seen:", bool(denied),
      re.sub(r"\s+", " ", denied[-1])[:220] if denied else "(none)", flush=True)

# R10 is the counter-example that makes R9's shape unnecessary: the write tool
# creates the intermediate directories itself, inside the carve-out.
s.turn(f"Use the write tool exactly once to create {PROBES['cwd_plans_mk']} containing x. Report the raw result briefly.")
print("R10 write tool creates missing plan dirs (file exists):",
      os.path.exists(PROBES["cwd_plans_mk"]), flush=True)

# R11 drops the mkdir, which is the half of R9 that had no legal spelling. If a
# plan-mode agent can write a plan file with a plain redirect, that is the shape
# to document; if it cannot, the write tool is the only route.
s.turn("Call the bash tool exactly once with this command, unchanged, then quote "
       "the raw result verbatim:\ncat > " + PROBES["cwd_plans_redir"] + " <<'EOF'\nx\nEOF")
print("R11 bash redirect into .plans (file exists):",
      os.path.exists(PROBES["cwd_plans_redir"]), flush=True)

# R12 is the security half of the same question. `cat` is in the persona's
# read-only bash allowlist, so if a redirect target is not gated as a WRITE path
# then `cat > file` writes anywhere the persona is supposed to be read-only. R2
# proves the write tool cannot reach this same location, so the two must agree.
s.turn("Call the bash tool exactly once with this command, unchanged, then quote "
       "the raw result verbatim:\ncat > " + PROBES["redir_outside"] + " <<'EOF'\nx\nEOF")
print("R12 bash redirect OUTSIDE the plan dirs blocked (no file):",
      not os.path.exists(PROBES["redir_outside"]), flush=True)

waiting = sum(1 for l in s.lines if "permission_request.waiting" in l)
print("R5 ZERO permission_request.waiting:", waiting == 0, f"(seen {waiting})", flush=True)
print("R6 ZERO permission dialogs:", len(DIALOGS) == 0, f"(seen {len(DIALOGS)})", flush=True)

s.stop()
time.sleep(1)
files = [p for p in PROBES.values() if os.path.exists(p)]
print("PASS" if (
    not os.path.exists(PROBES["bash"])
    and not os.path.exists(PROBES["project"])
    and os.path.exists(PROBES["cwd_plans"])
    and os.path.exists(PROBES["cwd_plans_abs"])
    and os.path.exists(PROBES["cwd_plans_deep"])
    and not os.path.exists(PROBES["cwd_plans_bash"])
    and os.path.exists(PROBES["cwd_plans_mk"])
    and os.path.exists(PROBES["home_plans"])
    and waiting == 0 and not DIALOGS
) else "FAIL", flush=True)
print("leftover probe files:", files, flush=True)
