"""11-user-bash-gate: the `!cmd` / RPC-bash gate in plan mode.

pi-permission-system registers no user_bash handler, so pi-workflow-modes'
commandIsReadOnly() is the only check on a user-initiated `!cmd`. 0.4.1
tightened it: wrappers (env), positional writers (uniq IN OUT), sed scripts,
git subcommand mutations (branch/tag/remote add), --output on git, date -s,
file -C, single `&` backgrounding, and newline-separated units are blocked,
while the ordinary readers stay allowed.

Assertion style: a blocked unit returns exit 126 with the gate's message; an
allowed unit runs and returns its own exit code (which may be non-zero when
git has no repo here, so "allowed" means "not 126"). Side-effect files double
as ground truth for the writers that would otherwise run.

Pass criteria in printed output: every case PASS, and FAILS: none.
"""
import json, os, subprocess, threading, time

CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
MARK = "WF11MARKER"

a_txt = os.path.join(CWD, "wf11-a.txt")
side = {name: os.path.join(CWD, f"wf11-{name}") for name in (
    "uniq", "sort", "magic", "env", "bg", "nl", "tee", "gitout", "sed",
)}

def cleanup():
    for path in (a_txt, *side.values()):
        try: os.remove(path)
        except: pass

cleanup()
open(a_txt, "w").write(f"alpha {MARK}\nalpha {MARK}\nbeta\n")

class S:
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
        try:
            self.p.stdin.write(json.dumps(obj) + "\n"); self.p.stdin.flush()
        except Exception: pass
    def response(self, rid):
        for line in self.lines:
            try: d = json.loads(line)
            except: continue
            if d.get("type") == "response" and d.get("id") == rid: return d
        return None
    def run(self, rid, command):
        self.send({"id": rid, "type": "bash", "command": command})
        deadline = time.time() + 30
        while time.time() < deadline:
            r = self.response(rid)
            if r is not None: return r.get("data", {})
            time.sleep(0.3)
        return {}

fails = []
def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f" | {detail}" if detail else ""), flush=True)
    if not ok: fails.append(name)

s = S()
s.send({"id": 1, "type": "get_state"}); time.sleep(6)
if s.p.poll() is not None:
    print("PI DIED AT START"); print(s.p.stderr.read()[:800]); raise SystemExit(1)
s.send({"id": 2, "type": "prompt", "message": "/plan"}); time.sleep(4)

def allowed(rid, command):
    data = s.run(rid, command)
    code = data.get("exitCode")
    check(f"allow: {command}", code != 126, f"exit {code}")

def blocked(rid, command, side_path=None):
    data = s.run(rid, command)
    code = data.get("exitCode")
    out = (data.get("output") or "")[:120].replace("\n", " ")
    ok = code == 126
    if side_path is not None:
        ok = ok and not os.path.exists(side_path)
    check(f"block: {command}", ok, f"exit {code} {out}")

rid = 100
for command in (
    "ls",
    "cat wf11-a.txt",
    "git --version",
    "git branch -v",
    "git remote -v",
    "git tag -l",
    "date +%F",
    "date -Iseconds",
    "sort wf11-a.txt",
    "find . -name wf11-a.txt",
    "cd . && ls",
):
    rid += 1; allowed(rid, command)

for command, path in (
    ("uniq wf11-a.txt wf11-uniq", side["uniq"]),
    ("uniq wf11-a.txt", None),
    ("sort -o wf11-sort wf11-a.txt", side["sort"]),
    ("sort --out=wf11-sort wf11-a.txt", side["sort"]),
    ("file -C -m wf11-magic", side["magic"]),
    ("date -s 2020-01-01", None),
    ("git tag wf11tag", None),
    ("git branch wf11branch", None),
    ("git remote add wf11 https://example.invalid/x", None),
    ("git log --output=wf11-gitout", side["gitout"]),
    ("env touch wf11-env", side["env"]),
    ("sed -n w wf11-sed wf11-a.txt", side["sed"]),
    ("sleep 0.1 & touch wf11-bg", side["bg"]),
    ("ls\n touch wf11-nl", side["nl"]),
    ("ls | tee wf11-tee", side["tee"]),
):
    rid += 1; blocked(rid, command, path)

s.p.terminate()
cleanup()
print("FAILS:", fails if fails else "none", flush=True)
print("done")
raise SystemExit(1 if fails else 0)
