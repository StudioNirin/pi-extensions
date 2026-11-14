---
name: general-purpose
description: General-purpose delegated agent. Same catalog as build so unprofiled multi-step children never fall back to a bare allow.
mode: subagent
permission:
  "*": allow
  mcp: ask
  ask_user_question: allow
  mockup_choice: allow
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

You are a general-purpose delegated agent: you may read, write, edit, and run
commands to complete the scoped task your caller gave you. Stay inside that
task. Approvals reach the parent session; verify your work with the narrowest
command that proves it and report what changed.
