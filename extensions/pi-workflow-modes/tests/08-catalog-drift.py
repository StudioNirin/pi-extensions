"""08-catalog-drift: the three ask-catalog carriers must stay byte-identical.

build.md, worker.md and general-purpose.md each carry the union ask catalog
(three copies until pi-policy-console owns sync). This test fails on any drift
between the shared blocks, so an edit to one file cannot silently weaken the
others.

Pass criteria in printed output:
  - the shared block (from `external_directory_write` to the end of the
    frontmatter) is identical in all three files
"""
import hashlib, os, re, sys

AGENTS = os.environ.get("PI_AGENTS_DIR") or os.path.join(
    os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent"), "agents")
FILES = ["build.md", "worker.md", "general-purpose.md"]
ANCHOR = "  external_directory_write: ask"

blocks = {}
for name in FILES:
    path = os.path.join(AGENTS, name)
    if not os.path.exists(path):
        print(f"MISSING: {path}", flush=True)
        sys.exit(1)
    text = open(path, encoding="utf-8").read()
    if ANCHOR not in text:
        print(f"NO SHARED BLOCK: {name} has no '{ANCHOR.strip()}'", flush=True)
        sys.exit(1)
    start = text.index(ANCHOR)
    end = text.index("\n---", start)
    block = text[start:end].rstrip("\n")
    blocks[name] = block
    print(f"{name}: {len(block.splitlines())} shared lines sha256={hashlib.sha256(block.encode()).hexdigest()[:16]}", flush=True)

reference_name = FILES[0]
reference = blocks[reference_name]
ok = all(block == reference for block in blocks.values())
if not ok:
    for name, block in blocks.items():
        if block != reference:
            reference_lines = reference.splitlines()
            block_lines = block.splitlines()
            for index in range(max(len(reference_lines), len(block_lines))):
                left = reference_lines[index] if index < len(reference_lines) else "<missing>"
                right = block_lines[index] if index < len(block_lines) else "<missing>"
                if left != right:
                    print(f"FIRST DRIFT {reference_name} vs {name} line {index + 1}:", flush=True)
                    print(f"  {reference_name}: {left}", flush=True)
                    print(f"  {name}: {right}", flush=True)
                    break
print("PASS" if ok else "FAIL", flush=True)
sys.exit(0 if ok else 1)
