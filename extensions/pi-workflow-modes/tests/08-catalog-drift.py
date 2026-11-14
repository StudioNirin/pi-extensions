"""08-catalog-drift: the personas must not drift apart.

Two shared blocks are pinned:

  1. Writer catalog: build.md and general-purpose.md carry the union ask
     catalog. Three copies became two when worker.md was retired (0.4.1);
     pi-policy-console will own sync later.
  2. Read-only bash surface: plan.md, ask.md, and Explore.md carry the same
     reader allowlist plus the same writer-flag denies, and none of them may
     reintroduce `uniq` or `sed` (both can write through a positional or a
     script, which no option check can see).

Pass criteria in printed output:
  - the writer block (from `mcp: ask` to the end of the frontmatter) is
    identical in both writer files (both carry the `ask_user_question` and
    `mockup_choice` allow lines)
  - the read-only block (from `bash:` to the end of the frontmatter) is
    identical in all three read-only files
  - all five personas name the user-facing tool allows: `ask_user_question`,
    `mockup_choice`, `web_search`, `web_fetch` (user decisions 2026-11-14)
  - no read-only file allows uniq or sed
"""
import hashlib, os, sys

AGENTS = os.environ.get("PI_AGENTS_DIR") or os.path.join(
    os.environ.get("PI_CODING_AGENT_DIR") or os.path.expanduser("~/.pi/agent"), "agents")
WRITERS = ["build.md", "general-purpose.md"]
READERS = ["plan.md", "ask.md", "Explore.md"]
WRITER_ANCHOR = "  mcp: ask"
READER_ANCHOR = "  bash:"

def shared_block(name, anchor):
    path = os.path.join(AGENTS, name)
    if not os.path.exists(path):
        print(f"MISSING: {path}", flush=True)
        sys.exit(1)
    text = open(path, encoding="utf-8").read()
    if anchor not in text:
        print(f"NO SHARED BLOCK: {name} has no '{anchor.strip()}'", flush=True)
        sys.exit(1)
    start = text.index(anchor)
    end = text.index("\n---", start)
    block = text[start:end].rstrip("\n")
    print(f"{name}: {len(block.splitlines())} shared lines sha256={hashlib.sha256(block.encode()).hexdigest()[:16]}", flush=True)
    return block

def compare(label, files, blocks):
    reference_name = files[0]
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
                        print(f"FIRST DRIFT {label} {reference_name} vs {name} line {index + 1}:", flush=True)
                        print(f"  {reference_name}: {left}", flush=True)
                        print(f"  {name}: {right}", flush=True)
                        break
    return ok

writer_blocks = {name: shared_block(name, WRITER_ANCHOR) for name in WRITERS}
writer_ok = compare("writers", WRITERS, writer_blocks)
reader_blocks = {name: shared_block(name, READER_ANCHOR) for name in READERS}
reader_ok = compare("readers", READERS, reader_blocks)
print("writer catalog identical:", "PASS" if writer_ok else "FAIL", flush=True)
print("read-only surface identical:", "PASS" if reader_ok else "FAIL", flush=True)

# User-facing tools are accessible to ALL personas (user decision 2026-11-14,
# reversing an earlier build-only lean; web tools same day with the rpiv
# install): the writers get them via the pinned block above, the deny-all
# readers only if each names them.
TOOL_ACCESS = ("ask_user_question: allow", "mockup_choice: allow",
               "web_search: allow", "web_fetch: allow")
missing = []
for name in WRITERS + READERS:
    text = open(os.path.join(AGENTS, name), encoding="utf-8").read()
    for rule in TOOL_ACCESS:
        if rule not in text:
            missing.append(f"{name}: no '{rule}'")
for gap in missing:
    print("TOOL ACCESS GAP:", gap, flush=True)
print("user-facing tools allowed in all personas:",
      "PASS" if not missing else "FAIL", flush=True)

leaks = []
for name, block in reader_blocks.items():
    for line in block.splitlines():
        stripped = line.strip()
        if stripped.startswith('"uniq') or stripped.startswith('"sed'):
            leaks.append(f"{name}: {stripped}")
if leaks:
    for leak in leaks:
        print("READ-ONLY WRITER LEAK:", leak, flush=True)
print("no uniq/sed in read-only surface:", "PASS" if not leaks else "FAIL", flush=True)

sys.exit(0 if writer_ok and reader_ok and not missing and not leaks else 1)
