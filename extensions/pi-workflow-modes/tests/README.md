# Scenario scripts for the workflow-mode stack: headless pi RPC regression tests.
# ./run.sh runs all; ./run.sh 01 runs one by name prefix.
# See ../README.md "Tests / upgrade gate".
#
# Environment:
#   PI_TEST_CWD           scratch project the sessions run in (default: $HOME)
#   PI_CODING_AGENT_DIR   agent dir under test (default: ~/.pi/agent)
#   PI_TEST_MODEL         model id for every scenario (default: basalt/Qwen3.8-Flash-Next-NVFP4)
#   PI_TEST_TRACE         trace file for 06 (default: $TMPDIR/wf-mode-trace.jsonl)
#   PI_AGENTS_DIR         agents dir for 08 drift check (default: <agent dir>/agents)
#
# 01 mode switch          05 plan-file carve-out (silent denies, no dialogs)
# 02 resume + !cmd gate   06 mode-transition notice reaches the model
# 03 resume write leak    07 pi-veto floor (tool + !cmd + floor.json)
# 04 dialogs/subagents    08 ask-catalog drift across the three carriers
#                         09 load order (veto before pps; no loose copies)
#                         10 read-only bash (cd compounds allowed; -delete/
#                            --pre/-i style flags denied on both bash paths)
# 11 plan-mode !cmd gate   14 throughput meters (installed floating, no tools,
#                            redraw rate <= 15/s, number jitter, rendered width)
