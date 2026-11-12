#!/usr/bin/env bash
# Headless regression suite for pi workflow modes + pps + pi-veto enforcement.
# Run AFTER any pi / pps / pi-subagents / pichamber / orbit update.
# (No pi-codemode re-pin since PiChamber 1.0.6: it bundles pi-coding-agent 1.5.0,
#  which pins pi-codemode 1.5.0 exactly.)
# Each scenario spawns its own `pi --mode rpc` in a real cwd; expect several
# minutes total. Set PI_TEST_CWD to choose that cwd (default: $HOME); probe
# files land there, so a scratch project keeps your home clean.
# Usage: ./run.sh            (all scenarios)
#        ./run.sh 01         (one scenario by name prefix)
set -u
cd "$(dirname "$0")"
if [ "$#" -gt 0 ]; then
  mapfile -t FILES < <(ls ./"$1"*.py 2>/dev/null)
else
  mapfile -t FILES < <(ls ./*.py | sort)
fi
[ "${#FILES[@]}" -eq 0 ] && { echo "no scenarios matched"; exit 2; }
fail=0
for f in "${FILES[@]}"; do
  echo "==== $f ===="
  timeout 1200 python3 "$f" || { echo "FAIL ($f) exit=$?"; fail=1; }
done
[ $fail -eq 0 ] && echo "ALL SCENARIOS RAN - check each script's PASS lines above; a script can exit 0 with FAILed expectations"
exit $fail
