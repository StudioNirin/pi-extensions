"""05-plan-carveout: plan mode writes plan documents and nothing else, silently.

Pass criteria in printed output:
  - bash `touch` in plan mode: blocked, no file, no dialog
  - write tool to a project path: blocked, no file
  - write tool to <cwd>/.plans/: allowed
  - write tool to ~/.pi/plans/: allowed
  - ZERO permission_request.waiting / Permission dialogs during the whole run
"""
import json, os, subprocess, sys, threading, time

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
SESSION_GLOB = os.path.join(AGENT_DIR, "sessions",
    "--" + CWD.lstrip("/").replace("/", "-") + "--", "*.jsonl")
PROBES = {
    "bash": os.path.join(CWD, "plan-bash-probe.txt"),
    "project": os.path.join(CWD, "plan-write-probe.md"),
    "cwd_plans": os.path.join(CWD, ".plans", "plan-write-ok.md"),
    "home_plans": os.path.expanduser("~/.pi/plans/plan-write-ok.md"),
}
for path in PROBES.values():
    try: os.remove(path)
    except OSError: pass
os.makedirs(os.path.join(CWD, ".plans"), exist_ok=True)
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
    and os.path.exists(PROBES["home_plans"])
    and waiting == 0 and not DIALOGS
) else "FAIL", flush=True)
print("leftover probe files:", files, flush=True)
