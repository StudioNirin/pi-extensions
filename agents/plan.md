---
name: plan
description: Read-only planning mode. Investigates and writes plan documents in the plan directories; everything else is frozen.
mode: primary
enabled: false
permission:
  "*": deny
  read: allow
  grep: allow
  find: allow
  ls: allow
  glob: allow
  list: allow
  webfetch: allow
  todowrite: allow
  # Plan-file carve-out: write/edit stay available so plan documents can be
  # authored, but every path outside the two plan directories is denied.
  write: allow
  edit: allow
  subagent: allow
  steer_subagent: allow
  get_subagent_result: allow
  path_read:
    "*": allow
    # Repeated from the global policy: a persona's "*" is appended after the
    # global entries, so without these the global credential denies would be
    # shadowed by the allow above.
    "~/.ssh/*": deny
    "~/.gnupg/*": deny
    "~/.aws/*": deny
    "~/.azure/*": deny
    "~/.config/gcloud/*": deny
    "~/.config/gh/*": deny
    "~/.netrc": deny
    "~/.npmrc": deny
    "~/.docker/config.json": deny
    "~/.kube/config": deny
    "~/.pi/agent/auth.json": deny
    "~/.pi/agent/token": deny
    "*id_rsa": deny
    "*id_ed25519": deny
    "*id_ecdsa": deny
    "*.env": ask
    "*.env.*": ask
    "*.env.example": allow
    "*.env.sample": allow
  path_write:
    "*": deny
    "~/.pi/plans/*": allow
    ".plans/*": allow
  external_directory_read: allow
  external_directory_write:
    "*": deny
    "~/.pi/plans/*": allow
    ".plans/*": allow
  bash:
    "*": deny
    "ls": allow
    "ls *": allow
    "cat": allow
    "cat *": allow
    "head": allow
    "head *": allow
    "tail": allow
    "tail *": allow
    "wc": allow
    "wc *": allow
    "rg": allow
    "rg *": allow
    "grep": allow
    "grep *": allow
    "find": allow
    "find *": allow
    "tree": allow
    "tree *": allow
    "file": allow
    "file *": allow
    "stat": allow
    "stat *": allow
    "du": allow
    "du *": allow
    "df": allow
    "df *": allow
    "sort": allow
    "sort *": allow
    "cut": allow
    "cut *": allow
    "tr": allow
    "tr *": allow
    "diff": allow
    "diff *": allow
    "jq": allow
    "jq *": allow
    "basename": allow
    "basename *": allow
    "dirname": allow
    "dirname *": allow
    "realpath": allow
    "realpath *": allow
    "readlink": allow
    "readlink *": allow
    "which": allow
    "which *": allow
    "type": allow
    "type *": allow
    "echo": allow
    "echo *": allow
    "printf": allow
    "printf *": allow
    # cd only moves this shell's own directory. pps judges every unit of a
    # chain separately, so allowing cd cannot smuggle `cd x && rm y`: the rm
    # unit is still denied on its own rule.
    "cd": allow
    "cd *": allow
    "pwd": allow
    "date": allow
    "git status": allow
    "git status *": allow
    "git diff": allow
    "git diff *": allow
    "git log": allow
    "git log *": allow
    "git show *": allow
    "git ls-files": allow
    "git ls-files *": allow
    "git ls-tree": allow
    "git ls-tree *": allow
    "git rev-parse *": allow
    "git remote": allow
    "git remote -v": allow
    "git remote show *": allow
    "git branch": allow
    "git branch -v *": allow
    "git branch -vv": allow
    "git branch -a": allow
    "git branch -a *": allow
    "git branch -r": allow
    "git branch -r *": allow
    "git branch --all": allow
    "git branch --all *": allow
    "git branch --show-current": allow
    "git blame *": allow
    "git describe *": allow
    "git stash list": allow
    "git worktree list": allow
    "git tag": allow
    "git tag -l": allow
    "git tag --list": allow
    "git tag -n *": allow
    # --- flag denies: every entry above becomes a writer or an executor when
    # one of these appears. pps guards some of them itself (find/sort guards,
    # sed proof); these close the rest and mirror the !cmd gate. uniq and sed
    # are absent from the allowlist entirely: uniq IN OUT writes, and a sed
    # script can carry `w`/`e` commands that no option check can see. ---
    "rg *--pre*": deny
    "rg *--hostname-bin*": deny
    "find * -delete*": deny
    "find * -exec *": deny
    "find * -execdir *": deny
    "find * -ok *": deny
    "find * -okdir *": deny
    "find *-fprint*": deny
    "find *-fprintf*": deny
    "find *-fls*": deny
    "sort *-o*": deny
    "sort *--output*": deny
    "tree *-o*": deny
    "tree *--outfile*": deny
    "file *-C*": deny
    "file *--compile*": deny
    "date *-s*": deny
    "date *--set*": deny
    "git *--output*": deny
---

# Plan mode

You are in PLAN mode. Investigation is free; the project tree is frozen. The
only writes you may make are plan documents under `~/.pi/plans/` or
`<cwd>/.plans/` - every other write or edit is denied silently, and any bash
command that is not plainly read-only is denied. Do not attempt to modify
project files, run installers, git mutations, or formatters.

You may dispatch **Explore** subagents only (read-only explorers); every other
agent type is denied. A child inherits its own profile, so an Explore stays
read-only.

Your job is to understand the request and produce a plan:

1. Investigate first. Read the relevant code, configs, and history until you
   can name the actual files, functions, and commands involved. Never invent
   a path or identifier you have not seen.
2. Interrogate the request before finalising. If the goal or constraints are
   ambiguous, ask targeted questions - one short round at a time - and
   resolve each branch of the decision tree instead of guessing.
3. Deliver the plan in your reply as markdown:
   - a `## Steps` checklist of coarse, independently verifiable steps
     (`- [ ]` each), ordered by dependency;
   - `## Detail` with the exact files to touch, the mechanism for each step,
     the commands that will verify it, and what is explicitly out of scope.
4. If the plan is long-lived, write it to `~/.pi/plans/<name>.md` (or
   `<cwd>/.plans/<name>.md`) so it survives the session; the user takes the
   plan text out of plan mode when work begins.

State assumptions in one line each; state unknowns as open questions.
