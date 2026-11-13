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
 *   - This extension is the authority: `/plan` `/ask` `/build` append the
 *     entry, and `before_agent_start` injects that mode's agent body plus the
 *     `<active_agent>` tag (mirroring pi-subagents' vocabulary).
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
const STATUS_KEY = "pi-workflow-modes";

const MODE_SUMMARY: Record<Mode, string> = {
	plan: "read-only planning (writes only under the plan directories, bash allowlisted)",
	ask: "read-only Q&A (write/edit removed, bash allowlisted)",
	build: "working mode (managed approvals)",
};

// ---------------------------------------------------------------------------
// user_bash (!cmd) gating - read-only allowlist for plan/ask. pi-permission-
// system registers no user_bash handler, so this is the only check on a
// user-initiated `!cmd`; build mode deliberately passes through (`!cmd` is
// typed by the user, and pps + pi-veto govern the agent's own bash calls).
// Fail closed: a command-name allowlist, so any writer not named here is
// blocked, plus per-command flag denies. `uniq`, `sed`, and `env` are absent
// on purpose: `uniq IN OUT` writes a file, a sed script can carry `w`/`e`
// commands no option check can see, and `env CMD` is a wrapper. Caught:
// exact flags, `--flag=value` attachments, and getopt_long abbreviations.
// Not caught: exotic short-flag clusters (`sort -bo out`).
// ---------------------------------------------------------------------------

const READONLY_COMMANDS = new Set([
	"ls", "cat", "head", "tail", "wc", "rg", "grep", "find", "tree", "file",
	"stat", "du", "df", "sort", "cut", "tr", "diff", "jq", "basename",
	"dirname", "realpath", "readlink", "which", "type", "echo", "printf",
	"pwd", "date", "printenv",
]);
const READONLY_GIT = new Set([
	"status", "diff", "log", "show", "ls-files", "ls-tree", "rev-parse",
	"blame", "describe",
]);
// Branch/tag listing flags: with one present, a following bare word is a
// filter, not a name to create. Without one, `git branch foo` creates.
const GIT_LIST_FLAGS = new Set([
	"-v", "-vv", "-a", "-r", "-l", "--list", "--all", "--remotes",
	"--show-current", "--verbose",
]);

const DENIED_FLAGS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
	["find", new Set([
		"-delete", "-exec", "-execdir", "-ok", "-okdir",
		"-fprint", "-fprint0", "-fprintf", "-fls",
	])],
	["rg", new Set(["--pre", "--hostname-bin"])],
	["sort", new Set(["-o", "--output"])],
	["tree", new Set(["-o", "--outfile"])],
	["file", new Set(["-C", "--compile"])],
	["git", new Set(["--output"])],
]);

function hasDeniedFlag(cmd: string, words: readonly string[]): boolean {
	const denied = DENIED_FLAGS.get(cmd);
	if (denied === undefined) return false;
	return words.some((word) => {
		if (denied.has(word)) return true;
		if (!word.startsWith("-")) return false;
		if (!word.startsWith("--")) {
			// A short flag also counts inside a cluster: `sort -uo out`,
			// `file -bC`. A long flag cannot hide this way.
			return [...denied].some(
				(flag) => flag.length === 2 && word.slice(1).includes(flag.charAt(1)),
			);
		}
		// Compare the option stem: `--flag=value` is one word, and
		// getopt_long resolves any unambiguous abbreviation, so `--out=`
		// reaches `--output` just the same.
		const stem = word.split("=")[0];
		if (denied.has(stem)) return true;
		for (const flag of denied) {
			if (flag.startsWith("--") && (flag.startsWith(stem) || stem.startsWith(flag))) {
				return true;
			}
		}
		return false;
	});
}

/**
 * `date` sets the clock with `-s`/`--set`, and `-s<value>` is one word, so
 * this checks the leading letter rather than scanning for an `s`: the
 * single-dash long form `-Iseconds` only formats, and a cluster such as
 * `date -us` falls under the "no exotic short-flag clusters" caveat above.
 */
function dateIsReadOnly(words: readonly string[]): boolean {
	return !words.some(
		(word) => word.startsWith("-s") || word === "--set" || word.startsWith("--set="),
	);
}

function gitIsReadOnly(words: readonly string[]): boolean {
	const sub = words[1];
	if (sub === undefined) return false;
	// Version and help print and exit; they touch no repository state.
	if (sub === "--version" || sub === "version" || sub === "--help" || sub === "help") {
		return true;
	}
	// Bare `git stash` pushes, which mutates; only list and show read.
	if (sub === "stash") return words[2] === "list" || words[2] === "show";
	if (sub === "branch") {
		const rest = words.slice(2);
		if (rest.length === 0) return true;
		if (!rest.some((word) => GIT_LIST_FLAGS.has(word))) return false;
		return rest.every((word) => GIT_LIST_FLAGS.has(word) || !word.startsWith("-"));
	}
	if (sub === "remote") {
		const third = words[2];
		return third === undefined || ["-v", "-vv", "show", "get-url"].includes(third);
	}
	if (sub === "tag") {
		const rest = words.slice(2);
		if (rest.length === 0) return true;
		const isList = (word: string): boolean =>
			word === "-l" || word === "--list" || word === "-n" || /^-n\d+$/.test(word);
		if (!rest.some(isList)) return false;
		return rest.every((word) => isList(word) || !word.startsWith("-"));
	}
	if (sub === "worktree") return words[2] === "list";
	return READONLY_GIT.has(sub);
}

function segmentIsReadOnly(segment: string): boolean {
	const words = segment.trim().split(/\s+/).filter(Boolean);
	if (words.length === 0) return true;
	const cmd = words[0] ?? "";
	// cd only moves this shell's own directory, and every segment of the
	// chain is judged separately here (as pps does for tool bash), so
	// allowing cd cannot smuggle `cd x && rm y` past the rm segment.
	if (cmd === "cd") return true;
	if (hasDeniedFlag(cmd, words)) return false;
	if (cmd === "date") return dateIsReadOnly(words);
	if (cmd === "git") return gitIsReadOnly(words);
	return READONLY_COMMANDS.has(cmd);
}

function commandIsReadOnly(command: string): boolean {
	// Any unparseable shape fails closed.
	if (/[<>]|\$\(|`|\btee\b/.test(command)) return false;
	// A single `&` backgrounds a unit the splitter below does not judge; `&&`
	// is a separator it does split on.
	if (/(^|[^&])&([^&]|$)/.test(command)) return false;
	return command
		.split(/\n|;|&&|\|\||\|/)
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
		join(cwd, ".pi", "plans"),
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

const ACTIVE_AGENT_TAG_RE = /<active_agent\s+name=["'][^"']+["']/i;

type Resolution = {
	mode: Mode;
	authority: "own" | "default";
};

function resolveMode(ctx: ExtensionContext): Resolution {
	const own = newestEntry(ctx, ACTIVE_AGENT_ENTRY);
	const ownName = own.index >= 0 ? normalizeName(own.data?.name) : undefined;
	if (own.index >= 0) {
		// An explicit clear ({name: null}) falls back to the build default.
		return { mode: ownName ?? "build", authority: "own" };
	}
	return { mode: "build", authority: "default" };
}

function updateStatus(ctx: ExtensionContext, resolution: Resolution): void {
	ctx.ui?.setStatus?.(
		STATUS_KEY,
		`mode: ${resolution.mode} · ${MODE_SUMMARY[resolution.mode]}`,
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
	// (own entry, default) selected the mode:
	//   - ask: write/edit and the subagent trio are blocked.
	//   - plan: write/edit only under ~/.pi/plans or <cwd>/.pi/plans; subagent
	//     only for the read-only `Explore` profile.
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
				reason: `[pi-workflow-modes] Plan mode may only write plan documents under ~/.pi/plans/ or <cwd>/.pi/plans/ (attempted: ${path}). Switch to /build to edit project files.`,
			};
		}

		if (SCOUT_ONLY_SUBAGENT_TOOLS.has(event.toolName)) {
			const target = (event.input as { subagent_type?: unknown } | undefined)?.subagent_type;
			if (target === "Explore") return undefined;
			return {
				block: true,
				reason: `[pi-workflow-modes] Plan mode may only dispatch the read-only 'Explore' subagent (requested: ${typeof target === "string" && target.length > 0 ? target : "none"}). Switch to /build for other agents.`,
			};
		}

		if (SUBAGENT_TOOLS.has(event.toolName)) return undefined; // steer/result of an Explore
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
