"""14-tps-meters: the footer throughput meters stay floating, silent on tools,
and readable.

Why this is a test: the meters are two floating npm packages
(npm:pi-token-speed, npm:pi-token-rate), not code in this repo, so a bump can
change their behaviour without any diff here to review. The complaints this
scenario encodes are the ones that made us drop a hand-rolled meter: a readout
that redraws on every delta, one whose width changes as the digits change, one
whose number swings wildly, and one that quietly starts registering a tool.

The meters are observed through the RPC `extension_ui_request` stream, which
carries `setStatus` as a plain string. `setWidget` only carries string arrays
in RPC mode (component factories are ignored, rpc-extension-ui.md), and
pi-token-rate ships a component factory, so it is deliberately NOT sampled
here: its check is that it loads clean and stays quiet. In the CLI TUI and in
PiChamber (whose bridge renders function components through a tuiStub) it does
draw; that half is a manual look.

Pass criteria in printed output:
  - P1 each meter installed floating from its expected source (pi-token-speed
    must be the StudioNirin fork, not the npm build; see P3)
  - P2 neither registers a tool, and no loose copy shadows them
  - M1 the setStatus meter produced at least 5 samples during a streamed turn
  - M2 its peak redraw rate stayed at or under 15 updates in any one second
  - M3 its mid-stream number did not jump more than 45% of the observed range
    (the end-of-turn frame is excluded: it legitimately carries the reconciled
    average, and M5 judges it instead)
  - M4 the rate part of its line, everything up to "tok/s", took at most 8
    distinct widths. With the meter configured display=full the whole line
    legitimately changes length as token and elapsed digits change, so the total
    is printed without a verdict
  - M5 the final frame's token count equals the session file's usage.output
    total: the end-to-end gate for the fork's forced end-of-turn render
  - N1 pi-token-rate loaded without an extension error and drew nothing over RPC
"""
import json, os, re, subprocess, sys, threading, time

AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
SETTINGS = os.path.join(AGENT_DIR, "settings.json")
NPM_DIR = os.path.join(AGENT_DIR, "npm", "node_modules")
CWD = os.path.realpath(os.environ.get("PI_TEST_CWD") or os.path.expanduser("~"))
TEST_MODEL = os.environ.get("PI_TEST_MODEL", "basalt/Qwen3.8-Flash-Next-NVFP4")
MODEL = ["--model", TEST_MODEL]

STATUS_KEY = "tokenSpeed"          # pi-token-speed: src/config/constants.ts
WIDGET_KEY = "token-rate-spark"    # pi-token-rate: index.ts
METERS = ("pi-token-speed", "pi-token-rate")
# pi-token-speed is a fork: the npm build drops the reconciled end-of-turn
# frame so the footer shows a stale count (gsanhueza/pi-token-speed#20). The
# meter must come from the fork and float on its default branch, never pin.
SOURCE_SPEC = {
    "pi-token-speed": "git:github.com/StudioNirin/pi-token-speed",
    "pi-token-rate": "npm:pi-token-rate",
}
INSTALL_ROOT = {
    "pi-token-speed": os.path.join(AGENT_DIR, "git", "github.com", "StudioNirin", "pi-token-speed"),
    "pi-token-rate": os.path.join(NPM_DIR, "pi-token-rate"),
}
MAX_UPDATES_PER_SEC = 15
MAX_JITTER_FRACTION = 0.45
MAX_DISTINCT_WIDTHS = 8
WARMUP_SAMPLES = 5
COUNT_PROMPT = "Without using any tools, count from 1 to 150, each number on its own line."

ok = True
def check(label, condition, detail=""):
    global ok
    ok = ok and bool(condition)
    print(f"{label}: {'PASS' if condition else 'FAIL'} {detail}".rstrip(), flush=True)
def info(label, detail=""):
    print(f"{label}: INFO {detail}".rstrip(), flush=True)

# --- P1 floating install policy -------------------------------------------------
settings = json.load(open(SETTINGS, encoding="utf-8"))
packages = [e if isinstance(e, str) else e.get("source", "") for e in settings.get("packages", [])]
for meter in METERS:
    spec = SOURCE_SPEC[meter]
    entries = [e for e in packages if e == spec or e.startswith(spec + "@")]
    floating_only = [e for e in entries if e == spec]
    check(f"P1 {meter} installed floating from {spec}", bool(entries) and bool(floating_only),
          f"entries={entries}")

# --- P2 no tool surface, no shadowing ------------------------------------------
for meter in METERS:
    root = INSTALL_ROOT[meter]
    registers = False
    if os.path.isdir(root):
        for dirpath, _, files in os.walk(root):
            if "node_modules" in dirpath:
                continue
            for name in files:
                if name.endswith((".ts", ".js", ".mjs", ".cjs")) and not name.endswith(".d.ts"):
                    try:
                        text = open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read()
                    except OSError:
                        continue
                    if re.search(r"registerTool\s*\(|\btools\s*:\s*\[", text):
                        registers = True
    check(f"P2 {meter} registers no tool", os.path.isdir(root) and not registers,
          "installed" if os.path.isdir(root) else "MISSING")
loose = [os.path.join(AGENT_DIR, "extensions", m) for m in METERS if os.path.exists(os.path.join(AGENT_DIR, "extensions", m))]
check("P2 no loose meter dirs", not loose, f"found={loose}")

# --- P3 installed meter carries the end-of-turn render fix ----------------------
# The whole reason pi-token-speed is a fork. handleAgentEnd must render with the
# throttle bypassed, or the reconciled final frame is dropped and the footer
# understates the turn (gsanhueza/pi-token-speed#20). If pi is ever repointed at
# the npm build, or the fork branch loses the commit, this catches it.
events_src = os.path.join(INSTALL_ROOT["pi-token-speed"], "src", "core", "events.ts")
try:
    events_text = open(events_src, encoding="utf-8").read()
except OSError:
    events_text = ""
check("P3 installed meter forces the end-of-turn render",
      "renderer.update(ctx, true)" in events_text, events_src)

# --- M1..M4 observe one streamed turn -----------------------------------------
class Session:
    def __init__(self):
        self.p = subprocess.Popen(["pi", "--mode", "rpc", "--approve"] + MODEL, cwd=CWD,
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, bufsize=1)
        self.rows = []      # (arrival, parsed json)
        self.stderr_text = ""
        threading.Thread(target=self.read, daemon=True).start()
        threading.Thread(target=self.drain, daemon=True).start()

    def read(self):
        for line in self.p.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.rows.append((time.perf_counter(), json.loads(line)))
            except json.JSONDecodeError:
                self.rows.append((time.perf_counter(), None))

    def drain(self):
        self.stderr_text = self.p.stderr.read() or ""

    def send(self, obj):
        try:
            self.p.stdin.write(json.dumps(obj) + "\n")
            self.p.stdin.flush()
        except Exception:
            pass

    def agent_ends(self):
        return sum(1 for _, d in self.rows if isinstance(d, dict) and d.get("type") == "agent_end")

    def wait_end(self, prev, timeout=300):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if self.agent_ends() > prev:
                return True
            if self.p.poll() is not None:
                return False
            time.sleep(0.5)
        return False

    def stop(self):
        self.p.terminate()

# The session file for this run, to hold the meter to the provider's own count.
# Bucket directory naming: cwd with "/" replaced by "-", wrapped in double dashes.
SESSION_BUCKET = os.path.join(AGENT_DIR, "sessions", "--" + CWD.strip("/").replace("/", "-") + "--")
try:
    SESSIONS_BEFORE = set(os.listdir(SESSION_BUCKET))
except OSError:
    SESSIONS_BEFORE = set()

s = Session()
s.send({"id": 1, "type": "get_state"})
time.sleep(6)
prev = s.agent_ends()
s.send({"id": 2, "type": "prompt", "message": COUNT_PROMPT})
streamed = s.wait_end(prev)
time.sleep(2)
s.stop()
time.sleep(1)
stderr_text = s.stderr_text

def texts_for(method, key_field, key_value):
    out = []
    for arrival, d in s.rows:
        if not isinstance(d, dict) or d.get("type") != "extension_ui_request":
            continue
        if d.get("method") != method or d.get(key_field) != key_value:
            continue
        value = d.get("statusText") or d.get("widgetLines")
        if isinstance(value, list):
            value = "\n".join(str(v) for v in value)
        if isinstance(value, str) and value:
            out.append((arrival, value))
    return out

samples = texts_for("setStatus", "statusKey", STATUS_KEY)
widgets = texts_for("setWidget", "widgetKey", WIDGET_KEY)
info("turn", f"agent_end={streamed} setStatus samples={len(samples)} setWidget samples={len(widgets)}")

check("M1 meter redrew during the turn", len(samples) >= 5, f"samples={len(samples)}")

if len(samples) >= 2:
    span = samples[-1][0] - samples[0][0]
    # Peak redraw rate, not the average: an unthrottled meter hides in an
    # average taken across a turn that mostly spent its time not streaming.
    peak = max(sum(1 for b in samples if 0 <= b[0] - a[0] < 1.0) for a in samples)
    check("M2 redraw throttled", peak <= MAX_UPDATES_PER_SEC,
          f"peak updates/s={peak} limit={MAX_UPDATES_PER_SEC} ({len(samples)} over {span:.1f}s)")
else:
    check("M2 redraw throttled", False, "too few samples to measure")

RATE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*tok/s")
COUNT_RE = re.compile(r"(\d+) tok in")
ANSI = re.compile(r"\x1b\[[0-9;]*m")
rates = [(t, float(RATE_RE.search(v).group(1)), v) for t, v in samples if RATE_RE.search(v)]
if len(rates) > WARMUP_SAMPLES + 1:
    # Last frame excluded on purpose: it is the end-of-turn render, where
    # reconcileTotal snaps the total to provider usage and endTpsBehavior
    # "average" legitimately differs from the sliding-window mid-stream value.
    # M3 judges mid-stream smoothness; M5 judges that final frame's accuracy.
    warm = rates[WARMUP_SAMPLES:-1]
    deltas = [abs(b[1] - a[1]) for a, b in zip(warm, warm[1:])]
    span_range = max(r[1] for r in warm) - min(r[1] for r in warm)
    worst = max(deltas) if deltas else 0.0
    limit = MAX_JITTER_FRACTION * max(span_range, 1.0)
    check("M3 readout did not swing", worst <= limit,
          f"max jump={worst:.1f} tok/s limit={limit:.1f} range={span_range:.1f} min={min(r[1] for r in warm):.1f} max={max(r[1] for r in warm):.1f}")
    def segment(value):
        # The part of the line whose length should not move as a side effect of
        # the number itself: everything up to and including "tok/s".
        clean = ANSI.sub("", value)
        cut = clean.find("tok/s")
        return clean[: cut + 5] if cut >= 0 else clean
    widths = sorted({len(segment(r[2])) for r in rates})
    check("M4 rate display width steady", len(widths) <= MAX_DISTINCT_WIDTHS,
          f"distinct widths={len(widths)} {widths[:12]}")
    # display=full legitimately changes the total length: the token count and
    # elapsed digits are content, not jitter. Report it, judge nothing.
    info("M4 full line widths (no verdict)",
         str(sorted({len(ANSI.sub("", r[2])) for r in rates})[:12]))
    info("M3/M4 sample", ANSI.sub("", rates[len(rates) // 2][2])[:120])
else:
    check("M3 readout did not swing", False, f"parsable tok/s samples={len(rates)}")
    check("M4 rendered width steady", False, "no parsable samples")

# --- M5 the final frame carries the reconciled turn total ------------------------
# The fork's reason to exist (gsanhueza/pi-token-speed#20). Without the forced
# end-of-turn render this comparison reads a mid-stream snapshot: measured
# 703/890 and 474/629 on the npm build at the shipped 80 ms interval, versus
# exact matches with the throttle off. Now that the fork publishes the frame,
# the last token count shown must equal the session file's usage.output sum.
final_tok = None
for _, v in reversed(samples):
    m = COUNT_RE.search(ANSI.sub("", v))
    if m:
        final_tok = int(m.group(1))
        break
auth_total = None
try:
    new_sessions = [f for f in sorted(os.listdir(SESSION_BUCKET)) if f not in SESSIONS_BEFORE]
except OSError:
    new_sessions = []
if new_sessions:
    auth_total = 0
    with open(os.path.join(SESSION_BUCKET, new_sessions[-1]), encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = d.get("message") or d
            if msg.get("role") == "assistant" and isinstance((msg.get("usage") or {}).get("output"), (int, float)):
                auth_total += msg["usage"]["output"]
check("M5 final frame matches usage.output",
      final_tok is not None and auth_total is not None and final_tok == auth_total,
      f"final={final_tok} usage_output={auth_total}")

# --- N1 pi-token-rate loads clean and stays invisible over RPC -----------------
errors = re.findall(r"(?i)(pi-token-rate|token-rate-spark)[^\n]{0,120}(error|failed|throw)", stderr_text)
check("N1 pi-token-rate loaded without error", not errors, f"matches={errors[:2]}")
check("N1 pi-token-rate silent over RPC", not widgets,
      "component factories are ignored in RPC mode, so no widget payload is correct")
if stderr_text.strip():
    info("stderr", stderr_text.strip()[:200].replace("\n", " | "))

print("PASS" if ok else "FAIL", flush=True)
sys.exit(0 if ok else 1)
