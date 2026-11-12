"""06-mode-transition: switching modes tells the MODEL, not only the user.

Uses the extension's test seam: PI_WORKFLOW_MODES_TRACE=<path> appends one JSON
line per agent turn with the resolved mode, the previous mode, and the notice
that was injected.

Pass criteria in printed output:
  - first build turn: mode=build, no notice
  - after /plan: previous=build, notice contains workflow_mode_changed and plan
  - after /build: previous=plan, notice contains workflow_mode_changed and build
  - a project write after the switch succeeds (enforcement follows the notice)
"""
import json, os, subprocess, sys, threading, time

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
SESSION_GLOB = os.path.join(AGENT_DIR, "sessions",
    "--" + CWD.lstrip("/").replace("/", "-") + "--", "*.jsonl")
TRACE = os.environ.get("PI_TEST_TRACE") or os.path.join(os.environ.get("TMPDIR", "/tmp"), "wf-mode-trace.jsonl")
PROBE = os.path.join(CWD, "transition-probe.md")
for path in (TRACE, PROBE):
    try: os.remove(path)
    except OSError: pass

env = dict(os.environ, PI_WORKFLOW_MODES_TRACE=TRACE)

class Session:
    def __init__(self):
        self.p = subprocess.Popen(
            ["pi", "--mode", "rpc", "--approve", "--model", TEST_MODEL],
            cwd=CWD, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
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

def trace_lines():
    if not os.path.exists(TRACE): return []
    out = []
    for line in open(TRACE, encoding="utf-8"):
        try: out.append(json.loads(line))
        except Exception: pass
    return out

s = Session()
time.sleep(7)
if s.p.poll() is not None:
    print("PI DIED:", s.p.stderr.read()[:800]); sys.exit(1)

s.turn("Reply with exactly: ready")
s.send({"id": 2, "type": "prompt", "message": "/plan"}); time.sleep(4)
s.turn("Reply with exactly: ready")
s.send({"id": 3, "type": "prompt", "message": "/build"}); time.sleep(4)
s.turn("Reply with exactly: ready")

lines = trace_lines()
print("trace lines:", len(lines), flush=True)
for line in lines:
    print(" ", line.get("mode"), "<-", line.get("previous"), "|", (line.get("notice") or "-")[:150], flush=True)

t_build = lines[0] if lines else {}
t_plan = lines[1] if len(lines) > 1 else {}
t_back = lines[2] if len(lines) > 2 else {}

ok_build = t_build.get("mode") == "build" and not t_build.get("notice")
ok_plan = (
    t_plan.get("mode") == "plan" and t_plan.get("previous") == "build"
    and "workflow_mode_changed" in (t_plan.get("notice") or "")
    and 'to="plan"' in (t_plan.get("notice") or "")
)
ok_back = (
    t_back.get("mode") == "build" and t_back.get("previous") == "plan"
    and "workflow_mode_changed" in (t_back.get("notice") or "")
    and 'to="build"' in (t_back.get("notice") or "")
)
print("T1 first build turn clean:", ok_build, flush=True)
print("T2 plan transition notice:", ok_plan, flush=True)
print("T3 build transition notice:", ok_back, flush=True)

s.turn("Use the write tool exactly once to create transition-probe.md containing x. Report the raw result briefly.")
print("T4 write after switch to build:", os.path.exists(PROBE), flush=True)

s.stop()
time.sleep(1)
print("PASS" if ok_build and ok_plan and ok_back and os.path.exists(PROBE) else "FAIL", flush=True)
try: os.remove(PROBE)
except OSError: pass
