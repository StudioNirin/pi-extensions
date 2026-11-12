"""09-load-order: the veto must load before pps, on every runtime.

Why this is a test: extension handlers run in load order, and a blocked
`tool_call` stops later handlers. If pi-permission-system loads first, it opens
its ask dialog before pi-veto can block a catastrophic command. The package
manifest and settings.json order are therefore part of the security contract,
not cosmetics.

Pass criteria in printed output:
  - the package manifest lists pi-veto before pi-workflow-modes
  - settings.json lists our package before pi-permission-system
  - no loose copies of the two extensions shadow the package
"""
import json, os, sys

AGENT_DIR = os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent")
SETTINGS = os.path.join(AGENT_DIR, "settings.json")


def source_of(entry):
    return entry if isinstance(entry, str) else entry.get("source", "")


def resolves_to(source, target):
    if not source or ":" in source.split("/")[0]:
        return False
    if not os.path.isabs(source):
        source = os.path.join(AGENT_DIR, source)
    return os.path.realpath(source) == os.path.realpath(target)


ok = True

# --- 1. Package manifest order ---
manifest_path = None
packages = json.load(open(SETTINGS, encoding="utf-8")).get("packages", [])
for entry in packages:
    source = source_of(entry)
    if "pi-extensions" in source:
        candidate = source
        if not os.path.isabs(candidate):
            candidate = os.path.join(AGENT_DIR, candidate)
        if os.path.exists(os.path.join(candidate, "package.json")):
            manifest_path = candidate
            break

if not manifest_path:
    print("M1 package manifest found: False", flush=True)
    ok = False
else:
    manifest = json.load(open(os.path.join(manifest_path, "package.json"), encoding="utf-8"))
    extensions = manifest.get("pi", {}).get("extensions", [])
    veto = next((i for i, path in enumerate(extensions) if "pi-veto" in path), None)
    modes = next((i for i, path in enumerate(extensions) if "pi-workflow-modes" in path), None)
    order_ok = veto is not None and (modes is None or veto < modes)
    print(f"M1 manifest order veto={veto} modes={modes}: {order_ok}", flush=True)
    print(f"M2 manifest: {manifest_path}", flush=True)
    print(f"M3 extensions listed: {extensions}", flush=True)
    ok = ok and order_ok

# --- 2. Settings order: our package before pps ---
our_index = None
pps_index = None
if manifest_path:
    for i, entry in enumerate(packages):
        if resolves_to(source_of(entry), manifest_path):
            our_index = i
            break
for i, entry in enumerate(packages):
    if "pi-permission-system" in source_of(entry):
        pps_index = i
        break
settings_ok = our_index is not None and (pps_index is None or our_index < pps_index)
print(f"S1 settings order ours={our_index} pps={pps_index}: {settings_ok}", flush=True)
print(f"S2 settings: {[source_of(entry) for entry in packages]}", flush=True)
ok = ok and settings_ok

# --- 3. No loose copies shadowing the package ---
loose = [os.path.join(AGENT_DIR, "extensions", name)
         for name in ("pi-veto", "pi-workflow-modes")
         if os.path.exists(os.path.join(AGENT_DIR, "extensions", name))]
print(f"L1 no loose extension dirs: {not loose}", f"(found {loose})", flush=True)
ok = ok and not loose

print("PASS" if ok else "FAIL", flush=True)
sys.exit(0 if ok else 1)
