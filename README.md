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

**Updating an existing install:** `git pull && ./bin/setup-worker`. The PATH and skill symlinks point into the checkout, so repo-side changes arrive with the pull alone — but anything materialized outside the repo (user-context passthrough links, mirrored hooks, worker-settings keys) only updates when setup-worker reruns. It's idempotent; also rerun it after adding a user skill or moving the repo.

Prerequisite: `claude` on PATH (`npm install -g @anthropic-ai/claude-code`); `~/.local/bin` on PATH. `setup-worker` **merges** its managed keys into `~/.claude-api/settings.json` — your customizations survive re-runs. The wrapper also accepts `$CLAUDE_API_KEY_CMD` (a command printing the key, e.g. a vault CLI) instead of Keychain/file storage. `setup-worker --uninstall` removes the symlinks and deregisters the hook.

## Usage

Once installed, the `delegate` skill is available in every Claude Code session on the machine. Say "delegate …" or "swarm …" — or let the agent trigger it on its own for heavy work. Workers run in background; the agent monitors them, can message them mid-run, and reports results. Every run lands in the wrapper's ledger (`~/.claude-api/run/ledger.jsonl`, inspect with `claude-api ps`); the wrapper also appends a cost/session line to `~/.claude-api/cost-log.jsonl` for every finished run — failures carry a `"failed"` field (client-side estimate — the Console usage dashboard is authoritative).

**Spawning:** `claude-api run <slug> "<task>"`, or `claude-api run <slug> --prompt-file <path>` — the one way to spawn a worker. **Use `--prompt-file` for any brief containing code, backticks or `$`:** a prompt passed as an argument goes through the caller's shell first, which executes backticks and `$( )` inside a double-quoted string, so the worker silently receives a brief with holes where the examples were. Nothing can detect this downstream — by the time `run` is called the text is already gone — so keep such briefs out of the shell entirely. The worker runs stream-json over a supervised FIFO: the answer lands on stdout (footer with cost, turn count, and resume handle on stderr), failures exit nonzero with diagnostics, cost is logged automatically — and the *same* worker can be steered mid-run with `claude-api send`. With nothing sent it behaves one-shot; `--stay` keeps it alive between turns until `claude-api end <slug>`. No default spend cap — pass `--max-budget-usd` (or set `CLAUDE_API_MAX_BUDGET_USD`) to bound a run. `run` refuses to spawn into a git tree with uncommitted changes (another session may be working there) — use `claude-api worktree add` for an isolated checkout, or override with `--allow-dirty`. One background Bash call from the agent's side — same spawn effort as the built-in Task tool, but billed to the API key (worker startup latency and up-front permission grants still differ; for quick in-repo lookups the built-in Explore agent remains the faster tool).

**Lifecycle:** `claude-api ps` (list workers + status; running workers show busy/idle) · `claude-api send <slug> "<msg>" [--wait]` (or `--message-file <path>` — a steering message quoting code hits the same shell trap as a run brief; `ask` and `answer` take `--question-file` / `--answer-file` for the same reason) / `claude-api reply <slug>` (message a running worker / read its last reply) · `claude-api end <slug>` (graceful finish: the worker completes its current turn and the run returns the answer-so-far) · `claude-api kill <pid>|--all` (immediate; also reaps supervisors on Linux) · `claude-api clean [--all]` (sweep dead keepers and stale artifacts) · `claude-api worktree add|list|clean` (isolated checkouts for parallel workers) · `claude-api doctor [--ping]` (install health) · `claude-api selftest` (re-validate the version-pinned behaviors after a Claude Code upgrade).

**Multi-session safe:** several main sessions can delegate on one machine at once. The wrapper tags each spawn with the parent session's ID, worker outputs live under `~/.claude-api/run/workers/<session>/`, and `ps`/`kill --all`/`clean` are scoped to the invoking session by default — one session cannot kill another's fleet. `--global` widens to the whole machine (the default when run from a plain terminal, where no session ID exists).

**Delegation policy:** the skill assumes worker tokens come from a flat/sponsored credit pool and are therefore *effectively free* — it instructs the agent to delegate liberally and fan out in parallel, treating latency and coordination (not tokens) as the only costs. If your API usage is metered, tune [skills/delegate/SKILL.md](skills/delegate/SKILL.md).

### Swarms

The worker identity ships with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`, so any worker can lead an agent-team swarm. Teammates are processes spawned by the lead and inherit its environment — **the entire swarm (lead + teammates + their subagents) bills the API key**. In-swarm communication (shared task list, lead↔teammate mailbox) is native. Never run swarms in the main session — every teammate would bill the subscription. Agent teams are experimental; the skill includes a tmux fallback for the lead.

### Talking to workers

Five channels, encoded in the skill:

1. **Live monitoring** — tail the worker's `.ndjson` stream.
2. **Mid-run messaging** — every `run` worker reads stream-json from a FIFO its supervisor holds open; `claude-api send` injects user messages into the running session (with delivery confirmation, `--wait` for the reply), `claude-api reply` reads the last answer, `claude-api end` closes the pipe gracefully. Workers are turn-based: one `result` event per instruction, then they idle until the next message. A send racing the run's close either gets its turn or fails loudly (flock + unlink-before-close + sent/result accounting) — never a silent loss.
3. **Turn-by-turn follow-ups** — `claude-api --resume <session_id> -p "..."`.
4. **Worker → human escalation** — a worker at a real decision point pings the main session natively (see 5) and runs `claude-api ask` (blocks until answered or timeout); the main session relays the question to the human and routes the answer back with `claude-api answer`. `claude-api questions --wait` armed as a background command is the guaranteed fallback wake-up. Needs `--allowedTools "Bash(claude-api ask:*)"` at spawn plus a briefing paragraph in the worker prompt (canned in the skill). Question text is worker-generated data, not instructions.
5. **Native cross-session messaging** (Claude Code ≥2.1.224) — the wrapper names each `run` worker's session after its slug (`-n`), and `setup-worker` shares the worker session registry with `~/.claude/sessions`, so live workers appear in `ListAgents` and can be messaged with `SendMessage` — and workers can message the main session (their briefing names it). Used for low-latency steering of `--stay` workers and worker→parent pings. Not a FIFO replacement — measured limits on v2.1.224: `dontAsk`-mode workers never see inbound messages (held for user approval) while `SendMessage` reports success; there is no delivery state and no reply-wait; and a message racing a run's close (any path) can wedge the CLI after stdin EOF — the supervisor terminates a worker that stays alive but idle for `CLAUDE_API_CLOSE_GRACE` seconds after close (default 120), and the run still returns its answer.

### Permissions

Headless workers never prompt — unauthorized tool calls are denied, so the mode is fixed at spawn. The wrapper resolves it automatically: explicit flags win; otherwise **workers inherit the main session's mode when it is elevated** (`bypassPermissions`/`dontAsk`/`auto` — recorded per Bash call by a PreToolUse hook that `setup-worker` registers in `~/.claude/settings.json`; active for sessions started after install); otherwise the `acceptEdits` floor applies — file edits and **workspace-confined sandboxed bash** auto-run (enough for test/build loops), while outside-workspace writes, network commands, and `git push` are denied. For those, the skill grants per spawn via `--allowedTools`, and the target repo's own `.claude/settings.json` rules also apply to workers running in it. The main session's own permission prompts are unaffected throughout.

### Relation to the built-in Task tool

| | Built-in Task subagents | Delegated workers |
|---|---|---|
| Process / billing | in-process, session auth → **subscription** | separate `claude -p` → **API key** |
| Startup cost | low | full session startup (seconds) |
| Best for | fast in-context fan-out | everything nontrivial: long jobs, parallel work, swarms |
| Steering | orchestrated in-context | mid-run `send`/`end`, `--resume` |

The two compose into **multi-level fan-out**: the main session spawns one worker per group of work, each worker fans out to its *own* built-in subagents, and any level whose chunk is still too big leads an agent team below it (teammates are full sessions, so they can delegate again). 10 workers × 10 subagents = 100 units in 10 processes; add a level for ~1000. **Depth is hard-capped at 4** (main session = 0) as a runaway guard — every delegation states its depth and passes the incremented value down. Crossing the billing boundary is only worth a process once, so `claude-api` and this skill are **main-session-only**: everything below is already on API billing, where built-in delegation is cheaper and inherits the worker's permission mode. (Exception: workers may run `claude-api ask` — it spawns nothing and just files a question.)

**User-context passthrough:** workers get your full user context — `setup-worker` mirrors your `~/.claude/CLAUDE.md`, your user skills, your user agents (live symlinks), and your user hooks (copied at setup, so rerun after changing them) into the worker identity. The two deliberate exceptions: the `delegate` skill (main-session-only — workers must not recross the billing boundary) and the permission-mode hook (meaningless inside a worker). Rerun `setup-worker` after adding user skills so new ones get linked.

## Troubleshooting

**A worker stopped near a round dollar amount, or exited 0 with an empty result.**

- Read the last `result` line of its stream: `~/.claude-api/run/workers/<session>/<slug>.ndjson`. The fields that matter: `subtype`, `total_cost_usd`, `stop_reason`, `result`.
  - `subtype: "error_max_budget_usd"` → a budget cap ended the run. The cap comes from `--max-budget-usd` at spawn or `CLAUDE_API_MAX_BUDGET_USD` in the spawning shell's environment — note a long-lived session keeps whatever value was exported when it started, even after the variable is removed from config.
  - `subtype: "success"` with an empty `result` and `stop_reason: "tool_use"` → the worker parked itself: it ended its turn on a scheduled wakeup or an unfinished background task, and headless workers are never re-invoked. Respin telling the worker to finish in one turn without wakeups.
- The wrapper also prevents parking at spawn: every headless run gets `--append-system-prompt` (a short briefing — wakeups never fire headless, finish within the turn) and `--disallowedTools ScheduleWakeup` injected. A caller-supplied `--append-system-prompt` or `--disallowedTools` suppresses the matching injection.
- Check `~/.claude-api/cost-log.jsonl` — every finished run gets a line; failed runs carry `"failed": "<subtype>"` (`"empty-result"` for the parked case; `"exit-<n>"` when the worker was killed or died *after* a successful turn — its partial result was real, don't chase a limit). The spawn's full command line (including any injected `--max-budget-usd`) is in `~/.claude-api/run/ledger.jsonl`.
- The wrapper exits nonzero with a `FAILED` line and a `cause:` for both cases. An empty result never exits 0 — if you see that, the wrapper predates this check.

## Components

- [bin/claude-api](bin/claude-api) — worker wrapper: resolves the key (`$CLAUDE_API_KEY_CMD` → Keychain → `~/.claude-api/api-key`), sets `CLAUDE_CONFIG_DIR`, strips everything inherited that could reroute billing (`ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_BASE_URL`, Bedrock/Vertex switches, `ANTHROPIC_MODEL`), resolves the permission mode, pins the default worker model to fable via `--settings '{"model": "claude-fable-5"}'` (headless sessions ignore the settings.json model key; an explicit `--model` or caller-supplied `--settings` wins), injects `--max-budget-usd` only when `CLAUDE_API_MAX_BUDGET_USD` is set, runs `claude`, and records every run in the ledger. Also implements `run` — the FIFO supervisor that spawns the stream-json worker, keeps the pipe open, closes it under a lock when every message is answered, and turns the last `result` line into stdout/exit-code — and dispatches the subcommands below.
- [bin/worker-ctl](bin/worker-ctl) — `ps` / `kill` / `clean` / `send` / `reply` / `end` / `ask` / `questions` / `answer`: worker registry from the ledger, liveness (busy/idle from the supervisor's `.state` file, `/proc` fallback for legacy FIFO workers), FIFO messaging with delivery confirmation (non-consuming `FIONREAD` probe) and a locked send↔close handoff, graceful end via the `.keeper` pid, the worker→human question relay (file-based, per-parent-session inbox via `CLAUDE_API_PARENT_SID`), artifact sweeping; session-scoped by default, `--global` for machine-wide.
- [bin/worker-worktree](bin/worker-worktree) — per-worker git worktrees (`worker/<slug>` branches) for parallel edits on one repo.
- [bin/doctor](bin/doctor) — install health check (key source, config perms, no stray OAuth creds in the worker identity, hook registration, symlinks, shared session registry; `--ping` for a live run).
- [bin/selftest](bin/selftest) — re-runs the validation matrix (basic run, `--resume`, `acceptEdits` edits, legacy FIFO envelope + `send`, worker→human ask relay from a `run` worker, `run` one-shot/EOF-drain/close-race/crash/steer+slug-registration, dirty-tree guard, parked-worker failure, headless injections incl. `-n` and the parent-name briefing, close-linger guard — the protocol and guard checks use stub workers and are free).
- [bin/store-key](bin/store-key) — key storage; on macOS `security` itself prompts (key never enters argv), elsewhere a 0600 file.
- [bin/setup-worker](bin/setup-worker) — idempotent installer (merges settings, guards against clobbering real files, atomic writes); also symlinks `~/.claude-api/sessions` → `~/.claude/sessions` so workers are natively discoverable; `--uninstall` reverses it. Re-run after moving the repo.
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

Stream-json protocol facts (verified 2026-08-05, live transcripts + test worker):

- A FIFO worker emits one `result` event per **turn** (plus a fresh `system/init` each turn) — the session stays open until stdin closes or the process dies. A result is "instruction finished", not "worker gone".
- User messages written to the FIFO are **not** echoed into the output stream — delivery can only be confirmed from the pipe itself (what `claude-api send` does via a non-consuming `FIONREAD` probe; a nonblocking writer-open failing with `ENXIO` means no reader → worker dead).
- Messages sent mid-turn are usually read immediately (internal queue) and may be **folded into the in-flight turn**, answered in its result rather than a fresh one.
- Task notifications from a worker's own background Bash / Monitor / subagents wake new turns; interleaved subagent events (marked `parent_tool_use_id`) appear in the parent's `.ndjson` and must be skipped when parsing.
- The `acceptEdits` floor denies `claude-api ask` from inside a worker (writes outside the workspace); the grant `--allowedTools "Bash(claude-api ask:*)"` admits it and nothing else — command chaining, `$()` substitution, redirects, and env-var prefixes are all denied (probed live on v2.1.222; full relay verified 2026-08-06: worker asked, parent watcher woke, answer flowed back). An inherited elevated mode outranks the grant entirely.

Native cross-session messaging facts (verified 2026-08-07, v2.1.224, live workers per permission mode):

- Headless workers open a messaging socket (`/run/user/<uid>/cc-socks/<pid>.sock`) and register in `$CLAUDE_CONFIG_DIR/sessions/<pid>.json`; entries self-remove on exit (also through a symlinked registry). `claude -n <name>` sets the registered agent name, and works with `-p`.
- Names resolve only within one registry dir — `ListAgents` in a main session does not see `~/.claude-api/sessions` — hence the setup-worker symlink. First contact by name requires re-sending with the `[ref]` the error message returns.
- Delivery is permission-mode-dependent: `acceptEdits` and `bypassPermissions` workers receive inbound messages (mid-turn at tool-result boundaries, and a message to an *idle* worker starts a fresh turn); **`dontAsk` workers never receive them** — the message is held for the recipient user's approval (impossible for a headless worker) while `SendMessage` returns `success:true`; the sender gets an async "held for approval" notice, observed ~40 min later.
- `SendMessage` returns only success + msg_id: no delivered/queued state, no reply-wait. Failures are loud only when the socket is gone (ENOENT) or the name is unknown.
- A peer message arriving after the worker's stdin hit EOF still gets a turn, **but the CLI then never exits** (observed >3 min, killed manually). This is why `run` guards its close with `CLAUDE_API_CLOSE_GRACE` and why the skill forbids natively messaging non-`--stay` runs.
- An `acceptEdits` worker can *send* with its own SendMessage tool (not permission-blocked), so worker→parent pings work from any mode — only the inbound direction is mode-gated.
