#!/usr/bin/env bash
# Install this repo into pi and seed the example agent personas.
#
#   ./install.sh          # keep existing deployed personas
#   ./install.sh --force  # overwrite deployed personas with the examples here
#
# Idempotent. The package is registered as a LOCAL source, which pi loads from
# this path without copying, so editing a file here takes effect after
# `/reload` or a restart (no reinstall step).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

# 1. Register the package first, so a failed install leaves any loose
#    extensions in place.
pi install "$REPO_DIR"

# 2. Keep this package FIRST in settings.json. Load order is settings order,
#    and pi-veto must run before pi-permission-system: a veto block then
#    preempts pps's ask dialog, which is what makes "catastrophic never
#    prompts" true even for commands pps would otherwise ask about.
python3 - "$AGENT_DIR" "$REPO_DIR" <<'PY'
import json, os, sys
agent_dir, repo = sys.argv[1], os.path.realpath(sys.argv[2])
settings_path = os.path.join(agent_dir, "settings.json")
with open(settings_path, encoding="utf-8") as handle:
    settings = json.load(handle)
packages = settings.get("packages")
if not isinstance(packages, list):
    sys.exit(0)

def source_of(entry):
    return entry if isinstance(entry, str) else entry.get("source", "")

def is_ours(entry):
    source = source_of(entry)
    if not source or ":" in source.split("/")[0]:
        return False
    if not os.path.isabs(source):
        source = os.path.join(agent_dir, source)
    return os.path.realpath(source) == repo

ours = [entry for entry in packages if is_ours(entry)]
rest = [entry for entry in packages if not is_ours(entry)]
if not ours or packages[0] in ours:
    sys.exit(0)
settings["packages"] = ours + rest
tmp = settings_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as handle:
    json.dump(settings, handle, indent=2)
    handle.write("\n")
os.replace(tmp, settings_path)
print("moved this package to the front of", settings_path)
PY

# 3. Remove loose auto-discovered copies. If both a loose dir and the package
#    register the same tool, pi treats the duplicate name as fatal.
for name in pi-workflow-modes pi-veto pi-opencode-free-sidecar; do
  loose="$AGENT_DIR/extensions/$name"
  if [ -e "$loose" ]; then
    echo "removing loose extension dir: $loose"
    rm -rf "$loose"
  fi
done

# 3b. Zen relay prerequisites. bun runs the transport relay (pi itself does
#     not need it); the models.json baseUrl decides where Zen requests go,
#     and requests must reach the relay. Seed it only when the provider has
#     no baseUrl yet (or --force): your provider config stays yours.
if ! command -v bun >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/bun" ]; then
  echo "WARNING: bun not found (PATH or ~/.local/bin/bun). Zen free models"
  echo "         need the Bun relay; install bun from https://bun.sh"
fi
python3 - "$AGENT_DIR" "$FORCE" <<'PY'
import json, os, sys

agent_dir, force = sys.argv[1], int(sys.argv[2])
path = os.path.join(agent_dir, "models.json")
try:
    with open(path, encoding="utf-8") as fh:
        config = json.load(fh)
except FileNotFoundError:
    config = {}
providers = config.setdefault("providers", {})
zen = providers.setdefault("opencode-zen", {})
relay = "http://127.0.0.1:8787/zen/v1"
current = zen.get("baseUrl")
if current is None or (force and current != relay):
    zen["baseUrl"] = relay
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")
    os.replace(tmp, path)
    print(f"seeded opencode-zen baseUrl -> {relay} in {path}")
elif current != relay:
    print(f"note: leaving your existing opencode-zen baseUrl as {current}")
else:
    print("opencode-zen baseUrl already points at the relay")
PY
# The relay's token header (x-zen-relay-token) is added to models.json by
# the extension itself on first load, once the baseUrl above matches.

# 4. Agent personas are not a pi-package resource. pi-permission-system and
#    pi-subagents read them from <agent-dir>/agents/, so seed them there.
#    The copies in this repo are GENERIC examples (sanitized LAN targets);
#    your deployed files are the source of truth for your own policy, so they
#    are only written when absent unless --force is given.
mkdir -p "$AGENT_DIR/agents"
for src in "$REPO_DIR"/agents/*.md; do
  dst="$AGENT_DIR/agents/$(basename "$src")"
  if [ -e "$dst" ] && [ "$FORCE" -eq 0 ]; then
    echo "keeping existing persona: $dst"
  else
    cp -f "$src" "$dst"
    echo "deployed persona: $dst"
  fi
done

cat <<'EOF'

Next:
  1. Personalize the ask catalog in ~/.pi/agent/agents/*.md (see "Personalize"
     in this repo's README); the deployed files are yours, this repo only
     seeds them.
  2. If you used npm:@rabden/pi-opencode-zen before, remove it from
     settings.json packages: this package's pi-opencode-free-sidecar
     replaces it and they must not both load.
  3. `pi` / PiChamber (restart its session daemon) / Orbit (restart)
  4. /workflow-mode should report the active mode; /opencode-free-sidecar
     status should report the Bun relay
  5. run the regression gate: extensions/pi-workflow-modes/tests/run.sh
EOF
