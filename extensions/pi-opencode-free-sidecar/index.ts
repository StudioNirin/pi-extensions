/**
 * pi-opencode-free-sidecar
 *
 * One extension doing two jobs:
 *
 *  1. The OpenCode Zen free-model provider, vendored from
 *     @rabden/pi-opencode-zen@0.3.0 (MIT; vendor/pi-opencode-zen/, kept
 *     byte-identical for clean re-syncs). It shapes every Zen request for
 *     the free-tier gate: official UA, fingerprint headers stripped,
 *     SortableID session headers, marker prompt, text-protocol tool calls.
 *
 *  2. A Bun transport relay for the outbound hop (relay.js). Zen classifies
 *     free-tier traffic by CLIENT CLASS, decided by the transport
 *     fingerprint: Bun-built clients (the official OpenCode CLI, pi's own
 *     compiled binary) pass; Node/undici clients get
 *     `429 FreeUsageLimitError` regardless of request content, verified
 *     2026-11-12 with identical shaped requests on two pi versions each.
 *     pi hosted inside Node (PiChamber's session daemon) is therefore
 *     locked out, so pi sends its shaped requests to this relay over plain
 *     HTTP on loopback and Bun performs the real HTTPS request.
 *
 * Ordering contract inside this file: `PI_ZEN_BASE_URL` is defaulted at
 * module scope, and the vendored provider is imported DYNAMICALLY in the
 * factory, so the env is always set before the vendored module evaluates
 * `const BASE_URL = process.env.PI_ZEN_BASE_URL ?? ...`. Do not turn that
 * import into a static one.
 *
 * Lifecycle: the relay is spawned on demand (detached, from `bun`), adopted
 * if already running, and self-exits when idle (default 15 min), so no boot
 * service is needed. A fetch guard restarts it transparently if it died
 * mid-session. Writes to the relay require a shared token (0600 file) so
 * other local processes cannot spend the allowance; models.json carries it
 * as a provider header, seeded by install.sh and self-healed here.
 *
 * Env (all optional):
 *   PI_ZEN_BASE_URL      set to bypass the relay entirely (advanced)
 *   PI_ZEN_RELAY_PORT    loopback port (default 8787)
 *   PI_ZEN_RELAY_BUN     path to the bun binary (default: PATH search)
 *   PI_ZEN_RELAY_SCRIPT  path to relay.js (default: next to this file)
 *   PI_ZEN_RELAY_IDLE_MS relay idle self-exit (default 900000)
 *   PI_FREE_SIDECAR_STATE_DIR  token/pid/log dir (default
 *                        ~/.local/share/pi-opencode-free-sidecar)
 * All remaining PI_ZEN_* vars are the vendored provider's (see its header).
 *
 * Commands: /opencode-free-sidecar status | restart | stop
 */

import { spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, renameSync, statSync, unlinkSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { delimiter, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const PROVIDER_ID = "opencode-zen";
const TOKEN_HEADER = "x-zen-relay-token";
const PORT = Number(process.env.PI_ZEN_RELAY_PORT ?? 8787);
const RELAY_ORIGIN = `http://127.0.0.1:${PORT}`;
const LOOPBACK_BASE = `${RELAY_ORIGIN}/zen/v1`;

// Must happen before the vendored provider module evaluates (see ordering
// contract above): default the base to the relay, honour an explicit
// override, and remember whether the relay is ours to manage.
process.env.PI_ZEN_BASE_URL = process.env.PI_ZEN_BASE_URL?.trim() || LOOPBACK_BASE;
const RELAY_OWNED = process.env.PI_ZEN_BASE_URL === LOOPBACK_BASE;

const STATE_DIR =
	process.env.PI_FREE_SIDECAR_STATE_DIR ?? join(homedir(), ".local", "share", "pi-opencode-free-sidecar");
const TOKEN_FILE = join(STATE_DIR, "token");
const PID_FILE = join(STATE_DIR, "relay.pid");
const LOG_FILE = join(STATE_DIR, "relay.log");
const AGENT_DIR = process.env.PI_CODING_AGENT_DIR ?? join(homedir(), ".pi", "agent");

interface EnsureResult {
	ok: boolean;
	detail: string;
}

function findBun(): string | null {
	const candidates = [
		process.env.PI_ZEN_RELAY_BUN,
		join(homedir(), ".local", "bin", "bun"),
		"/usr/local/bin/bun",
		"/usr/bin/bun",
	];
	for (const candidate of candidates) {
		if (candidate && existsSync(candidate)) return candidate;
	}
	for (const dir of (process.env.PATH ?? "").split(delimiter)) {
		if (!dir) continue;
		const candidate = join(dir, "bun");
		try {
			if (statSync(candidate).isFile()) return candidate;
		} catch {
			// not here
		}
	}
	return null;
}

function ensureToken(): string {
	writeTokenDir();
	try {
		const existing = readFileSync(TOKEN_FILE, "utf8").trim();
		if (existing.length > 0) return existing;
	} catch {
		// fall through and create
	}
	// The relay creates the token the same way if it gets there first; both
	// paths are create-only, so neither can rotate the other's secret.
	const token = randomBytes(32).toString("hex");
	try {
		const fd = openSync(TOKEN_FILE, "wx", 0o600);
		try {
			writeFileSync(fd, `${token}\n`);
		} finally {
			closeSync(fd);
		}
	} catch {
		// lost a creation race: read the winner's value
	}
	return readFileSync(TOKEN_FILE, "utf8").trim();
}

function writeTokenDir(): void {
	try {
		mkdirSync(STATE_DIR, { recursive: true, mode: 0o700 });
	} catch {
		// exists
	}
}

function readPid(): number | null {
	try {
		const pid = Number(readFileSync(PID_FILE, "utf8").trim());
		return Number.isFinite(pid) && pid > 0 ? pid : null;
	} catch {
		return null;
	}
}

async function relayHealth(timeoutMs = 1500): Promise<Record<string, unknown> | null> {
	try {
		const response = await fetch(`${RELAY_ORIGIN}/healthz`, { signal: AbortSignal.timeout(timeoutMs) });
		if (!response.ok) return null;
		const body = (await response.json()) as Record<string, unknown> | null;
		return body && typeof body.ok === "boolean" ? body : null;
	} catch {
		return null;
	}
}

let ensuring: Promise<EnsureResult> | null = null;

function ensureRelay(): Promise<EnsureResult> {
	ensuring ??= doEnsureRelay().finally(() => {
		ensuring = null;
	});
	return ensuring;
}

async function doEnsureRelay(): Promise<EnsureResult> {
	if (!RELAY_OWNED) return { ok: true, detail: "relay not managed (PI_ZEN_BASE_URL overridden)" };
	if (await relayHealth()) return { ok: true, detail: `relay already running on ${RELAY_ORIGIN}` };

	const bun = findBun();
	if (!bun) {
		return {
			ok: false,
			detail: `bun not found; install it (https://bun.sh) or set PI_ZEN_RELAY_BUN. Zen free models need the relay because they reject Node's transport fingerprint.`,
		};
	}
	let script: string;
	try {
		script = process.env.PI_ZEN_RELAY_SCRIPT ?? join(dirname(fileURLToPath(import.meta.url)), "relay.js");
	} catch {
		return { ok: false, detail: "cannot locate relay.js; set PI_ZEN_RELAY_SCRIPT" };
	}
	if (!existsSync(script)) return { ok: false, detail: `relay script missing: ${script}` };

	writeTokenDir();
	ensureToken();
	let logFd: number;
	try {
		logFd = openSync(LOG_FILE, "a");
	} catch {
		logFd = openSync("/dev/null", "a");
	}
	const child = spawn(bun, [script], {
		detached: true,
		stdio: ["ignore", logFd, logFd],
		cwd: STATE_DIR,
		env: {
			...process.env,
			ZEN_RELAY_PORT: String(PORT),
			ZEN_RELAY_STATE_DIR: STATE_DIR,
			ZEN_RELAY_IDLE_MS: process.env.PI_ZEN_RELAY_IDLE_MS ?? "900000",
		},
	});
	child.unref();

	const deadline = Date.now() + 4000;
	while (Date.now() < deadline) {
		if (await relayHealth()) {
			return { ok: true, detail: `relay started on ${RELAY_ORIGIN} (pid ${readPid() ?? child.pid})` };
		}
		await new Promise((resolve) => setTimeout(resolve, 125));
	}
	return { ok: false, detail: `relay did not answer /healthz within 4 s; see ${LOG_FILE}` };
}

/**
 * Self-heal the models.json provider header that carries the relay token,
 * but only when the opencode-zen provider is already pointed at our relay
 * (install.sh seeds the baseUrl; we never create or redirect provider
 * config ourselves).
 */
function ensureModelsJsonTokenHeader(): void {
	if (!RELAY_OWNED) return;
	const modelsPath = join(AGENT_DIR, "models.json");
	let config: Record<string, unknown>;
	try {
		config = JSON.parse(readFileSync(modelsPath, "utf8")) as Record<string, unknown>;
	} catch {
		return;
	}
	const providers = config.providers as Record<string, Record<string, unknown>> | undefined;
	const zen = providers?.[PROVIDER_ID];
	if (!zen || zen.baseUrl !== LOOPBACK_BASE) return;
	const headers = (zen.headers ?? {}) as Record<string, string>;
	if (headers[TOKEN_HEADER]) return;
	headers[TOKEN_HEADER] = `!cat ${TOKEN_FILE}`;
	zen.headers = headers;
	try {
		const tmp = `${modelsPath}.pi-opencode-free-sidecar.tmp`;
		writeFileSync(tmp, `${JSON.stringify(config, null, 2)}\n`);
		renameSync(tmp, modelsPath);
	} catch {
		// best effort; preflight notify tells the user if requests then 401
	}
}

/**
 * Outer fetch wrapper (installed AFTER the vendored patch, so it sees the
 * loopback hop it guards): if the relay died since we last checked, restart
 * it and retry the request once.
 */
function installRelayGuard(): void {
	if (!RELAY_OWNED) return;
	type GuardedFetch = typeof globalThis.fetch & { __freeSidecarGuard?: boolean };
	const inner = globalThis.fetch as GuardedFetch;
	if (inner.__freeSidecarGuard) return;
	const guarded = (async (input: Parameters<typeof fetch>[0], init?: RequestInit): Promise<Response> => {
		const url =
			typeof input === "string"
				? input
				: input instanceof URL
					? input.href
					: ((input as Request)?.url ?? "");
		if (!url.startsWith(`${RELAY_ORIGIN}/`)) return inner(input, init);
		try {
			return await inner(input, init);
		} catch (error) {
			const ensured = await ensureRelay();
			if (!ensured.ok) throw error;
			return inner(input, init);
		}
	}) as GuardedFetch;
	guarded.__freeSidecarGuard = true;
	globalThis.fetch = guarded;
}

function stopRelay(): Promise<string> {
	return (async () => {
		const pid = readPid();
		if (!pid) return "relay is not ours to stop (no pid file; is it a foreign process on this port?)";
		try {
			process.kill(pid, "SIGTERM");
		} catch {
			// already gone
		}
		const deadline = Date.now() + 2000;
		while (Date.now() < deadline && (await relayHealth(300))) {
			await new Promise((resolve) => setTimeout(resolve, 100));
		}
		try {
			unlinkSync(PID_FILE);
		} catch {
			// already gone
		}
		return `relay stopped (pid ${pid})`;
	})();
}

let bootIssue: string | null = null;

export default async function (pi: ExtensionAPI): Promise<void> {
	if (RELAY_OWNED) {
		const ensured = await ensureRelay();
		if (ensured.ok) ensureModelsJsonTokenHeader();
		else bootIssue = ensured.detail;
	}

	// Dynamic import is the ordering contract: env set above, provider
	// module evaluated now.
	const zen = (await import("./vendor/pi-opencode-zen/index.ts")) as {
		default: (api: ExtensionAPI) => void;
	};
	zen.default(pi);

	installRelayGuard();

	pi.registerCommand("opencode-free-sidecar", {
		description: "OpenCode Zen Bun relay: status | restart | stop",
		handler: async (args, ctx) => {
			const action = (args ?? "").trim().toLowerCase().split(/\s+/)[0] ?? "status";
			if (action === "stop") {
				ctx.ui?.notify?.(RELAY_OWNED ? await stopRelay() : "relay not managed (PI_ZEN_BASE_URL overridden)", "info");
				return;
			}
			if (action === "restart") {
				if (RELAY_OWNED) await stopRelay();
				const ensured = await ensureRelay();
				ctx.ui?.notify?.(`opencode-free-sidecar restart: ${ensured.detail}`, ensured.ok ? "info" : "error");
				return;
			}
			const health = await relayHealth();
			if (!health) {
				ctx.ui?.notify?.(`relay: not running on ${RELAY_ORIGIN} (it starts on demand; last attempt: ${bootIssue ?? "not attempted"}`, "warning");
				return;
			}
			const pid = readPid();
			const ours = pid !== null;
			ctx.ui?.notify?.(
				`relay: ${String(health.name ?? "?")} v${String(health.version ?? "?")} (${String(health.runtime ?? "?")}) on ${RELAY_ORIGIN} -> ${String(health.upstream ?? "?")}; ${ours ? `ours, pid ${pid}` : "foreign process, not ours to manage"}`,
				"info",
			);
		},
	});

	pi.on("session_start", (_event, ctx) => {
		if (bootIssue) {
			ctx.ui?.notify?.(`opencode-free-sidecar: ${bootIssue}`, "warning");
			bootIssue = null;
		}
		if (RELAY_OWNED) {
			void ensureRelay().then((ensured) => {
				if (!ensured.ok) ctx.ui?.notify?.(`opencode-free-sidecar: ${ensured.detail}`, "warning");
			});
		}
	});
}
