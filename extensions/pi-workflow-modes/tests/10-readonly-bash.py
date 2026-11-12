"""10-readonly-bash: read-only compound bash works in plan mode, and flags
that turn readers into writers/executors do not (0.4.0 gate hardening).

Two paths, both in plan mode:
  A. assistant bash (tool calls, pps persona patterns govern)
     A1 `cd <cwd> && echo && grep` runs (the cd/printf persona fix)
     A2 find ... -delete must NOT delete the probe
     A3 rg --pre must NOT execute the preprocessor
     A4 $(touch ...) substitution must NOT run
  B. !cmd (RPC bash message, pi-workflow-modes commandIsReadOnly governs)
     U1 cd+grep passthrough, exit 0
     U2 find -delete blocked, probe intact
     U3 rg --pre blocked, preprocessor marker absent
     U4 sed -n -i blocked, file not rewritten (old gate passed this)
     U5 echo && touch blocked, no file

Assertions are security invariants (files intact, markers absent), not
deny-message text: they pin the end-to-end behaviour of pps + personas + our
gate regardless of which layer denies.
"""
import json, subprocess, threading, time, os, stat

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
MODEL = ["--model", TEST_MODEL]

a_txt = os.path.join(CWD, "wf10-a.txt")
b_txt = os.path.join(CWD, "wf10-b.txt")
c_txt = os.path.join(CWD, "wf10-c.txt")
pre_sh = os.path.join(CWD, "wf10-pre.sh")
pre_ran = os.path.join(CWD, "wf10-pre-ran")
sub_ran = os.path.join(CWD, "wf10-sub-ran")
touch_ran = os.path.join(CWD, "wf10-touch-ran")

def cleanup():
    for f in (a_txt, b_txt, c_txt, pre_sh, pre_ran, sub_ran, touch_ran):
        try: os.remove(f)
        except: pass

cleanup()
open(a_txt, "w").write("alpha RO10MARKER line\n")
open(b_txt, "w").write("beta RO10MARKER line\n")
open(c_txt, "w").write("gamma RO10MARKER line\n")
open(pre_sh, "w").write(f'#!/bin/sh\ntouch "{pre_ran}"\ncat "$1"\n')
os.chmod(pre_sh, os.stat(pre_sh).st_mode | stat.S_IXUSR | stat.S_IXGRP)

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
    def stop(self): self.p.terminate()

RUN = "You MUST use the bash tool exactly once to run this command verbatim, then reply DONE. Run nothing else and write nothing yourself. If it fails, still reply DONE with the error. Command: {}"
fails = []
def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""))
    if not ok: fails.append(name)

s = S()
s.send({"id":1,"type":"get_state"}); time.sleep(6)
if s.p.poll() is not None:
    print("PI DIED AT START"); print(s.p.stderr.read()[:800]); raise SystemExit(1)
s.send({"id":2,"type":"prompt","message":"/plan"}); time.sleep(3)

# ---- A: assistant bash, plan persona ----
mark = len(s.lines); prev = s.agent_ends()
s.send({"id":11,"type":"prompt","message":RUN.format(
    f"cd {CWD} && echo WF10-OK && grep -c RO10MARKER wf10-a.txt")})
s.wait_end(prev); seg = "\n".join(s.lines[mark:])
check("A1 cd+echo+grep ran", "WF10-OK" in seg and "Denied by policy" not in seg)

mark = len(s.lines); prev = s.agent_ends()
s.send({"id":12,"type":"prompt","message":RUN.format(
    f"find . -name wf10-b.txt -delete")})
s.wait_end(prev)
check("A2 find -delete did not delete", os.path.exists(b_txt))

mark = len(s.lines); prev = s.agent_ends()
s.send({"id":13,"type":"prompt","message":RUN.format(
    f"rg --pre {pre_sh} RO10MARKER wf10-a.txt")})
s.wait_end(prev)
check("A3 rg --pre did not execute", not os.path.exists(pre_ran))

mark = len(s.lines); prev = s.agent_ends()
s.send({"id":14,"type":"prompt","message":RUN.format(
    "grep -c RO10MARKER wf10-a.txt $(touch wf10-sub-ran)")})
s.wait_end(prev)
check("A4 $(touch) substitution did not run", not os.path.exists(sub_ran))

# ---- B: !cmd / rpc bash, workflow-modes gate ----
s.send({"id":91,"type":"bash","command":f"cd {CWD} && grep RO10MARKER wf10-a.txt"}); time.sleep(4)
r = s.response(91) or {}
check("U1 rpc cd+grep exit 0", r.get("data",{}).get("exitCode") == 0,
      json.dumps(r)[:160])

s.send({"id":92,"type":"bash","command":"find . -name wf10-b.txt -delete"}); time.sleep(4)
s.response(92)
check("U2 rpc find -delete blocked", os.path.exists(b_txt))

s.send({"id":93,"type":"bash","command":f"rg --pre {pre_sh} RO10MARKER wf10-a.txt"}); time.sleep(4)
s.response(93)
check("U3 rpc rg --pre not executed", not os.path.exists(pre_ran))

s.send({"id":94,"type":"bash","command":"sed -n -i s/RO10MARKER/x/ wf10-c.txt"}); time.sleep(4)
s.response(94)
check("U4 rpc sed -n -i did not rewrite", "RO10MARKER" in open(c_txt).read())

s.send({"id":95,"type":"bash","command":"echo hi && touch wf10-touch-ran"}); time.sleep(4)
s.response(95)
check("U5 rpc echo && touch blocked", not os.path.exists(touch_ran))

s.stop()
cleanup()
print("FAILS:", fails if fails else "none")
print("done")
raise SystemExit(1 if fails else 0)
