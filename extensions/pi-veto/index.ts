/**
 * pi-veto
 *
 * The deny-only security floor. It runs *below* policy: pi-permission-system
 * and every agent file can ask, allow, or deny whatever they like, but these
 * operations never run - not from a tool call, not from `!cmd` user bash, not
 * from a frontmatter that tries to allow them.
 *
 * Design contract:
 *   - DENY ONLY. There is no ask path and no allow path. An ask-capable floor
 *     would be a second, mode-blind prompter (the guardrails double-prompt
 *     bug); a allow path would make the floor liftable.
 *   - Agent-immune. The checks live in this extension's hooks, not in agent
 *     frontmatter, so no `permission:` block can reach them.
 *   - Additive user rules only. ~/.pi/agent/floor.json may add more DENIES
 *     (`deny.bash`, `deny.paths`); anything else in it is ignored on purpose.
 *   - No dialogs. A blocked call returns a canned reason; `!cmd` gets exit
 *     code 126 and never executes.
 *
 * Built-in floor:
 *   disk      mkfs*, fdisk, parted, wipefs, mount, umount
 *   devices   dd of=/dev/*, shred /dev/*, rm -rf /dev/*
 *   wipe      rm -rf / and the system roots (~, /home, /etc, /usr, ...)
 *   bombs     :(){ :|:& };:
 *   power     reboot, shutdown, poweroff, halt
 *   secrets   writes to ~/.ssh, ~/.gnupg, ~/.aws, ~/.azure, ~/.config/gcloud,
 *             ~/.netrc, ~/.npmrc, ~/.pi/agent, /etc/sudoers, /etc/shadow
 */

import { existsSync, readFileSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve, sep } from "node:path";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const DENY_PREFIX = "[pi-veto] Denied";

/** Commands that are catastrophic on their own, matched by basename. */
const HARD_COMMANDS: ReadonlyArray<{ re: RegExp; reason: string }> = [
	{ re: /^mkfs(\..+)?$/, reason: "filesystem creation is never allowed" },
	{ re: /^fdisk$/, reason: "partition-table editing is never allowed" },
	{ re: /^parted$/, reason: "partition editing is never allowed" },
	{ re: /^wipefs$/, reason: "filesystem-signature wiping is never allowed" },
	{ re: /^mount$/, reason: "mounting is never allowed for the agent" },
	{ re: /^umount$/, reason: "unmounting is never allowed for the agent" },
	{ re: /^reboot$/, reason: "the agent cannot reboot the machine" },
	{ re: /^shutdown$/, reason: "the agent cannot shut the machine down" },
	{ re: /^poweroff$/, reason: "the agent cannot power the machine off" },
	{ re: /^halt$/, reason: "the agent cannot halt the machine" },
];

/** Absolute roots whose recursive deletion destroys the machine or a data disk. */
const DANGEROUS_ROOTS = new Set([
	"/", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/lib32",
	"/lib64", "/opt", "/proc", "/root", "/run", "/sbin", "/srv", "/sys",
	"/usr", "/var",
]);

/** Wrappers whose real command is further right in the token list. */
const WRAPPERS = new Set([
	"sudo", "doas", "pkexec", "command", "exec", "env", "nohup", "nice",
	"ionice", "time", "stdbuf", "watch", "xargs",
]);

/** Flags of a wrapper that consume the following token. */
const VALUE_FLAGS: Record<string, ReadonlySet<string>> = {
	sudo: new Set(["-u", "-g", "-h", "-p", "-C", "-T", "-U", "-r", "-t"]),
	doas: new Set(["-u", "-C"]),
	pkexec: new Set(["--user"]),
	env: new Set(["-u", "-C", "-S"]),
	nice: new Set(["-n"]),
	ionice: new Set(["-c", "-n", "-p"]),
	stdbuf: new Set(["-i", "-o", "-e"]),
	xargs: new Set(["-n", "-P", "-I", "-d", "-E", "-L", "-s"]),
};

const SHELLS = new Set(["sh", "bash", "zsh", "dash", "ksh", "fish"]);

/** Credential and policy stores no tool may write, no matter the policy. */
const PROTECTED_WRITE_PATHS = [
	"~/.ssh/",
	"~/.gnupg/",
	"~/.aws/",
	"~/.azure/",
	"~/.config/gcloud/",
	"~/.netrc",
	"~/.npmrc",
	"~/.pi/agent/",
	"/etc/sudoers",
	"/etc/shadow",
];

const FORK_BOMB_RE = /:\s*\(\s*\)\s*\{[^}]*:\s*\|\s*:[^}]*\}\s*;\s*:/;

type DenyVerdict = { rule: string; reason: string };

function basename(token: string): string {
	return token.split("/").filter(Boolean).pop() ?? token;
}

function expandHome(value: string): string {
	if (value === "~") return homedir();
	if (value.startsWith("~/")) return join(homedir(), value.slice(2));
	if (value.startsWith("$HOME/")) return join(homedir(), value.slice(6));
	if (value.startsWith("${HOME}/")) return join(homedir(), value.slice(8));
	return value;
}

/** Split a shell command on its unquoted control operators. */
function splitSegments(command: string): string[] {
	const out: string[] = [];
	let cur = "";
	let quote: string | null = null;
	for (let i = 0; i < command.length; i += 1) {
		const ch = command[i];
		if (quote) {
			cur += ch;
			if (ch === quote) quote = null;
			continue;
		}
		if (ch === "'" || ch === '"') {
			quote = ch;
			cur += ch;
			continue;
		}
		if (ch === "\\" && i + 1 < command.length) {
			cur += ch + command[i + 1];
			i += 1;
			continue;
		}
		if (ch === "\n" || ch === ";") {
			out.push(cur);
			cur = "";
			continue;
		}
		if (ch === "&" && command[i + 1] === "&") {
			out.push(cur);
			cur = "";
			i += 1;
			continue;
		}
		if (ch === "|") {
			if (command[i + 1] === "|") i += 1;
			out.push(cur);
			cur = "";
			continue;
		}
		cur += ch;
	}
	out.push(cur);
	return out.map((segment) => segment.trim()).filter((segment) => segment.length > 0);
}

/** Quote-aware whitespace tokenizer. */
function tokenize(segment: string): string[] {
	const out: string[] = [];
	let cur = "";
	let quote: string | null = null;
	for (let i = 0; i < segment.length; i += 1) {
		const ch = segment[i];
		if (quote) {
			if (ch === quote) quote = null;
			else cur += ch;
			continue;
		}
		if (ch === "'" || ch === '"') {
			quote = ch;
			continue;
		}
		if (/\s/.test(ch)) {
			if (cur.length > 0) {
				out.push(cur);
				cur = "";
			}
			continue;
		}
		cur += ch;
	}
	if (cur.length > 0) out.push(cur);
	return out;
}

/** Contents of `$(...)` and backtick substitutions, best effort. */
function substitutions(command: string): string[] {
	const found: string[] = [];
	for (let i = 0; i < command.length; i += 1) {
		if (command[i] === "$" && command[i + 1] === "(") {
			let depth = 1;
			let j = i + 2;
			for (; j < command.length && depth > 0; j += 1) {
				if (command[j] === "(") depth += 1;
				else if (command[j] === ")") depth -= 1;
			}
			if (depth === 0) found.push(command.slice(i + 2, j - 1));
		} else if (command[i] === "`") {
			const end = command.indexOf("`", i + 1);
			if (end > i) {
				found.push(command.slice(i + 1, end));
				i = end;
			}
		}
	}
	return found;
}

function dangerousOperand(operand: string): boolean {
	const expanded = expandHome(operand).replace(/\/+$/, "") || "/";
	if (expanded === "/" || expanded === "/*") return true;
	if (expanded === homedir()) return true;
	if (DANGEROUS_ROOTS.has(expanded)) return true;
	// A data-disk mount root itself, e.g. /mnt/data-disk.
	if (/^\/(mnt|media)\/[^/]+$/.test(expanded)) return true;
	return false;
}

function checkTokens(tokens: string[]): DenyVerdict | null {
	if (tokens.length === 0) return null;
	const cmd = basename(tokens[0]);
	const args = tokens.slice(1);

	for (const entry of HARD_COMMANDS) {
		if (entry.re.test(cmd)) {
			return { rule: cmd, reason: entry.reason };
		}
	}

	if (cmd === "dd") {
		if (args.some((arg) => /^of=\/dev\//.test(arg))) {
			return { rule: "dd of=/dev/*", reason: "writing directly to a block device is never allowed" };
		}
	}

	if (cmd === "shred") {
		if (args.some((arg) => arg.startsWith("/dev/"))) {
			return { rule: "shred /dev/*", reason: "shredding a device is never allowed" };
		}
	}

	if (cmd === "rm") {
		const flags = args.filter((arg) => arg.startsWith("-"));
		const operands = args.filter((arg) => !arg.startsWith("-"));
		const recursive = flags.some((flag) => flag === "--recursive" || /^-[a-zA-Z]*[rR]/.test(flag));
		const force = flags.some((flag) => flag === "--force" || /^-[a-zA-Z]*f/.test(flag));
		if (recursive && force) {
			for (const operand of operands) {
				if (operand.startsWith("/dev/")) {
					return { rule: "rm -rf /dev/*", reason: "deleting device nodes is never allowed" };
				}
				if (dangerousOperand(operand)) {
					return { rule: `rm -rf ${operand}`, reason: "recursive deletion of a system root is never allowed" };
				}
			}
		}
	}

	return null;
}

function analyzeSegment(segment: string, depth: number): DenyVerdict | null {
	if (depth > 4) return null;
	let tokens = tokenize(segment);

	for (let guard = 0; guard < 6; guard += 1) {
		while (tokens.length > 0 && /^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[0])) {
			tokens = tokens.slice(1);
		}
		if (tokens.length === 0) return null;

		const cmd = basename(tokens[0]);
		if (SHELLS.has(cmd)) {
			const ci = tokens.indexOf("-c");
			if (ci >= 0 && ci + 1 < tokens.length) {
				const inner = tokens.slice(ci + 1).join(" ");
				const verdict = checkCommand(inner, depth + 1);
				if (verdict) return verdict;
			}
			return null;
		}
		if (!WRAPPERS.has(cmd)) break;

		const valueFlags = VALUE_FLAGS[cmd];
		const rest: string[] = [];
		for (let i = 1; i < tokens.length; i += 1) {
			const token = tokens[i];
			if (token.startsWith("-")) {
				if (valueFlags?.has(token)) i += 1;
				continue;
			}
			rest.push(token);
		}
		tokens = rest;
	}

	return checkTokens(tokens);
}

function checkCommand(command: string, depth = 0): DenyVerdict | null {
	if (FORK_BOMB_RE.test(command)) {
		return { rule: "fork bomb", reason: "fork bombs are never allowed" };
	}
	for (const segment of splitSegments(command)) {
		const verdict = analyzeSegment(segment, depth);
		if (verdict) return verdict;
	}
	for (const inner of substitutions(command)) {
		const verdict = checkCommand(inner, depth + 1);
		if (verdict) return verdict;
	}
	return null;
}

// ---------------------------------------------------------------------------
// ~/.pi/agent/floor.json - additive DENY rules only.
// ---------------------------------------------------------------------------

type FloorRule = { regex: RegExp; source: string };

type FloorState = {
	stamp: string;
	bash: FloorRule[];
	paths: string[];
	ignored: string[];
};

let floorCache: FloorState | null = null;

function floorPath(): string {
	const env = process.env.PI_CODING_AGENT_DIR;
	const dir = env && env.length > 0 ? env : join(homedir(), ".pi", "agent");
	return join(dir, "floor.json");
}

function globToRegex(pattern: string): RegExp {
	const escaped = expandHome(pattern)
		.split("*")
		.map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))
		.join(".*")
		// Mirror pps: a trailing " *" also matches the bare command.
		.replace(/ \.\*$/, "( .*)?");
	return new RegExp(`^${escaped}$`, "s");
}

function loadFloor(): FloorState {
	const path = floorPath();
	if (!existsSync(path)) {
		floorCache = { stamp: "missing", bash: [], paths: [], ignored: [] };
		return floorCache;
	}
	let stamp = "unreadable";
	try {
		const stat = statSync(path);
		stamp = `${stat.mtimeMs}:${stat.size}`;
	} catch {
		// fall through with a stable stamp so a broken file is not re-read hot
	}
	if (floorCache?.stamp === stamp) return floorCache;

	const state: FloorState = { stamp, bash: [], paths: [], ignored: [] };
	try {
		const parsed = JSON.parse(readFileSync(path, "utf8")) as unknown;
		const deny = (parsed as { deny?: unknown } | null)?.deny;
		if (deny && typeof deny === "object") {
			const bash = (deny as { bash?: unknown }).bash;
			if (Array.isArray(bash)) {
				for (const entry of bash) {
					if (typeof entry === "string" && entry.trim().length > 0) {
						state.bash.push({ regex: globToRegex(entry.trim()), source: entry.trim() });
					} else {
						state.ignored.push(`deny.bash entry is not a string: ${JSON.stringify(entry)}`);
					}
				}
			}
			const paths = (deny as { paths?: unknown }).paths;
			if (Array.isArray(paths)) {
				for (const entry of paths) {
					if (typeof entry === "string" && entry.trim().length > 0) {
						state.paths.push(expandHome(entry.trim()));
					} else {
						state.ignored.push(`deny.paths entry is not a string: ${JSON.stringify(entry)}`);
					}
				}
			}
		}
		// Anything that is not under `deny` is not part of the contract.
		for (const key of Object.keys((parsed ?? {}) as Record<string, unknown>)) {
			if (key !== "deny" && key !== "$schema" && !key.startsWith("_") && key !== "$comment") {
				state.ignored.push(`top-level "${key}" is not read: the floor is deny-only`);
			}
		}
	} catch (error) {
		state.ignored.push(`floor.json could not be parsed: ${(error as Error).message}`);
	}
	floorCache = state;
	return state;
}

function checkFloorBash(command: string): DenyVerdict | null {
	for (const rule of loadFloor().bash) {
		if (rule.regex.test(command)) {
			return { rule: rule.source, reason: "matches an additive deny rule in floor.json" };
		}
	}
	return null;
}

function pathVariants(value: string): string[] {
	const expanded = expandHome(value);
	const absolute = isAbsolute(expanded) ? expanded : resolve(process.cwd(), expanded);
	const normalized = absolute.replace(/\/+$/, "") || "/";
	return [value, expanded, absolute, normalized];
}

function underPrefix(value: string, prefix: string): boolean {
	const normalizedPrefix = prefix.replace(/\/+$/, "");
	if (normalizedPrefix.length === 0) return false;
	return value === normalizedPrefix || value.startsWith(`${normalizedPrefix}${sep}`);
}

function checkProtectedWrite(rawPath: string): DenyVerdict | null {
	const variants = pathVariants(rawPath);
	for (const entry of PROTECTED_WRITE_PATHS) {
		const protectedPath = expandHome(entry);
		for (const variant of variants) {
			if (underPrefix(variant, protectedPath)) {
				return {
					rule: `write ${entry}`,
					reason: "the agent cannot modify credential stores or its own policy files",
				};
			}
		}
	}
	for (const entry of loadFloor().paths) {
		for (const variant of variants) {
			if (underPrefix(variant, entry)) {
				return { rule: `write ${entry}`, reason: "matches an additive path deny in floor.json" };
			}
		}
	}
	return null;
}

const MUTATION_RE =
	/(^|[\s;&|])(>>?|tee|shred|dd|rm|truncate|chmod|chown|ln|touch|install|sed\s+-i)\b/;

function checkProtectedBash(command: string): DenyVerdict | null {
	if (!MUTATION_RE.test(command)) return null;
	for (const entry of PROTECTED_WRITE_PATHS) {
		const expanded = expandHome(entry);
		const literal = entry.replace(/\/+$/, "");
		const candidates = entry.endsWith("/") ? [literal, expanded] : [literal, expanded];
		if (candidates.some((candidate) => command.includes(candidate))) {
			return {
				rule: `write ${entry}`,
				reason: "the agent cannot modify credential stores or its own policy files",
			};
		}
	}
	return null;
}

function denyReason(verdict: DenyVerdict): string {
	return `${DENY_PREFIX} (${verdict.rule}): ${verdict.reason}. This is a hard floor - mode, agent policy, and approval cannot override it. Run it yourself outside the agent if you intend it.`;
}

function deniedResult(verdict: DenyVerdict) {
	return {
		result: {
			output: denyReason(verdict),
			exitCode: 126,
			cancelled: false,
			truncated: false,
		},
	};
}

export default function (pi: ExtensionAPI): void {
	pi.registerCommand("veto", {
		description: "Show the deny-only floor (built-ins and floor.json entries)",
		handler: async (_args, ctx) => {
			const floor = loadFloor();
			const lines = [
				"pi-veto floor (deny-only, agent-immune, no dialogs)",
				"built-in: mkfs/fdisk/parted/wipefs/mount/umount, dd of=/dev/*, shred /dev/*, rm -rf of system roots, fork bombs, reboot/shutdown/poweroff/halt",
				`floor.json bash denies: ${floor.bash.length ? floor.bash.map((rule) => rule.source).join(", ") : "(none)"}`,
				`floor.json path denies: ${floor.paths.length ? floor.paths.join(", ") : "(none)"}`,
			];
			if (floor.ignored.length > 0) lines.push(`ignored entries: ${floor.ignored.join("; ")}`);
			ctx.ui?.notify?.(lines.join("\n"), floor.ignored.length > 0 ? "warning" : "info");
		},
	});

	pi.on("tool_call", (event) => {
		if (event.toolName === "bash") {
			const command = (event.input as { command?: unknown } | undefined)?.command;
			if (typeof command !== "string") return undefined;
			const verdict =
				checkCommand(command) ?? checkFloorBash(command) ?? checkProtectedBash(command);
			return verdict ? deniedToolCall(verdict) : undefined;
		}
		if (event.toolName === "write" || event.toolName === "edit") {
			const input = event.input as { path?: unknown; file_path?: unknown } | undefined;
			const raw = input?.path ?? input?.file_path;
			if (typeof raw !== "string") return undefined;
			const verdict = checkProtectedWrite(raw);
			return verdict ? deniedToolCall(verdict) : undefined;
		}
		return undefined;
	});

	pi.on("user_bash", (event) => {
		const verdict =
			checkCommand(event.command) ??
			checkFloorBash(event.command) ??
			checkProtectedBash(event.command);
		return verdict ? deniedResult(verdict) : undefined;
	});
}

function deniedToolCall(verdict: DenyVerdict | null) {
	if (!verdict) return undefined;
	return { block: true, reason: denyReason(verdict) };
}
