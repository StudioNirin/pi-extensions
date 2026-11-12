# pi-veto

The **deny-only security floor** for pi. It sits below policy: no agent
frontmatter, pps rule, workflow mode, or approval can make these operations
run, and none of them ever opens a dialog.

## Contract

| Property | Meaning |
| --- | --- |
| Deny only | There is no ask path and no allow path. A mode-blind ask would be a second prompter (double-prompt bug); an allow would make the floor liftable. |
| Agent-immune | Enforcement lives in this extension's `tool_call` / `user_bash` hooks, not in `permission:` frontmatter. A file that says `"mkfs *": allow` changes nothing. |
| Additive user rules | `~/.pi/agent/floor.json` may add more denies. Anything that is not under `deny` is ignored on purpose. |
| Silent | Tool calls get a block reason; `!cmd` gets exit 126 and never executes. No `Yes/No` card. |

## Built-in floor

- **Disk / partitions:** `mkfs`, `mkfs.*`, `fdisk`, `parted`, `wipefs`, `mount`, `umount`
- **Devices:** `dd of=/dev/*`, `shred /dev/*`, `rm -rf /dev/*`
- **Wipe:** `rm -rf` on `/`, `~`, `/home`, `/etc`, `/usr`, `/var`, `/boot`, `/opt`, `/srv`, `/lib*`, `/bin`, `/sbin`, `/proc`, `/sys`, `/run`, `/root`, a `/mnt/<disk>` or `/media/<disk>` root
- **Fork bomb:** `:(){ :|:& };:` and variants
- **Power:** `reboot`, `shutdown`, `poweroff`, `halt`
- **Secrets and policy (writes only):** `~/.ssh/`, `~/.gnupg/`, `~/.aws/`, `~/.azure/`, `~/.config/gcloud/`, `~/.netrc`, `~/.npmrc`, `~/.pi/agent/`, `/etc/sudoers`, `/etc/shadow`

Shell wrappers (`sudo`, `doas`, `pkexec`, `env`, `xargs`, `nohup`, `watch`,
`nice`, ...), `sh -c "..."`, command substitutions, and `;`/`&&`/`||`/`|`
chains are inspected, so `sudo mkfs.ext4 /dev/sda` and
`!sh -c "dd of=/dev/sda"` are caught too.

## floor.json

```json
{
  "deny": {
    "bash": ["docker system prune *", "gh repo delete *"],
    "paths": ["~/work/clients/*"]
  }
}
```

- `deny.bash` entries are globs (`*`, `?`) matched against the whole command;
  a trailing `" *"` also matches the bare command, mirroring pps.
- `deny.paths` entries are path prefixes; `~` is expanded.
- Hot-reloaded (mtime checked per call). `/veto` shows what is active and lists
  any ignored entries.

## Regression tests

Covered by `pi-workflow-modes/tests/07-veto.py`: `wipefs` through the tool,
`dd of=/dev/*` through `!cmd`, additive floor denies, and the fact that the
veto fires for a command pps does not know about (so a pps change cannot mask
a veto regression).
