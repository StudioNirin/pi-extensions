"""02-resume-and-gate: plan mode survives session close+--continue, and the
user_bash gate (!cmd / RPC bash path) blocks writes in plan mode.

Pass criteria:
  - phase1 session file ends with active_agent entry 'plan'
  - RESUMED TOOLS: only read-only names (expect `read, bash`)
  - gate touch rpc: blocked output (exitCode 126), no /tmp/wf-gate-probe file
  - read-only passthrough exit: 0
"""
import json, subprocess, threading, time, os, glob

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
SESSION_GLOB = os.path.join(AGENT_DIR, "sessions",
    "--" + CWD.lstrip("/").replace("/", "-") + "--", "*.jsonl")
MODEL = ["--model", TEST_MODEL]
TOOLS = "Without using any tools, reply with ONLY a plain comma-separated list of the tool names available to you in this session."
probe = "/tmp/wf-gate-probe"
try: os.remove(probe)
except: pass

class S:
    def __init__(self, extra=[]):
        self.p = subprocess.Popen(["pi","--mode","rpc","--approve"]+MODEL+extra, cwd=CWD,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines=[]
        threading.Thread(target=self.read, daemon=True).start()
    def read(self):
        for l in self.p.stdout: self.lines.append(l.strip())
    def send(self, o):
        try: self.p.stdin.write(json.dumps(o)+"\n"); self.p.stdin.flush()
        except Exception: pass
    def agent_ends(self):
        return sum(1 for l in self.lines if '"type":"agent_end"' in l or '"type": "agent_end"' in l)
    def wait_end(self, prev, timeout=240):
        t0=time.time()
        while time.time()-t0<timeout:
            if self.agent_ends()>prev: return True
            if self.p.poll() is not None: return False
            time.sleep(0.5)
        return False
    def response(self, rid):
        for l in self.lines:
            try: d=json.loads(l)
            except: continue
            if d.get("type")=="response" and d.get("id")==rid: return d
        return None
    def texts(self):
        out=[]
        for l in self.lines:
            try: d=json.loads(l)
            except: continue
            m=d.get("message")
            if isinstance(m,dict) and m.get("role")=="assistant":
                t="".join(c.get("text","") for c in m.get("content",[]) if isinstance(c,dict))
                if t.strip(): out.append(t.strip()[:250])
        return out
    def stop(self): self.p.terminate()

# Phase 1: fresh session, /plan, one real turn (flush entries to disk), stop
s=S(); s.send({"id":1,"type":"get_state"}); time.sleep(6)
s.send({"id":2,"type":"prompt","message":"/plan"}); time.sleep(3)
prev=s.agent_ends()
s.send({"id":3,"type":"prompt","message":"Reply with exactly: OK"})
s.wait_end(prev)
time.sleep(2); s.stop(); time.sleep(2)

files=sorted(glob.glob(SESSION_GLOB), key=os.path.getmtime)
latest=files[-1]
ents=[]
for l in open(latest,encoding="utf-8",errors="replace"):
    if '"active_agent"' in l:
        try: ents.append(json.loads(l)["data"]["name"])
        except: pass
print("phase1 session:", os.path.basename(latest), "entries:", ents)

# Phase 2: resume -> expect read-only tools
s2=S(extra=["--continue"]); s2.send({"id":1,"type":"get_state"}); time.sleep(7)
if s2.p.poll() is not None:
    print("RESUME DIED:", s2.p.stderr.read()[:400]); raise SystemExit(1)
prev=s2.agent_ends()
s2.send({"id":2,"type":"prompt","message":TOOLS})
print("resume turn:", s2.wait_end(prev))
t=s2.texts(); print("RESUMED TOOLS >>", t[-1] if t else "?")

# Phase 3: user_bash gate in resumed plan session (RPC bash == !cmd path)
s2.send({"id":9,"type":"bash","command":"touch /tmp/wf-gate-probe"}); time.sleep(4)
r=s2.response(9)
print("gate touch rpc:", json.dumps(r)[:220] if r else "?")
print("gate probe file created?", os.path.exists(probe))
s2.send({"id":10,"type":"bash","command":"ls /tmp | head -2"}); time.sleep(4)
r2=s2.response(10)
print("read-only passthrough exit:", (r2 or {}).get("data",{}).get("exitCode","?"))
s2.stop()
try: os.remove(probe)
except: pass
print("done")
