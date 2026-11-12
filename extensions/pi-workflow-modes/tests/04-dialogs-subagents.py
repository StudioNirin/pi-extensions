import json, subprocess, threading, time, os, re, sys

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
SESSION_GLOB = os.path.join(AGENT_DIR, "sessions",
    "--" + CWD.lstrip("/").replace("/", "-") + "--", "*.jsonl")
PROBE1 = os.path.join(CWD, "pps-probe.txt")
PROBE2 = os.path.join(CWD, "pps-probe2.txt")
SCOUT = os.path.join(CWD, "scout-probe.md")
for f in (PROBE1, PROBE2, SCOUT):
    try: os.remove(f)
    except: pass

ANSWER = {"current": "Yes"}          # planned answer for the next select dialog
DIALOGS = []                          # (title, answered)
LOCK = threading.Lock()

class S:
    def __init__(self, extra=[]):
        self.p = subprocess.Popen(["pi","--mode","rpc","--approve","--model",TEST_MODEL]+extra, cwd=CWD,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        self.lines=[]; self.notices=[]; self.answered=set()
        threading.Thread(target=self.read, daemon=True).start()
    def read(self):
        for l in self.p.stdout: self.lines.append(l.strip())
    def send(self, o):
        with LOCK:
            try: self.p.stdin.write(json.dumps(o)+"\n"); self.p.stdin.flush()
            except Exception: pass
    def autorespond(self):
        idx = 0
        while True:
            while idx < len(self.lines):
                l = self.lines[idx]; idx += 1
                if '"extension_ui_request"' not in l: continue
                try: d = json.loads(l)
                except Exception: continue
                if d.get("method") == "notify":
                    self.notices.append(d.get("message",""))
                    continue
                if d.get("method") not in ("select","input","confirm"): continue
                rid = d.get("id")
                if rid in self.answered: continue
                self.answered.add(rid)
                title = (d.get("title") or "")[:160].replace("\n"," | ")
                if d.get("method") == "select":
                    val = ANSWER["current"]
                    self.send({"type":"extension_ui_response","id":rid,"value":val})
                    DIALOGS.append((title, val))
                    print(f"[DIALOG] select: {title}  -> answered: {val}", flush=True)
                elif d.get("method") == "confirm":
                    ok = ANSWER["current"] == "Yes"
                    self.send({"type":"extension_ui_response","id":rid,"confirmed":ok})
                    DIALOGS.append((title, ANSWER["current"]))
                    print(f"[DIALOG] confirm: {title}  -> {ok}", flush=True)
                else:
                    self.send({"type":"extension_ui_response","id":rid,"value":""})
                    DIALOGS.append((title, "<input empty>"))
                time.sleep(0.2)
            if self.p.poll() is not None and idx >= len(self.lines): return
            time.sleep(0.3)
    def start_responder(self):
        threading.Thread(target=self.autorespond, daemon=True).start()
    def agent_ends(self):
        return sum(1 for l in self.lines if '"type":"agent_end"' in l or '"type": "agent_end"' in l)
    def wait_end(self, prev, timeout=300):
        t0=time.time()
        while time.time()-t0<timeout:
            if self.agent_ends()>prev: return True
            if self.p.poll() is not None: return False
            time.sleep(0.5)
        return False
    def texts(self):
        out=[]
        for l in self.lines:
            try: d=json.loads(l)
            except: continue
            m=d.get("message")
            if isinstance(m,dict) and m.get("role")=="assistant":
                t="".join(c.get("text","") for c in m.get("content",[]) if isinstance(c,dict))
                if t.strip(): out.append(t.strip()[:300])
        return out
    def subagent_calls(self):
        return sum(1 for l in self.lines if '"name":"subagent"' in l or '"name": "subagent"' in l)
    def stop(self): self.p.terminate()

s = S(); s.start_responder()
s.send({"id":1,"type":"get_state"}); time.sleep(6)
if s.p.poll() is not None:
    print("PI DIED:", s.p.stderr.read()[:800]); sys.exit(1)
model_ok = False
for l in s.lines:
    if '"command":"get_state"' in l:
        try:
            mid = json.loads(l).get("data",{}).get("model",{}).get("id","")
            model_ok = mid == "Qwen3.8-Flash-Next-NVFP4"
            print("MODEL:", mid, "PIN OK" if model_ok else "WRONG MODEL", flush=True)
        except Exception: pass
        break
if not model_ok: print("ABORT: model not pinned"); s.stop(); sys.exit(1)

def turn(msg, timeout=300):
    prev = s.agent_ends()
    s.send({"id":abs(hash(msg+str(time.time()))),"type":"prompt","message":msg})
    return s.wait_end(prev, timeout)

# ---- P0: fresh-session mode readout ----
s.send({"id":2,"type":"prompt","message":"/workflow-mode"}); time.sleep(3)
mode_notice = next((n for n in s.notices if "workflow mode" in n), "?")
print("P0 workflow-mode notice:", mode_notice, flush=True)

# ---- P1: ask dialog, APPROVE ----
turn("Call the bash tool exactly once with this command and report the raw result: touch pps-probe.txt")
print("P1a touch allowed silently, file exists:", os.path.exists(PROBE1), flush=True)
n_dialog_before = len(DIALOGS)
ANSWER["current"] = "Yes"
turn("Call the bash tool exactly once with this command and report the raw result: rm -f pps-probe.txt")
p1_dialogs = len(DIALOGS) - n_dialog_before
print("P1b rm: dialogs seen:", p1_dialogs, "| file gone:", not os.path.exists(PROBE1), flush=True)

# ---- P2: ask dialog, DENY ----
turn("Call the bash tool exactly once with this command and report the raw result: touch pps-probe2.txt")
n_dialog_before = len(DIALOGS)
ANSWER["current"] = "No"
turn("Call the bash tool exactly once with this command and report the raw result: rm -f pps-probe2.txt")
p2_dialogs = len(DIALOGS) - n_dialog_before
print("P2 rm denied via dialog: dialogs seen:", p2_dialogs, "| file still exists:", os.path.exists(PROBE2), flush=True)
# cleanup through the user_bash RPC path (build mode passes it)
s.send({"id":90,"type":"bash","command":"rm -f pps-probe2.txt"}); time.sleep(3)
print("P2 cleanup via rpc bash, file gone:", not os.path.exists(PROBE2), flush=True)

# ---- P3: worker forwarded approval (retry for model cooperation) ----
WORKER_PROMPTS = [
 'Use the subagent tool ONCE with subagent_type worker. Its prompt: "Run exactly this bash command: sh -c \'echo hi-worker\'. Report the output." Wait for the result and relay it.',
 'Call the tool named "subagent" directly - do not use bash first. subagent_type: worker. prompt: "Run exactly: sh -c \'echo hi-worker\'. Report the output." description: "worker echo". Wait for the result and relay the output verbatim.',
]
ANSWER["current"] = "Yes"
worker_ok = False
for attempt in (1,2,3,4):
    nd = len(DIALOGS); nc = s.subagent_calls()
    ok = turn(WORKER_PROMPTS[(attempt-1) % 2], timeout=340)
    t = s.texts()
    relayed = any("hi-worker" in x for x in t[-2:]) if t else False
    fwd = any("Subagent" in d[0] for d in DIALOGS[nd:])
    real = s.subagent_calls() > nc
    print(f"P3 attempt {attempt}: turn_end={ok} real_subagent_call={real} fwd_dialog={fwd} relayed={relayed}", flush=True)
    if real and relayed:
        worker_ok = True; break
print("P3 worker forwarding:", "PASS" if worker_ok else "FAIL", flush=True)

# ---- P4: scout child cannot write ----
for f in (SCOUT,): 
    try: os.remove(f)
    except: pass
SCOUT_PROMPTS = [
 'Use the subagent tool ONCE with subagent_type scout. Its prompt: "Write the word hi into scout-probe.md using your write tool, then report what happened." Relay its report.',
 'Call the tool named "subagent" directly - do not use bash. subagent_type: scout. prompt: "Write the word hi into scout-probe.md using your write tool, then report what happened." description: "scout write test". Wait for the result and relay its report in one sentence.',
]
scout_ok = False
for attempt in (1,2,3,4):
    nc = s.subagent_calls()
    ok = turn(SCOUT_PROMPTS[(attempt-1) % 2], timeout=340)
    real = s.subagent_calls() > nc
    print(f"P4 attempt {attempt}: turn_end={ok} real_subagent_call={real} scout file exists={os.path.exists(SCOUT)}", flush=True)
    if real:
        scout_ok = not os.path.exists(SCOUT); break
print("P4 scout write-blocked:", "PASS" if scout_ok else "FAIL", flush=True)

print("== ALL DIALOGS SEEN ==")
for t in DIALOGS: print(" >>", t)
print("== notices ==", [n[:90] for n in s.notices if n][:6])
s.stop()
print("DONE")
