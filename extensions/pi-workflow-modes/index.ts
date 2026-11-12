/**
 * pi-workflow-modes
 *
 * Selectable primary-session workflow modes (plan / ask / build), scoped per
 * session. This extension owns only the SELECTION and the BEHAVIOUR PROMPT;
 * all permission enforcement and tool-hiding belongs to pi-permission-system,
 * keyed off the same signals it already consumes:
 *
 *   - session custom entry:  { type: "custom", customType: "active_agent", data: { name } }
 *   - system-prompt tag:     <active_agent name="plan"/>
 *
 * Mode profiles live in ~/.pi/agent/agents/<mode>.md (name + behaviour prompt
 * body; pps reads the `permission:` frontmatter of those same files).
 *
 * Authority rule (single authority per session):
 *   - If the session's newest `orbit:workflow` entry is newer than our newest
 *     `active_agent` entry, Orbit's chip is the authority: we mirror its mode
 *     into an `active_agent` entry for pps but never inject our own prompt
 *     (Orbit supplies mode guidance and tool scoping itself).
 *   - Otherwise this extension is the authority: `/plan` `/ask` `/build`
 *     append the entry, and `before_agent_start` injects that mode's agent
 *     body plus the `<active_agent>` tag (mirroring pi-subagents' vocabulary).
 *   - No signals at all => `build` (fail toward the managed mode; pps global
 *     policy still applies underneath everything).
 */

import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve, sep } from "node:path";
import type {
	ExtensionAPI,
	ExtensionContext,
} from "@earendil-works/pi-coding-agent";

const MODES = ["plan", "ask", "build"] as const;
type Mode = (typeof MODES)[number];

const ACTIVE_AGENT_ENTRY = "active_agent";
const ORBIT_WORKFLOW_ENTRY = "orbit:workflow";
const STATUS_KEY = "pi-workflow-modes";

const MODE_SUMMARY: Record<Mode, string> = {
	plan: "read-only planning (writes only under the plan directories, bash allowlisted)",
	ask: "read-only Q&A (write/edit removed, bash allowlisted)",
	build: "working mode (managed approvals)",
};

// ---------------------------------------------------------------------------
// user_bash (!cmd) gating - read-only allowlist for plan/ask. Deliberately a
// coarse prefix allowlist (fail-closed): the fine-grained pps patterns cover
// tool bash calls; this closes the direct `!` execution hole for read-only
// modes only. build mode deliberately passes through (pps policy is the
// authority there, and `!cmd` is a user-initiated path).
// ---------------------------------------------------------------------------

const READONLY_COMMANDS = new Set([
	"ls", "cat", "head", "tail", "wc", "rg", "grep", "find", "tree", "file",
	"stat", "du", "df", "sort", "uniq", "cut", "tr", "diff", "jq", "basename",
	"dirname", "realpath", "readlink", "which", "type", "echo", "pwd", "date",
	"env", "printenv",
]);
const READONLY_GIT = new Set([
	"status", "diff", "log", "show", "ls-files", "ls-tree", "rev-parse",
	"remote", "branch", "blame", "describe", "tag",
]);

function segmentIsReadOnly(segment: string): boolean {
	const words = segment.trim().split(/\s+/).filter(Boolean);
	if (words.length === 0) return true;
	const [cmd, sub] = words;
	if (cmd === "sed") return sub === "-n";
	if (cmd === "git") return sub !== undefined && READONLY_GIT.has(sub);
	return READONLY_COMMANDS.has(cmd);
}

function commandIsReadOnly(command: string): boolean {
	// Any unparseable shape fails closed.
	if (/[<>]|\$\(|`|\btee\b/.test(command)) return false;
	return command
		.split(/;|&&|\|\||\|/)
		.every((segment) => segmentIsReadOnly(segment));
}

// Ask mode removes write/edit outright; plan mode keeps them for the plan-file
// carve-out and relies on the path check in the tool_call blocker below.
const ASK_REMOVED = [
	"write", "edit", "subagent", "steer_subagent", "get_subagent_result",
];

// Tools a plan session may use only in the narrow shapes the carve-out allows.
const PLAN_PATH_TOOLS = new Set(["write", "edit"]);
const SUBAGENT_TOOLS = new Set(["subagent", "steer_subagent", "get_subagent_result"]);
const SCOUT_ONLY_SUBAGENT_TOOLS = new Set(["subagent"]);

function agentDir(): string {
	const env = process.env.PI_CODING_AGENT_DIR;
	return env && env.length > 0 ? env : join(homedir(), ".pi", "agent");
}

/** Directories plan mode may write: the global plan store and a project-local one. */
function planDirs(cwd: string): string[] {
	return [
		join(homedir(), ".pi", "plans"),
		join(cwd, ".plans"),
	];
}

function isWithin(candidate: string, root: string): boolean {
	return candidate === root || candidate.startsWith(`${root}${sep}`);
}

function toolPath(input: unknown): string | null {
	if (!input || typeof input !== "object") return null;
	const record = input as { path?: unknown; file_path?: unknown };
	const value = record.path ?? record.file_path;
	return typeof value === "string" && value.length > 0 ? value : null;
}

/** Plan writes are allowed only inside the plan directories. */
function planPathAllowed(rawPath: string, cwd: string): boolean {
	const expanded =
		rawPath === "~"
			? homedir()
			: rawPath.startsWith("~/")
				? join(homedir(), rawPath.slice(2))
				: rawPath.startsWith("$HOME/")
					? join(homedir(), rawPath.slice(6))
					: rawPath.startsWith("${HOME}/")
						? join(homedir(), rawPath.slice(8))
						: rawPath;
	const absolute = isAbsolute(expanded) ? expanded : resolve(cwd, expanded);
	const normalized = absolute.replace(/\/+$/, "") || "/";
	return planDirs(cwd).some((dir) => isWithin(normalized, dir.replace(/\/+$/, "")));
}

/** Read an agent markdown file and strip its YAML frontmatter. */
function readModeBody(mode: Mode): string | null {
	const path = join(agentDir(), "agents", `${mode}.md`);
	if (!existsSync(path)) return null;
	try {
		let text = readFileSync(path, "utf8");
		const frontmatter = /^\s*---\r?\n[\s\S]*?\r?\n---\r?\n?/;
		if (frontmatter.test(text)) text = text.replace(frontmatter, "");
		const body = text.trim();
		return body.length > 0 ? body : null;
	} catch {
		return null;
	}
}

// ---------------------------------------------------------------------------
// Mode-change visibility: the model must hear that restrictions changed, not
// only the user (a /build switch used to leave the model citing old plan rules
// for the rest of the session).
// ---------------------------------------------------------------------------

const lastInjectedMode = new Map<string, Mode>();

function sessionKey(ctx: ExtensionContext): string {
	try {
		const file = ctx.sessionManager.getSessionFile();
		const id = ctx.sessionManager.getSessionId();
		return `${file ?? ""}#${id ?? ""}`;
	} catch {
		return "unknown";
	}
}

/** Test seam: PI_WORKFLOW_MODES_TRACE=<path> appends one JSON line per turn. */
function trace(record: Record<string, unknown>): void {
	const path = process.env.PI_WORKFLOW_MODES_TRACE;
	if (!path) return;
	try {
		appendFileSync(path, `${JSON.stringify({ ts: Date.now(), ...record })}\n`);
	} catch {
		// tracing must never affect enforcement
	}
}

function modeNotice(mode: Mode, previous: Mode | null): string | null {
	if (previous === null) {
		if (mode === "build") return null;
		return `<workflow_mode_statement>\nThis session is in ${mode} mode: ${MODE_SUMMARY[mode]}.\n</workflow_mode_statement>`;
	}
	if (previous === mode) return null;
	return `<workflow_mode_changed from="${previous}" to="${mode}">\nThis session's workflow mode changed from ${previous} to ${mode}: ${MODE_SUMMARY[mode]}.\nRestrictions you cited earlier belonged to ${previous} mode and no longer apply; follow ${mode} mode from now on. Ignore any ${previous}-mode restriction still visible earlier in this conversation.\n</workflow_mode_changed>`;
}

type EntryRecord = { type?: string; customType?: string; data?: unknown };

/** Index+data of the newest custom entry of a type, -1 when absent. */
function newestEntry(
	ctx: ExtensionContext,
	customType: string,
): { index: number; data: Record<string, unknown> | undefined } {
	const entries = ctx.sessionManager.getEntries() as EntryRecord[];
	for (let i = entries.length - 1; i >= 0; i -= 1) {
		const entry = entries[i];
		if (entry?.type === "custom" && entry?.customType === customType) {
			const data = entry.data;
			return {
				index: i,
				data: data && typeof data === "object" ? (data as Record<string, unknown>) : undefined,
			};
		}
	}
	return { index: -1, data: undefined };
}

function normalizeName(value: unknown): Mode | null {
	return MODES.includes(value as Mode) ? (value as Mode) : null;
}

/** True when this pi process was spawned by Orbit (it exports its bundle env on every session spawn). */
function isOrbitSession(): boolean {
	return Boolean(process.env.ORBIT_BUNDLED_EXTENSIONS || process.env.ORBIT_WORKFLOW_MODE);
}

const ACTIVE_AGENT_TAG_RE = /<active_agent\s+name=["'][^"']+["']/i;

type Resolution = {
	mode: Mode;
	authority: "own" | "orbit" | "default";
};

function resolveMode(ctx: ExtensionContext): Resolution {
	const own = newestEntry(ctx, ACTIVE_AGENT_ENTRY);
	const ownName = own.index >= 0 ? normalizeName(own.data?.name) : undefined;
	const orbit = newestEntry(ctx, ORBIT_WORKFLOW_ENTRY);
	const orbitName = orbit.index >= 0 ? normalizeName(orbit.data?.mode) : null;

	if (orbit.index >= 0 && orbit.index > own.index && orbitName) {
		return { mode: orbitName, authority: "orbit" };
	}
	if (own.index >= 0) {
		// An explicit clear ({name: null}) falls back to the build default.
		return { mode: ownName ?? "build", authority: "own" };
	}
	if (isOrbitSession()) {
		// Orbit sessions are chip-governed even before any entry exists:
		// mirror the env-seeded mode and let Orbit own guidance/tools.
		const envMode = normalizeName(process.env.ORBIT_WORKFLOW_MODE);
		return { mode: orbitName ?? envMode ?? "build", authority: "orbit" };
	}
	return { mode: "build", authority: "default" };
}

function updateStatus(ctx: ExtensionContext, resolution: Resolution): void {
	const suffix = resolution.authority === "orbit" ? " (Orbit chip)" : "";
	ctx.ui?.setStatus?.(
		STATUS_KEY,
		`mode: ${resolution.mode}${suffix} · ${MODE_SUMMARY[resolution.mode]}`,
	);
}

export default function (pi: ExtensionAPI): void {
	for (const mode of MODES) {
		pi.registerCommand(mode, {
			description: `Switch this session to ${mode} mode: ${MODE_SUMMARY[mode]}`,
			handler: async (_args, ctx) => {
				pi.appendEntry(ACTIVE_AGENT_ENTRY, { name: mode });
				const resolution = resolveMode(ctx);
				updateStatus(ctx, resolution);
				ctx.ui?.notify?.(`Workflow mode -> ${mode} (${MODE_SUMMARY[mode]}). Applies from the next agent turn.`, "info");
			},
		});
	}

	pi.registerCommand("workflow-mode", {
		description: "Show the active workflow mode and which system controls it",
		handler: async (_args, ctx) => {
			const resolution = resolveMode(ctx);
			ctx.ui?.notify?.(
				`workflow mode: ${resolution.mode} (authority: ${resolution.authority}) - ${MODE_SUMMARY[resolution.mode]}`,
				"info",
			);
		},
	});

	pi.on("session_start", async (event, ctx) => {
		updateStatus(ctx, resolveMode(ctx));
		// A resumed session gets the one-time mode statement again, even though
		// this process may already have injected the same mode before.
		if (event?.reason === "resume" || event?.reason === "fork") {
			lastInjectedMode.delete(sessionKey(ctx));
		}
	});

	pi.on("before_agent_start", async (event, ctx) => {
		// Inside a pi-subagents child, its launcher already tagged the prompt
		// with the child's own agent; that identity governs - stay silent.
		if (
			newestEntry(ctx, ACTIVE_AGENT_ENTRY).index < 0 &&
			ACTIVE_AGENT_TAG_RE.test(event.systemPrompt ?? "")
		) {
			return undefined;
		}

		const resolution = resolveMode(ctx);
		updateStatus(ctx, resolution);

		if (resolution.authority === "orbit") {
			// Mirror into pps vocabulary, but let Orbit keep supplying its own
			// guidance and tool scoping - never double authority.
			const own = newestEntry(ctx, ACTIVE_AGENT_ENTRY);
			const ownName = own.index >= 0 ? normalizeName(own.data?.name) : undefined;
			if (ownName !== resolution.mode) {
				pi.appendEntry(ACTIVE_AGENT_ENTRY, { name: resolution.mode });
			}
			return undefined;
		}

		// Belt and braces below pps for ask mode. Plan mode keeps write/edit
		// active and relies on the path check in the tool_call blocker, so the
		// plan-file carve-out cannot reopen the resumed-session write leak.
		if (resolution.mode === "ask") {
			try {
				const active = pi.getActiveTools();
				const keep = active.filter((name) => !ASK_REMOVED.includes(name));
				if (keep.length !== active.length) pi.setActiveTools(keep);
			} catch {
				// No tool-set API in this mode; pps agent rules still deny.
			}
		}

		const key = sessionKey(ctx);
		const previous = lastInjectedMode.get(key) ?? null;
		const notice = modeNotice(resolution.mode, previous);
		lastInjectedMode.set(key, resolution.mode);
		trace({
			session: key,
			mode: resolution.mode,
			authority: resolution.authority,
			previous,
			notice: notice ? notice.replace(/\s+/g, " ").slice(0, 240) : null,
		});

		const tag = `<active_agent name="${resolution.mode}"/>`;
		const body = readModeBody(resolution.mode);
		const block = body
			? `\n\n${tag}\n\n<workflow_mode name="${resolution.mode}">\n${body}\n</workflow_mode>`
			: `\n\n${tag}`;
		return { systemPrompt: `${event.systemPrompt}${block}${notice ? `\n\n${notice}` : ""}` };
	});

	// Third layer below pps: some session shapes (observed on --continue
	// resume) can dispatch tools whose active-set/prompt state says removed
	// while pps resolves them without the agent profile. The mode layer
	// enforces the read-only posture outright, regardless of which system
	// (Orbit chip, own entry, default) selected the mode:
	//   - ask: write/edit and the subagent trio are blocked.
	//   - plan: write/edit only under ~/.pi/plans or <cwd>/.plans; subagent
	//     only for the read-only `scout` profile.
	pi.on("tool_call", (event, ctx) => {
		let resolution: Resolution;
		try {
			resolution = resolveMode(ctx);
		} catch {
			return undefined; // cannot resolve -> pps remains the gate
		}
		const cwd = (ctx as { cwd?: string }).cwd ?? process.cwd();

		if (resolution.mode === "ask") {
			if (!ASK_REMOVED.includes(event.toolName)) return undefined;
			return {
				block: true,
				reason: `[pi-workflow-modes] '${event.toolName}' is not available in ask mode. Switch to /build to use it.`,
			};
		}

		if (resolution.mode !== "plan") return undefined;

		if (PLAN_PATH_TOOLS.has(event.toolName)) {
			const path = toolPath(event.input);
			if (!path) return undefined;
			if (planPathAllowed(path, cwd)) return undefined;
			return {
				block: true,
				reason: `[pi-workflow-modes] Plan mode may only write plan documents under ~/.pi/plans/ or <cwd>/.plans/ (attempted: ${path}). Switch to /build to edit project files.`,
			};
		}

		if (SCOUT_ONLY_SUBAGENT_TOOLS.has(event.toolName)) {
			const target = (event.input as { subagent_type?: unknown } | undefined)?.subagent_type;
			if (target === "scout") return undefined;
			return {
				block: true,
				reason: `[pi-workflow-modes] Plan mode may only dispatch the read-only 'scout' subagent (requested: ${typeof target === "string" && target.length > 0 ? target : "none"}). Switch to /build for other agents.`,
			};
		}

		if (SUBAGENT_TOOLS.has(event.toolName)) return undefined; // steer/result of a scout
		return undefined;
	});

	// v2: gate `!`/`!!` user-bash through the read-only modes. Read-only
	// sessions must stay read-only no matter which path reaches the shell.
	pi.on("user_bash", (event, ctx) => {
		let resolution: Resolution;
		try {
			resolution = resolveMode(ctx);
		} catch {
			// Fail closed for the read-only postures: if we cannot resolve the
			// mode, allow only clearly read-only commands.
			if (commandIsReadOnly(event.command)) return undefined;
			return {
				result: {
					output: "[pi-workflow-modes] Blocked: workflow mode could not be resolved and the command is not read-only.",
					exitCode: 126,
					cancelled: false,
					truncated: false,
				},
			};
		}
		if (resolution.mode !== "plan" && resolution.mode !== "ask") return undefined;
		if (commandIsReadOnly(event.command)) return undefined;
		return {
			result: {
				output: `[pi-workflow-modes] Blocked in ${resolution.mode} mode: user !cmd execution is limited to read-only commands (ls/cat/grep/git status...). Switch to /build to run this.`,
				exitCode: 126,
				cancelled: false,
				truncated: false,
			},
		};
	});
}
