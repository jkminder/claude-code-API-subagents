# claude-code-API-subagents

Run Claude Code **subagent workers billed to an Anthropic API key**, while your main interactive session stays on **claude.ai subscription auth — with Remote Control intact**.

## The problem

- Claude Code's [Remote Control](https://code.claude.com/docs/en/remote-control.md) (steering local sessions from claude.ai / the mobile app) requires subscription OAuth. The docs are explicit: *"API keys are not supported"* — and since v2.1.139 a session that merely has `ANTHROPIC_API_KEY` set errors out of Remote Control ([#59062](https://github.com/anthropics/claude-code/issues/59062)).
- The built-in Task/Agent subagents always inherit the session's credentials — there is no per-agent auth or billing override anywhere (frontmatter, settings, or SDK).

So out of the box you can't steer sessions from your phone *and* bill the heavy lifting to an API org. This repo adds that missing split.

## The trick

Auth is resolved per **process**: in Claude Code's [credential precedence](https://code.claude.com/docs/en/authentication.md), `ANTHROPIC_API_KEY` outranks subscription OAuth, and `CLAUDE_CONFIG_DIR` gives a process a fully isolated identity. The main session therefore spawns workers (`claude -p`) whose environment carries the key — the main session is untouched (the desktop app ignores `ANTHROPIC_API_KEY` entirely), and every worker token bills the API org.

```
Phone / claude.ai ──Remote Control──▶ Main session (subscription OAuth: planning/steering)
                                          │ spawns (env: ANTHROPIC_API_KEY, CLAUDE_CONFIG_DIR=~/.claude-api)
                                          ▼
                          claude -p workers · streaming workers · agent-team swarms
                                          → all billed to the API key
```

## Install (any machine — laptop or cluster)

```bash
git clone https://github.com/jkminder/claude-code-API-subagents.git
claude-code-API-subagents/bin/setup-worker    # worker config, PATH links, delegate skill (idempotent)
claude-code-API-subagents/bin/store-key       # prompts for the API key: Keychain on macOS, 0600 file on Linux
claude-api -p 'Reply with exactly: WORKER OK' --model sonnet   # verify → appears on Console usage
claude-api doctor                                              # health-check the install
```

Prerequisite: `claude` on PATH (`npm install -g @anthropic-ai/claude-code`); `~/.local/bin` on PATH. `setup-worker` **merges** its managed keys into `~/.claude-api/settings.json` — your customizations survive re-runs. The wrapper also accepts `$CLAUDE_API_KEY_CMD` (a command printing the key, e.g. a vault CLI) instead of Keychain/file storage. `setup-worker --uninstall` removes the symlinks and deregisters the hook.

## Usage

Once installed, the `delegate` skill is available in every Claude Code session on the machine. Say "delegate …" or "swarm …" — or let the agent trigger it on its own for heavy work. Workers run in background; the agent monitors them, can message them mid-run, and reports results. Every run lands in the wrapper's ledger (`~/.claude-api/run/ledger.jsonl`, inspect with `claude-api ps`); the agent additionally appends a best-effort cost/session line to `~/.claude-api/cost-log.jsonl` (client-side estimate — the Console usage dashboard is authoritative).

**Lifecycle:** `claude-api ps` (list workers + status) · `claude-api kill <pid>|--all` · `claude-api clean [--all]` (sweep FIFO keepers and stale artifacts) · `claude-api worktree add|list|clean` (isolated checkouts for parallel workers) · `claude-api doctor [--ping]` (install health) · `claude-api selftest` (re-validate the version-pinned behaviors after a Claude Code upgrade).

**Multi-session safe:** several main sessions can delegate on one machine at once. The wrapper tags each spawn with the parent session's ID, worker outputs live under `~/.claude-api/run/workers/<session>/`, and `ps`/`kill --all`/`clean` are scoped to the invoking session by default — one session cannot kill another's fleet. `--global` widens to the whole machine (the default when run from a plain terminal, where no session ID exists).

**Delegation policy:** the skill assumes worker tokens come from a flat/sponsored credit pool and are therefore *effectively free* — it instructs the agent to delegate liberally and fan out in parallel, treating latency and coordination (not tokens) as the only costs. If your API usage is metered, tune [skills/delegate/SKILL.md](skills/delegate/SKILL.md).

### Swarms

The worker identity ships with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, so any worker can lead an agent-team swarm. Teammates are processes spawned by the lead and inherit its environment — **the entire swarm (lead + teammates + their subagents) bills the API key**. In-swarm communication (shared task list, lead↔teammate mailbox) is native. Never run swarms in the main session — every teammate would bill the subscription. Agent teams are experimental; the skill includes a tmux fallback for the lead.

### Talking to workers

Three channels, encoded in the skill:

1. **Live monitoring** — tail the worker's `stream-json` output.
2. **Mid-run messaging** — start the worker with `--input-format stream-json` reading a FIFO; the main agent injects user messages into the running session at any time and closes the pipe to end it.
3. **Turn-by-turn follow-ups** — `claude-api --resume <session_id> -p "..."`.

### Permissions

Headless workers never prompt — unauthorized tool calls are denied, so the mode is fixed at spawn. The wrapper resolves it automatically: explicit flags win; otherwise **workers inherit the main session's mode when it is elevated** (`bypassPermissions`/`dontAsk`/`auto` — recorded per Bash call by a PreToolUse hook that `setup-worker` registers in `~/.claude/settings.json`; active for sessions started after install); otherwise the `acceptEdits` floor applies — file edits and **workspace-confined sandboxed bash** auto-run (enough for test/build loops), while outside-workspace writes, network commands, and `git push` are denied. For those, the skill grants per spawn via `--allowedTools`, and the target repo's own `.claude/settings.json` rules also apply to workers running in it. The main session's own permission prompts are unaffected throughout.

### Relation to the built-in Task tool

| | Built-in Task subagents | Delegated workers |
|---|---|---|
| Process / billing | in-process, session auth → **subscription** | separate `claude -p` → **API key** |
| Startup cost | low | full session startup (seconds) |
| Best for | fast in-context fan-out | everything nontrivial: long jobs, parallel work, swarms |
| Steering | orchestrated in-context | FIFO mid-run messages, `--resume` |

The two compose into **multi-level fan-out**: the main session spawns one worker per group of work, each worker fans out to its *own* built-in subagents, and any level whose chunk is still too big leads an agent team below it (teammates are full sessions, so they can delegate again). 10 workers × 10 subagents = 100 units in 10 processes; add a level for ~1000. Crossing the billing boundary is only worth a process once, so `claude-api` and this skill are **main-session-only**: everything below is already on API billing, where built-in delegation is cheaper and inherits the worker's permission mode. (Structurally reinforced — the skill lives in `~/.claude/skills`, outside the worker's `CLAUDE_CONFIG_DIR`, so workers never see it.)

## Components

- [bin/claude-api](bin/claude-api) — worker wrapper: resolves the key (`$CLAUDE_API_KEY_CMD` → Keychain → `~/.claude-api/api-key`), sets `CLAUDE_CONFIG_DIR`, strips everything inherited that could reroute billing (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, Bedrock/Vertex switches, `ANTHROPIC_MODEL`), resolves the permission mode, runs `claude`, and records every run in the ledger. Also the dispatcher for the subcommands below.
- [bin/worker-ctl](bin/worker-ctl) — `ps` / `kill` / `clean`: worker registry from the ledger, liveness, artifact sweeping; session-scoped by default, `--global` for machine-wide.
- [bin/worker-worktree](bin/worker-worktree) — per-worker git worktrees (`worker/<slug>` branches) for parallel edits on one repo.
- [bin/doctor](bin/doctor) — install health check (key source, config perms, no stray OAuth creds in the worker identity, hook registration, symlinks; `--ping` for a live run).
- [bin/selftest](bin/selftest) — re-runs the validation matrix (basic run, `--resume`, `acceptEdits` edits, FIFO envelope).
- [bin/store-key](bin/store-key) — key storage; on macOS `security` itself prompts (key never enters argv), elsewhere a 0600 file.
- [bin/setup-worker](bin/setup-worker) — idempotent installer (merges settings, guards against clobbering real files, atomic writes); `--uninstall` reverses it. Re-run after moving the repo.
- [bin/permission-mode-hook](bin/permission-mode-hook) — PreToolUse hook recording the session's permission mode to a private 0700 dir (`~/.claude-api/run/`, atomic 0600 writes, stale files pruned) so workers can inherit elevated modes.
- [skills/delegate/SKILL.md](skills/delegate/SKILL.md) — the delegation playbook (spawn, collect, steer, swarm, housekeeping).

**Design principle:** this repo is the single source of truth. The skill plus this README must contain everything an agent needs on a *fresh* machine — no reliance on local memory, prior sessions, or machine state beyond what `setup-worker` creates. Keep it that way when extending.

## Facts this relies on (verified 2026-08-04, Claude Code v2.1.220)

- Credential precedence: cloud creds → `ANTHROPIC_AUTH_TOKEN` → `ANTHROPIC_API_KEY` → `apiKeyHelper` → `CLAUDE_CODE_OAUTH_TOKEN` → subscription OAuth ([authentication.md](https://code.claude.com/docs/en/authentication.md)).
- Remote Control is subscription-only; an API key in the session env disables it ([remote-control.md](https://code.claude.com/docs/en/remote-control.md), [#59062](https://github.com/anthropics/claude-code/issues/59062)).
- In-process subagents have no auth override; costs roll into the parent session ([sub-agents docs](https://code.claude.com/docs/en/sub-agents.md)).
- `CLAUDE_CONFIG_DIR` relocates settings + credentials + sessions wholesale ([settings docs](https://code.claude.com/docs/en/settings.md)); nested `claude` spawning is unguarded (`CLAUDECODE=1` is a marker, not a block).
- Headless output formats and flags: [headless.md](https://code.claude.com/docs/en/headless.md) · costs/limits: [costs.md](https://code.claude.com/docs/en/costs.md).

- `CLAUDE_CODE_SESSION_ID` is exported to Bash tool subprocesses and matches the `session_id` in hook payloads — the link the permission-mode inheritance rides on.
- PreToolUse hooks fire **before** permission evaluation, so the recorded mode is fresh even when the triggering call is denied.

End-to-end validated: basic runs, `--resume`, `acceptEdits` file edits, FIFO mid-run steering (message envelope `{"type":"user","message":{"role":"user","content":"..."}}`), hook firing + payload fields, and permission-mode inheritance. Re-validate after Claude Code upgrades with `claude-api selftest`.
