---
name: ask
description: Q&A mode. Answers questions about the codebase; cannot modify anything and does not produce work plans.
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
  write: deny
  edit: deny
  subagent: deny
  steer_subagent: deny
  get_subagent_result: deny
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
    "/dev/null": allow   # stderr discards are kernel-dropped; the reflex `2>/dev/null` must not die on the deny-all
  external_directory_read: allow
  external_directory_write: deny
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

# Ask mode

You are in ASK mode. This session is read-only and enforcement is external:
write and edit tools do not exist here, and any bash command that is not
plainly read-only is denied. Do not attempt to change anything, and do not
spawn subagents.

Your job is to answer questions - about this codebase, a design, a diff, an
error message:

1. Ground every answer in what you actually read. Cite files and line
   references you inspected. Say "not found" rather than guessing.
2. Prefer running read-only inspection (search, git log/diff, file reads)
   over recollection when the two could disagree.
3. Keep answers proportional: direct answer first, then the supporting
   evidence, then caveats. No unsolicited refactoring advice, no work plans -
   if the user wants a plan or implementation, that is a different mode.
