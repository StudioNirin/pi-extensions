"""10-opencode-free-sidecar: Zen provider + Bun transport relay, end to end.

Why this is a test: this extension replaces the npm
@rabden/pi-opencode-zen (it must NOT coexist with it in settings), vendors
its provider, and defaults the Zen base URL to a loopback Bun relay. Three
contracts matter:

  A. live-config: our package loaded, no @rabden copy shadowing it, and the
     opencode-zen provider is pointed at the loopback relay with the token
     header wired (install.sh / self-heal product);
  B. relay.js: open GETs, token-gated writes, idle self-exit, single
     instance;
  C. extension load contract: with an isolated agent dir, starting pi
     spawns the relay, registers the provider (dynamic import AFTER the
     module-scope env default; if that ordering broke, requests would go
     straight to opencode.ai and never appear in the relay access log),
     survives a killed relay via the fetch guard, and carries the token.

C uses one live Zen round trip (a few seconds, like scenarios 05/07).
Environment: standard suite vars. Skip notes print if bun is unavailable.
"""
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.path.dirname(HERE)
REPO_DIR = os.path.abspath(os.path.join(EXT_DIR, "..", ".."))
LIVE_AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
VENDOR_FILES = ["index.ts", "marker.ts", "models-meta.ts", "stream.ts", "LICENSE"]

BUN = os.environ.get("PI_ZEN_RELAY_BUN") or os.path.expanduser("~/.local/bin/bun")
if not os.path.exists(BUN):
    BUN = shutil.which("bun")

ok = True


def check(label, condition, extra=""):
    global ok
    print(f"{label}: {bool(condition)}{' ' + extra if extra else ''}", flush=True)
    ok = ok and bool(condition)


def get(url, headers=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", "replace")


def post(url, body, headers=None, timeout=20):
    req = urllib.request.Request(url, data=body.encode(), headers=headers or {}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# A. live config contract (no subprocesses)
# ---------------------------------------------------------------------------
settings = json.load(open(os.path.join(LIVE_AGENT_DIR, "settings.json"), encoding="utf-8"))


def resolves_here(source):
    if not source or ":" in source.split("/")[0]:
        return False
    if not os.path.isabs(source):
        source = os.path.join(LIVE_AGENT_DIR, source)
    return os.path.realpath(source) == os.path.realpath(REPO_DIR)


pkg_sources = [e if isinstance(e, str) else e.get("source", "") for e in settings.get("packages", [])]
ours = [s for s in pkg_sources if resolves_here(s)]
rabden = [s for s in pkg_sources if "pi-opencode-zen" in s]
check("A1 our package in settings", ours, str(pkg_sources))
check("A2 no @rabden/pi-opencode-zen to shadow it", not rabden, str(rabden))
check("A3 vendor files present", all(os.path.exists(os.path.join(EXT_DIR, "vendor", "pi-opencode-zen", f)) for f in VENDOR_FILES))

models_path = os.path.join(LIVE_AGENT_DIR, "models.json")
try:
    live_models = json.load(open(models_path, encoding="utf-8"))
except FileNotFoundError:
    live_models = {}
zen = live_models.get("providers", {}).get("opencode-zen", {})
base_url = str(zen.get("baseUrl", ""))
check("A4 live baseUrl is loopback", base_url.startswith("http://127.0.0.1:"), base_url)
check("A5 live token header wired", "x-zen-relay-token" in zen.get("headers", {}), str(list(zen.get("headers", {}))))
stray = os.path.expanduser("~/.local/share/zen-sidecar")
unit = os.path.expanduser("~/.config/systemd/user/zen-sidecar.service")
check("A6 legacy zen-sidecar state dir gone", not os.path.exists(stray), stray)
check("A7 legacy systemd unit removed", not os.path.exists(unit), unit)

# ---------------------------------------------------------------------------
# B. relay.js unit behaviour against a local sink upstream
# ---------------------------------------------------------------------------
if not BUN:
    print("B1-SKIP bun not installed; relay unit + extension checks skipped", flush=True)
    print("C-SKIP", flush=True)
else:
    class Sink(BaseHTTPRequestHandler):
        def _reply(self):
            body = b'{"data":[{"id":"sink-model"}]}' if self.command == "GET" else b'{"echo":"sink-ok"}'
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = do_POST = _reply

        def log_message(self, *_a):
            pass

    sink = HTTPServer(("127.0.0.1", 0), Sink)
    sink_port = sink.server_address[1]
    threading.Thread(target=sink.serve_forever, daemon=True).start()

    tmp = tempfile.mkdtemp(prefix="zen-relay-test-")
    relay_env = {
        **os.environ,
        "ZEN_RELAY_PORT": "8792",
        "ZEN_RELAY_UPSTREAM": f"http://127.0.0.1:{sink_port}",
        "ZEN_RELAY_IDLE_MS": "3000",
        "ZEN_RELAY_STATE_DIR": tmp,
    }
    relay = subprocess.Popen([BUN, os.path.join(EXT_DIR, "relay.js")], env=relay_env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    alive = False
    for _ in range(40):
        try:
            get("http://127.0.0.1:8792/healthz", timeout=2)
            alive = True
            break
        except OSError:
            if relay.poll() is not None:
                break
            time.sleep(0.1)

    try:
        if not alive:
            boot_output = (relay.communicate(timeout=5)[0] if relay.poll() is not None else "(no output)")[:400]
            check("B1 relay never came up on 8792", False, boot_output.replace("\n", " | "))
            raise StopIteration
        status, body = get("http://127.0.0.1:8792/healthz")
        health = json.loads(body)
        check("B1 healthz identifies the relay", status == 200 and health.get("name") == "pi-opencode-free-sidecar", body[:80])
        status, _ = get("http://127.0.0.1:8792/zen/v1/models")
        check("B2 GET /models is open", status == 200, str(status))
        status, body = post("http://127.0.0.1:8792/zen/v1/chat/completions", "{}")
        check("B3 POST without token refused", status == 401, str(status))
        token = open(os.path.join(tmp, "token"), encoding="utf-8").read().strip()
        mode = stat.S_IMODE(os.stat(os.path.join(tmp, "token")).st_mode)
        check("B4 token file is 0600", mode == 0o600, oct(mode))
        status, body = post("http://127.0.0.1:8792/zen/v1/chat/completions", "{}",
                            headers={"x-zen-relay-token": token})
        check("B5 POST with token proxied", status == 200 and "sink-ok" in body, str(status))

        second = subprocess.Popen([BUN, os.path.join(EXT_DIR, "relay.js")], env=relay_env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        second_exited = second.wait(timeout=10) == 0
        still_alive = relay.poll() is None
        check("B6 second instance adopts and exits", second_exited and still_alive)

        deadline = time.time() + 12
        while time.time() < deadline and relay.poll() is None:
            time.sleep(0.3)
        check("B7 idle self-exit", relay.poll() is not None, f"exit={relay.poll()}")
        check("B8 pid file cleaned", not os.path.exists(os.path.join(tmp, "relay.pid")))
    except StopIteration:
        pass
    finally:
        if relay.poll() is None:
            relay.terminate()
        sink.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    # -----------------------------------------------------------------------
    # C. extension load contract in an isolated agent dir
    # -----------------------------------------------------------------------
    probe_dir = tempfile.mkdtemp(prefix="zen-probe-agent-")
    probe_state = os.path.join(probe_dir, "state")
    with open(os.path.join(probe_dir, "settings.json"), "w", encoding="utf-8") as fh:
        json.dump({"packages": [REPO_DIR]}, fh, indent=2)
    with open(os.path.join(probe_dir, "auth.json"), "w", encoding="utf-8") as fh:
        json.dump({"opencode-zen": {"type": "api_key", "key": "public"}}, fh)
    probe_port = "8791"
    with open(os.path.join(probe_dir, "models.json"), "w", encoding="utf-8") as fh:
        json.dump({"providers": {"opencode-zen": {"baseUrl": f"http://127.0.0.1:{probe_port}/zen/v1"}}}, fh, indent=2)

    probe_env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": probe_dir,
        "PI_FREE_SIDECAR_STATE_DIR": probe_state,
        "PI_ZEN_RELAY_PORT": probe_port,
        "PI_ZEN_RELAY_IDLE_MS": "600000",
    }
    health_url = f"http://127.0.0.1:{probe_port}/healthz"

    def probe_relay_pid():
        try:
            return int(open(os.path.join(probe_state, "relay.pid"), encoding="utf-8").read().strip())
        except (FileNotFoundError, ValueError):
            return None

    def probe_alive():
        try:
            get(health_url, timeout=2)
            return True
        except OSError:
            return False

    try:
        listing = subprocess.run(["pi", "--list-models"], env=probe_env, capture_output=True, text=True, timeout=180)
        check("C1 provider registered (dynamic import works)",
              "opencode-zen" in listing.stdout and "beam-free" in listing.stdout,
              listing.stdout[:120].replace("\n", " | "))
        check("C2 factory spawned the relay", probe_alive())

        # header self-heal: we seeded models.json without the token header
        healed = json.load(open(os.path.join(probe_dir, "models.json"), encoding="utf-8"))
        healed_headers = healed.get("providers", {}).get("opencode-zen", {}).get("headers", {})
        check("C3 token header self-healed into models.json", "x-zen-relay-token" in healed_headers, str(healed_headers))

        live = subprocess.run(
            ["pi", "--no-session", "--model", "opencode-zen/deepseek-v4.1-flash-free",
             "-p", "Reply with exactly: SIDECAR-10-OK"],
            env=probe_env, capture_output=True, text=True, timeout=300)
        check("C4 live Zen call succeeds through relay", live.returncode == 0 and "SIDECAR-10-OK" in live.stdout,
              live.stdout[-120:].strip().replace("\n", " ") or live.stderr[-160:].strip().replace("\n", " "))

        log_path = os.path.join(probe_state, "access.log")
        log_text = open(log_path, encoding="utf-8").read() if os.path.exists(log_path) else ""
        check("C5 relay saw the shaped traffic (base URL was loopback at import)",
              "POST /chat/completions 200" in log_text, f"{log_text.count(chr(10))} log lines")

        # fetch guard: kill the relay mid-session-lifetime; the next call must
        # self-heal (connection refused -> ensureRelay -> retry once)
        pid = probe_relay_pid()
        if pid:
            os.kill(pid, signal.SIGKILL)
        deadline = time.time() + 5
        while time.time() < deadline and probe_alive():
            time.sleep(0.2)
        recovered = subprocess.run(
            ["pi", "--no-session", "--model", "opencode-zen/deepseek-v4.1-flash-free",
             "-p", "Reply with exactly: SIDECAR-10-RECOVER"],
            env=probe_env, capture_output=True, text=True, timeout=300)
        check("C6 killed relay recovered (guard restart + retry)",
              recovered.returncode == 0 and "SIDECAR-10-RECOVER" in recovered.stdout,
              recovered.stdout[-120:].strip().replace("\n", " ") or recovered.stderr[-160:].strip().replace("\n", " "))

        # the token really is what gates the port: strip it and expect 401
        status, _ = post(f"http://127.0.0.1:{probe_port}/zen/v1/chat/completions", "{}")
        check("C7 token still gates writes on the probe relay", status == 401, str(status))
    finally:
        pid = probe_relay_pid()
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        shutil.rmtree(probe_dir, ignore_errors=True)

print("PASS" if ok else "FAIL", flush=True)
sys.exit(0 if ok else 1)
