# pi-opencode-free-sidecar

OpenCode Zen's free models for **every** pi host, including ones that embed pi
inside Node (PiChamber's session daemon). One extension that combines:

1. **The Zen free-model provider**, vendored from
   [`@rabden/pi-opencode-zen`](https://github.com/rabden/pi-opencode-zen)
   v0.3.0 (MIT, `vendor/pi-opencode-zen/`, byte-identical). It shapes every
   request for the free-tier gate: official UA, SDK fingerprint headers
   stripped, SortableID session headers, marker prompt, text-protocol tool
   calls with stream translation.
2. **A Bun transport relay** (`relay.js`) for the outbound HTTPS hop, which
   is what makes Node-hosted pi work (details below).

This extension **replaces** `npm:@rabden/pi-opencode-zen`. They must not
both be loaded: two registrations of the `opencode-zen` provider in one pi
process. If you are migrating, remove the npm entry from
`~/.pi/agent/settings.json`.

## Why a relay exists

Zen's free tier classifies clients by class, and since late 2026 the class
check happens on the **transport fingerprint**, not the request content.
Verified 2026-11-12, same machine, same agent dir, same extensions, identical
gate-shaped requests produced by the provider's fetch patch:

| Client | Runtime | Result |
| --- | --- | --- |
| `pi` CLI 1.5.1 (compiled Bun binary) | Bun | 200 |
| pi bundle 1.5.0 run under Node (PiChamber's) | Node | 429 `FreeUsageLimitError` |
| fresh pi 1.5.2 run under Node | Node | 429 `FreeUsageLimitError` |
| pi 1.5.0/1.5.2 under Node, via this relay | Bun for the hop | 200 |

The error message says "free usage limit reached", which is misleading: no
quota was involved, every Bun client with the same identity returned 200 at
the same seconds. rabden's `docs/zen-gate-notes.md` rule 11 records the
opposite finding ("transport-agnostic, no TLS fingerprinting"), probed in
October against `/responses`; it no longer holds for `/chat/completions`
from Node.

So: pi talks to the relay over plain HTTP on `127.0.0.1`, and Bun performs
the real HTTPS request to `opencode.ai`. Nothing about the request content
changes on the hop except the token header being removed.

## What runs where

```
index.ts                     pi process (any runtime): env default, relay
                             lifecycle, token, guard, /opencode-free-sidecar
vendor/pi-opencode-zen/      inside pi: provider, gate shaping, SSE tool
                             translation (unmodified upstream files)
relay.js                     separate Bun process: loopback :8787 ->
                             https://opencode.ai/zen/v1
```

Relay lifecycle: started **on demand** by the extension (detached spawn of
`bun relay.js`), adopted if already running, self-exits after 15 minutes of
silence, and is restarted transparently by a fetch guard if it died
mid-session. No systemd unit, nothing runs until a pi process needs Zen.
Runtime state (token 0600, pid file, logs, no request bodies) lives in
`~/.local/share/pi-opencode-free-sidecar/`, never in the package folder, so
updates cannot rotate a live secret.

## Security notes

- The relay listens on loopback only.
- Every write (`POST`) must carry `x-zen-relay-token` matching the token
  file, or it gets 401. Without this any local process, or a web page
  POSTing to `127.0.0.1:8787`, could spend the Zen allowance through the
  port. `install.sh` / the extension seed the header into `models.json` as
  `"!cat <tokenfile>"`, which pi resolves per request. `GET /models` stays
  open (the provider fetches it without pi's header pipeline).
- Publishing this package means publishing tooling that works around a
  client classification on someone else's free tier. The upstream extension
  (MIT) already documents and depends on that gate; this repo inherits that
  posture deliberately. Upstream can change the gate at any time, and
  nothing here is guaranteed to keep working.

## Requirements

- `bun` on PATH or at `~/.local/bin/bun` (the relay runtime; pi itself does
  not need it). Get it from <https://bun.sh>. `install.sh` warns if it is
  missing; Zen free models then fail with a clear notice instead of a 429.
- pi with this package installed (`install.sh` in the repo root).
- `~/.pi/agent/models.json` provider `opencode-zen` with `baseUrl` pointed
  at the relay (seeded by `install.sh`; the token header self-heals on load)
  and a credential in `~/.pi/agent/auth.json`. **Recommended: your real
  OpenCode account key** (the same one pi's built-in `opencode` provider
  uses): free-model quota is tracked per credential, and the account bucket
  matches what the OpenCode app gets. The anonymous
  `{"type":"api_key","key":"public"}` (or `OPENCODE_API_KEY=public`) works
  with no account but has a small per-IP bucket that empties fast. Either
  way the transport gate still applies: a Node client 429s with a paid key
  exactly as it does anonymously (verified 2026-11-12); the key changes the
  quota bucket, not the class check.

## Commands

```
/opencode-free-sidecar status    relay identity, port, upstream, ownership
/opencode-free-sidecar restart   stop and respawn the relay
/opencode-free-sidecar stop      stop it (Zen calls then fail until respawn)
```

## Configuration

Everything has a working default; env overrides:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PI_ZEN_RELAY_PORT` | `8787` | loopback port (also changes the expected `models.json` baseUrl) |
| `PI_ZEN_RELAY_BUN` | PATH search | path to the `bun` binary |
| `PI_ZEN_RELAY_SCRIPT` | `relay.js` next to `index.ts` | relay script path |
| `PI_ZEN_RELAY_IDLE_MS` | `900000` | relay idle self-exit |
| `PI_FREE_SIDECAR_STATE_DIR` | `~/.local/share/pi-opencode-free-sidecar` | token/pid/logs |
| `PI_ZEN_BASE_URL` | the relay URL | advanced: set to bypass relay management (e.g. Bun-only setups calling OpenCode directly) |

`PI_ZEN_TEXT_TOOLS`, `PI_ZEN_TOOLS`, `PI_ZEN_VISION`, `PI_ZEN_ALL_MODELS`,
`PI_ZEN_DEBUG` belong to the vendored provider; see its header comment.

Load-order contract (in-repo, enforced by `index.ts` structure, not
settings): the extension defaults `PI_ZEN_BASE_URL` at module scope and only
then imports the provider **dynamically**, so the provider always sees the
loopback base. Do not convert that import to a static import;
`10-opencode-free-sidecar.py` checks the consequence (traffic must appear in
the relay log).

## Re-syncing the vendored provider

`vendor/pi-opencode-zen/` is kept byte-identical to an upstream release so
updates are a plain file replace. To re-sync:

```sh
npm pack @rabden/pi-opencode-zen@latest   # or clone the repo
# replace index.ts marker.ts models-meta.ts stream.ts LICENSE in
# extensions/pi-opencode-free-sidecar/vendor/pi-opencode-zen/
# then run: tests (10) and a live Zen call
```

The volatile upstream pieces are the pinned `ZEN_USER_AGENT` string and the
verbatim `marker.ts` prompt; when OpenCode moves the gate, those change
first.

## Tests

`tests/10-opencode-free-sidecar.py` (also runs from the repo's
`extensions/pi-workflow-modes/tests/run.sh` gate): relay auth/idle/single-
instance behaviour against a local sink, and the pi-level contract in an
isolated agent dir, including one live Zen round trip through the relay and
a killed-relay recovery.

## Known limitations

- **The free endpoint is shape-gated (measured 2026-11-12, direct probes):**
  requests must use `stream: true`; messages may not contain any
  `assistant`-role item; the array is capped at roughly 4 entries; `tools`
  declarations are refused; the first message must be OpenCode's own
  marker prompt verbatim (it is a title-generation prompt, which is why the
  provider ships defusing preambles/reminders around it); and the API keeps
  no server-side conversation state for this client class (a
  same-`x-opencode-session` follow-up does not see the prior turn). These
  four rules together are why a pi conversation can only be sent as
  rabden's flattened single-user-message transcript with tools as text
  protocol: there is no shape on this endpoint that carries native
  multi-turn agent traffic. `429 FreeUsageLimitError` is the generic gate
  refusal, not a quota signal: violating any shape rule (even just
  `stream: false`) returns it with a fresh quota.
- **Reliability ceiling.** Because of the above, weaker free models run
  pi's conversation through prompt-text fences over a flattened transcript
  and intermittently fail that contract: measured live (deepseek-v4.1-
  flash-free, 2026-11-12): turns ending right after long thinking with
  zero content, `toolUse` turns with no executable call, models mimicking
  the flattened-transcript markers (`[assistant tool call: ...]`) as fake
  exchanges, and occasional title-generator leakage (answering a question
  with a title). The fence rewriter is verifiably not at fault (synthetic
  stream test: closed fences convert, unclosed ones flush as visible text).
  The OpenCode app does not hit these because the official client is the
  gate's reference shape: native tools in its own byte-exact toolset, no
  assistant-role items to smuggle, no marker contamination.
- **Quota is per credential and drifts.** Free-model catalog churns
  (`422 Endpoint is unavailable` etc. for recently-seen ids); the
  anonymous `public` bucket is small (confirmed exhaustion today).
- **Fingerprint rotation.** Upstream can change the client-class check at
  any time; the relay is the current workaround, not a guarantee.

## Rollback

1. `systemctl --user stop pichamber.service` (or quit pi).
2. Remove `extensions/pi-opencode-free-sidecar` from the package (or the
   whole package from `settings.json`).
3. Restore `~/.pi/agent/settings.json` / `models.json` from your backups;
   `pi install npm:@rabden/pi-opencode-zen` if you want the pre-merge state.
4. Kill any `bun .../relay.js` process. Nothing else was installed.
