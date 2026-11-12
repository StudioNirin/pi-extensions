"""07-veto: the deny-only floor blocks tools and !cmd, independently of pps.

Pass criteria in printed output:
  - !dd if=/dev/zero of=/dev/null is stopped with exit 126 and a [pi-veto] reason
  - the bash tool calling `wipefs /dev/null` is blocked with a [pi-veto] reason
    (pps has no rule for wipefs, so this proves the veto is a real layer)
  - a floor.json deny.bash entry takes effect, hot-reloaded
  - a non-deny floor.json shape ("allow") is ignored
  - no permission dialog appears for any veto-covered command
"""
import json, os, shutil, subprocess, sys, threading, time

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
SESSION_GLOB = os.path.join(AGENT_DIR, "sessions",
    "--" + CWD.lstrip("/").replace("/", "-") + "--", "*.jsonl")
FLOOR = os.path.join(AGENT_DIR, "floor.json")
BACKUP = FLOOR + ".test-backup"
shutil.copyfile(FLOOR, BACKUP)

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
    def response(self, request_id):
        for line in self.lines:
            try: d = json.loads(line)
            except Exception: continue
            if d.get("type") == "response" and d.get("id") == request_id:
                return d.get("data", {})
        return None
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

def write_floor(deny_bash, extra=None):
    payload = {"deny": {"bash": deny_bash, "paths": []}}
    if extra: payload.update(extra)
    with open(FLOOR, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

def watchdog(s):
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
            DIALOGS.append(d.get("title", "")[:120])
            print(f"[DIALOG] {d.get('method')}: {d.get('title','')[:120]}", flush=True)
            s.send({"type": "extension_ui_response", "id": rid, "confirmed": False, "value": "No"})
        if s.p.poll() is not None: return
        time.sleep(0.3)

def bash_rpc(s, request_id, command):
    s.send({"id": request_id, "type": "bash", "command": command})
    t0 = time.time()
    while time.time() - t0 < 30:
        result = s.response(request_id)
        if result is not None: return result
        time.sleep(0.5)
    return {}

s = Session()
threading.Thread(target=watchdog, args=(s,), daemon=True).start()
time.sleep(7)
if s.p.poll() is not None:
    print("PI DIED:", s.p.stderr.read()[:800]); shutil.copyfile(BACKUP, FLOOR); sys.exit(1)

# --- V1: user_bash, dd to a device ---
r = bash_rpc(s, 101, "dd if=/dev/zero of=/dev/null bs=1 count=0")
v1_out = (r or {}).get("output", "")
v1 = (r or {}).get("exitCode") == 126 and "[pi-veto]" in v1_out
print("V1 !dd blocked:", v1, flush=True)

# --- V2: the bash tool, a command pps does not know ---
veto_seen = False
for attempt in (1, 2, 3):
    s.turn("Call the bash tool exactly once with: wipefs /dev/null . Report the raw result briefly.")
    veto_seen = any("[pi-veto]" in line for line in s.lines)
    print(f"V2 attempt {attempt}: veto reason seen in transcript = {veto_seen}", flush=True)
    if veto_seen: break
print("V3 no permission dialogs:", len(DIALOGS) == 0, f"(seen {len(DIALOGS)})", flush=True)

# --- V4: additive floor deny, hot-reloaded in the same process ---
write_floor(["curl *veto-probe.invalid*"])
r = bash_rpc(s, 102, "curl --max-time 1 http://veto-probe.invalid")
v4_out = (r or {}).get("output", "")
v4 = (r or {}).get("exitCode") == 126 and "floor.json" in v4_out
print("V4 floor.json additive deny:", v4, flush=True)

# --- V5: a non-deny shape is ignored (the floor is deny-only) ---
write_floor([], extra={"allow": {"bash": ["echo *"]}, "ask": {"bash": ["*"]}})
r = bash_rpc(s, 103, "echo floor-allowed")
v5 = (r or {}).get("exitCode") == 0 and "floor-allowed" in (r or {}).get("output", "")
print("V5 non-deny shapes ignored:", v5, flush=True)

s.stop()
time.sleep(1)
shutil.copyfile(BACKUP, FLOOR)
os.remove(BACKUP)
print("PASS" if (v1 and veto_seen and v4 and v5 and len(DIALOGS) == 0) else "FAIL", flush=True)
