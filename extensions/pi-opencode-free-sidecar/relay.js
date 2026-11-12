// pi-opencode-free-sidecar relay (Bun).
//
// Why this exists: OpenCode Zen's free tier classifies clients by their
// transport fingerprint, not just request content. The official OpenCode
// client is Bun-built, so Bun HTTPS clients pass; Node's undici clients get
// `429 FreeUsageLimitError` no matter how the request is shaped (verified
// 2026-11-12: identical shaped requests, Bun 200 / Node 429, two pi versions
// each). pi hosted inside a Node process (PiChamber's session daemon) is
// therefore locked out. The pi side of this package (index.ts, vendored
// @rabden/pi-opencode-zen) shapes every request for the gate; this relay
// performs the outbound HTTPS hop with Bun's fetch, restoring the accepted
// fingerprint. Traffic between pi and the relay is plain HTTP on loopback.
//
// Behaviour:
//   - listens on 127.0.0.1:$ZEN_RELAY_PORT (default 8787);
//   - rewrites /zen/v1/* to $ZEN_RELAY_UPSTREAM/* (default
//     https://opencode.ai/zen/v1) and streams responses back untouched;
//   - GETs (model catalog) are open; every write (POST) must carry
//     x-zen-relay-token matching the shared token file, so other local
//     processes or browser pages cannot spend the allowance through this
//     port. The token file is created 0600 if absent;
//   - exits on its own after ZEN_RELAY_IDLE_MS with no requests (default
//     15 min), so nothing runs until some pi process needs it;
//   - single instance via a pid file; access log records method, path,
//     status and duration only, never bodies.
//
// Runtime state (token, pid, logs) lives in $ZEN_RELAY_STATE_DIR (default
// ~/.local/share/pi-opencode-free-sidecar), never in the extension folder.

import { randomBytes } from "node:crypto";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const VERSION = "0.2.0";
const PORT = Number(process.env.ZEN_RELAY_PORT ?? 8787);
const UPSTREAM = (process.env.ZEN_RELAY_UPSTREAM ?? "https://opencode.ai/zen/v1").replace(/\/+$/, "");
const IDLE_MS = Number(process.env.ZEN_RELAY_IDLE_MS ?? 15 * 60 * 1000);
const STATE_DIR = process.env.ZEN_RELAY_STATE_DIR
	?? join(homedir(), ".local", "share", "pi-opencode-free-sidecar");
const TOKEN_FILE = join(STATE_DIR, "token");
const PID_FILE = join(STATE_DIR, "relay.pid");
const ACCESS_LOG = process.env.ZEN_RELAY_ACCESS_LOG ?? join(STATE_DIR, "access.log");
const TOKEN_HEADER = "x-zen-relay-token";

const HOP_BY_HOP = [
	"host",
	"content-length",
	"connection",
	"keep-alive",
	"transfer-encoding",
	"upgrade",
	"proxy-authorization",
	"te",
	"trailer",
	"proxy-connection",
];

function ensureToken() {
	mkdirSync(STATE_DIR, { recursive: true, mode: 0o700 });
	if (existsSync(TOKEN_FILE)) {
		const existing = readFileSync(TOKEN_FILE, "utf8").trim();
		if (existing.length > 0) return existing;
	}
	const token = randomBytes(32).toString("hex");
	const fd = openSync(TOKEN_FILE, "wx", 0o600);
	try {
		writeFileSync(fd, `${token}\n`);
	} finally {
		closeSync(fd);
	}
	return token;
}

function logLine(line) {
	try {
		mkdirSync(STATE_DIR, { recursive: true, mode: 0o700 });
		const fd = openSync(ACCESS_LOG, "a");
		try {
			writeFileSync(fd, `${new Date().toISOString()} ${line}\n`);
		} finally {
			closeSync(fd);
		}
	} catch {
		// logging must never take the relay down
	}
}

// Single-instance guard: adopt an existing live relay rather than racing it.
if (existsSync(PID_FILE)) {
	try {
		const other = Number(readFileSync(PID_FILE, "utf8").trim());
		if (Number.isFinite(other) && other > 0) {
			process.kill(other, 0); // throws if dead
			console.log(`another relay is already running (pid ${other}); exiting`);
			process.exit(0);
		}
	} catch {
		// dead or unreadable: take over
	}
}

const token = ensureToken();
try {
	mkdirSync(STATE_DIR, { recursive: true, mode: 0o700 });
	writeFileSync(PID_FILE, `${process.pid}\n`);
} catch {
	// pid file is best-effort bookkeeping
}

let lastActivity = Date.now();
const idleTimer = setInterval(() => {
	if (Date.now() - lastActivity > IDLE_MS) {
		logLine(`IDLE_EXIT after ${Math.round((Date.now() - lastActivity) / 1000)}s quiet`);
		cleanupExit();
	}
}, Math.min(60_000, Math.max(1_000, Math.floor(IDLE_MS / 4))));

function cleanupExit() {
	try {
		unlinkSync(PID_FILE);
	} catch {
		// already gone
	}
	process.exit(0);
}
process.on("SIGTERM", cleanupExit);
process.on("SIGINT", cleanupExit);

Bun.serve({
	port: PORT,
	hostname: "127.0.0.1",
	idleTimeout: 120,
	async fetch(req, server) {
		lastActivity = Date.now();
		const url = new URL(req.url);
		if (url.pathname === "/healthz") {
			return Response.json({
				ok: true,
				name: "pi-opencode-free-sidecar",
				version: VERSION,
				runtime: `bun/${Bun.version}`,
				upstream: UPSTREAM,
			});
		}
		const suffix = url.pathname.replace(/^\/zen\/v1/, "");
		if (req.method !== "GET" && req.method !== "HEAD") {
			const got = req.headers.get(TOKEN_HEADER) ?? "";
			if (got !== token) {
				logLine(`${req.method} ${suffix} 401 unauthorized (missing or wrong ${TOKEN_HEADER})`);
				return new Response(
					JSON.stringify({
						error: `pi-opencode-free-sidecar: requests must carry the ${TOKEN_HEADER} header (see the extension README)`,
					}),
					{ status: 401, headers: { "content-type": "application/json" } },
				);
			}
		}
		const target = UPSTREAM + suffix + url.search;

		const headers = new Headers(req.headers);
		for (const name of HOP_BY_HOP) headers.delete(name);
		headers.delete(TOKEN_HEADER); // local hop only; upstream must not see it
		// Keep the body decodable end to end; re-encoding an SSE stream here
		// would only add risk.
		headers.set("accept-encoding", "identity");

		const body = req.method === "GET" || req.method === "HEAD" ? undefined : await req.arrayBuffer();
		const started = Date.now();
		let upstreamRes;
		try {
			upstreamRes = await fetch(target, { method: req.method, headers, body });
		} catch (error) {
			logLine(`${req.method} ${suffix} UPSTREAM_ERROR ${String(error)}`);
			return new Response(`zen relay: upstream fetch failed: ${String(error)}`, { status: 502 });
		}
		logLine(`${req.method} ${suffix} ${upstreamRes.status} ${Date.now() - started}ms`);
		return new Response(upstreamRes.body, {
			status: upstreamRes.status,
			statusText: upstreamRes.statusText,
			headers: upstreamRes.headers,
		});
	},
});

console.log(
	`pi-opencode-free-sidecar relay v${VERSION} on http://127.0.0.1:${PORT} -> ${UPSTREAM} (bun ${Bun.version}, idle exit ${IDLE_MS}ms, state ${STATE_DIR})`,
);
