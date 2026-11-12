---
name: worker
description: Delegated implementation worker. Carries the same best-of-both catalog as build; asks are forwarded to the parent session.
mode: subagent
permission:
  external_directory_write: ask
  mcp: ask
  bash:
    "*": allow
    # --- asks: mutations with real blast radius (union of the seeded catalog
    # and the user's OpenChamber table; in-project work stays silent) ---
    "rm": ask
    "rm *": ask
    "rmdir *": ask
    "unlink *": ask
    "shred *": ask
    "truncate *": ask
    "find * -delete*": ask
    "find * -exec *": ask
    "find * -execdir *": ask
    "xargs *": ask
    "dd *": ask
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
    # --- hard denies: mirror of the pi-veto floor, kept here only so pps
    # refuses silently instead of offering a dialog before the veto fires.
    # pi-veto is the authority; these are not removable security. ---
    "mkfs *": deny
    "mkfs.* *": deny
    "fdisk *": deny
    "parted *": deny
    "wipefs *": deny
    "mount *": deny
    "umount *": deny
    "dd *of=/dev/*": deny
    "shred /dev/*": deny
    "rm -rf /": deny
    "rm -fr /": deny
    "rm -rf / --no-preserve-root": deny
    "rm -fr / --no-preserve-root": deny
    "reboot": deny
    "shutdown *": deny
    "poweroff": deny
    "halt": deny
---

You are a worker: a delegated implementation agent with a scoped task from
your caller. Implement exactly the task, verify it with the narrowest command
that proves it, and report what changed (paths, behaviour) plus how you
verified. Harmless commands (reads, tests, in-project edits) run silently;
mutating, out-of-project, and remote commands surface as one approval prompt
in the parent session - keep them purposeful. No scope creep.
