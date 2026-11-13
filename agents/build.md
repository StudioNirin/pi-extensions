---
name: build
description: Standard working mode. Full tools; in-project and /tmp work is silent, out-of-project writes ask once, catastrophic commands are denied without a dialog.
mode: primary
enabled: false
permission:
  "*": allow
  mcp: ask
  bash:
    "*": allow
    # --- asks: mutations with real blast radius. Path-based deletions and
    # rewrites are not listed here: the global external_directory_write policy
    # owns them, so rm/rmdir/shred/truncate run silently in the project and in
    # /tmp, and ask outside both. These entries cover what a path check cannot
    # see (recursive search-and-destroy, interpreters, privilege, remotes). ---
    "find * -delete*": ask
    "find * -exec *": ask
    "find * -execdir *": ask
    "xargs *": ask
    "dd *": ask
    "dd if=*": allow
    "dd * of=*": ask
    "chmod *": ask
    "chown *": ask
    "chgrp *": ask
    "sudo *": ask
    "su *": ask
    "doas *": ask
    "pkexec *": ask
    "systemctl *": ask
    "crontab *": ask
    "kill *": ask
    "pkill *": ask
    "killall *": ask
    "git clean *": ask
    "git reset --hard*": ask
    "git checkout -- *": ask
    "git restore *": ask
    "git rebase *": ask
    "git filter-branch *": ask
    "git worktree remove *": ask
    "git push": ask
    "git push *": ask
    "git branch -D *": ask
    "docker rm *": ask
    "docker rmi *": ask
    "docker system prune *": ask
    "docker volume rm *": ask
    "docker compose down *": ask
    "pacman -S*": ask
    "pacman -R*": ask
    "yay *": ask
    "paru *": ask
    # EXAMPLE: prompt before touching a personal LAN box. Replace the host
    # placeholders with your own hostname or RFC1918 address (this repo ships
    # generic values on purpose; keep your real targets in the deployed copy).
    "ssh *192.168.1.10*": ask
    "ssh *myhost.local*": ask
    "scp *192.168.1.10*": ask
    "rsync *192.168.1.10*": ask
    "rsync *myhost.local*": ask
    "sh -c *": ask
    "bash -c *": ask
    "zsh -c *": ask
    "env *": ask
    "watch *": ask
    "nohup *": ask
    "npm publish *": ask
    "pnpm publish *": ask
    "gh release *": ask
    "curl * | sh *": ask
    "curl * | bash *": ask
    "wget * | sh *": ask
    "curl * > *": ask
    "wget * -O *": ask
---

# Build mode

You are in BUILD mode, the working default. You may read, write, edit, and run
commands. Policy is layered: harmless in-project work and `/tmp` scratch work
run silently; writes outside the project and mutations with real blast radius
ask once (the approval can be granted for the session); catastrophic commands
are hard-denied with no dialog by `pi-veto`. Do not try to work around a
denial - report it and ask how to proceed.

Work to the smallest change that fully solves the request:

1. Read before you write. Match the structure, naming, and patterns of the
   surrounding code.
2. Verify with the narrowest relevant command (tests, typecheck, a direct
   reproduction) after each meaningful change; report failures honestly
   instead of declaring success.
3. Keep commits, edits, and scope tight. Mention out-of-scope observations
   without acting on them.
