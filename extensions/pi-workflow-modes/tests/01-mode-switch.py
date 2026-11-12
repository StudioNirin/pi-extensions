"""01-mode-switch: /plan applies the carve-out tool set mid-session; /build restores.

Pass criteria in printed output:
  - turn1 tools (after /plan): write/edit/subagent remain reachable (the
    carve-out is path-checked in the blocker, not removed); ask removal is
    covered by 05
  - turn2 tools (after /build): full set incl. write/edit/subagent
  - session entries end with ('active_agent', plan) then ('active_agent', build)
"""
import json, subprocess, sys, threading, time, glob, os

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
SESSION_GLOB = os.path.join(AGENT_DIR, "sessions",
    "--" + CWD.lstrip("/").replace("/", "-") + "--", "*.jsonl")
MODEL = ["--model", TEST_MODEL]
PROMPT = "Without using any tools, reply with ONLY a plain comma-separated list of the tool names available to you in this session."

p = subprocess.Popen(["pi", "--mode", "rpc", "--approve"] + MODEL,
    cwd=CWD, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

out_lines = []
def reader():
    for line in p.stdout:
        out_lines.append(line.strip())
threading.Thread(target=reader, daemon=True).start()

def send(obj):
    p.stdin.write(json.dumps(obj) + "\n"); p.stdin.flush()

def count_agent_ends():
    return sum(1 for l in out_lines if '"type":"agent_end"' in l or '"type": "agent_end"' in l)

def wait_agent_end(prev, timeout=200):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if count_agent_ends() > prev: return True
        if p.poll() is not None: return False
        time.sleep(0.5)
    return False

def disposition_for(rid):
    for l in out_lines:
        try: d = json.loads(l)
        except Exception: continue
        if d.get("type") == "response" and d.get("id") == rid:
            return d.get("data", {}).get("disposition") or ("success" if d.get("success") else "fail")
    return None

send({"id": 1, "type": "get_state"}); time.sleep(6)
if p.poll() is not None:
    print("PI DIED AT START"); print(p.stderr.read()[:1500]); sys.exit(1)

send({"id": 2, "type": "prompt", "message": "/plan"}); time.sleep(4)
print("disposition /plan:", disposition_for(2))

prev = count_agent_ends()
send({"id": 3, "type": "prompt", "message": PROMPT})
ok1 = wait_agent_end(prev); print("turn1 end:", ok1)

prev = count_agent_ends()
send({"id": 4, "type": "prompt", "message": "/build"}); time.sleep(4)
print("disposition /build:", disposition_for(4))
send({"id": 5, "type": "prompt", "message": PROMPT})
ok2 = wait_agent_end(prev); print("turn2 end:", ok2)

time.sleep(2)
p.terminate()
err = p.stderr.read()
if err.strip(): print("STDERR:", err[:800])

tools_msgs = []
for l in out_lines:
    try: d = json.loads(l)
    except Exception: continue
    m = d.get("message") or (d if d.get("role") else None)
    if isinstance(m, dict) and m.get("role") == "assistant":
        txt = "".join(c.get("text", "") for c in m.get("content", []) if isinstance(c, dict))
        if txt.strip(): tools_msgs.append(txt.strip()[:300])
print("--- assistant tool-list texts ---")
for t in tools_msgs: print(">>", t)

files = sorted(glob.glob(SESSION_GLOB), key=os.path.getmtime)
latest = files[-1] if files else None
print("latest session file:", latest)
if latest:
    hits = []
    for l in open(latest, encoding="utf-8", errors="replace"):
        if "active_agent" in l and "custom" in l:
            try:
                d = json.loads(l)
                hits.append((d.get("customType"), d.get("data")))
            except Exception:
                hits.append(("?", l[:120]))
    print("active_agent entries:", hits)
