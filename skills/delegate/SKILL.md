---
name: delegate
description: Delegate work to API-billed Claude Code workers or swarms. Worker tokens are effectively free (flat API credit pool) — use them liberally and in parallel for anything nontrivial: refactors, migrations, test-fix loops, bulk research/codegen, verification passes, swarms. Trigger on "delegate", "worker", "swarm", "spawn workers", "run this on API credits". The main session keeps its subscription auth (Remote Control intact); workers run as separate claude -p processes.
---

# Delegate to API-billed workers

`claude-api` (on PATH — installed by this repo's `bin/setup-worker`) runs `claude` with a dedicated API key (Keychain or `~/.claude-api/api-key`) and an isolated `CLAUDE_CONFIG_DIR=~/.claude-api`. Worker tokens bill a flat API credit pool and are **effectively free — do not economize on them**. Prefer delegating over doing heavy work in this session, fan out in parallel by default, and treat latency plus coordination overhead as the only real costs.

**Never export `ANTHROPIC_API_KEY` in this main session** — it would flip the session's billing and break Remote Control.

**Portability:** this skill plus the repo README are the complete operating manual — assume no other local state, memory, or prior conversation. If `claude-api` is not on PATH, resolve it through this skill's own symlink: `"$(readlink -f ~/.claude/skills/delegate)/../../bin/claude-api"`. If `jq` is missing, parse worker JSON with `python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));print(d["result"],d["session_id"])' <file>`. If `claude-api` reports **no API key found**, stop and ask the user to run `claude-api-store-key` — it prompts interactively for the secret; you cannot do that step for them.

## When to delegate

**Default to yes for anything nontrivial.** Workers are free, so the calculus is latency and coordination, not tokens: delegate multi-file work, long build/test/fix loops, bulk research or generation, independent verification passes, exploratory spikes — and fan out in parallel whenever subtasks are independent. If the task is too big or too vague to split up front, delegate the splitting as well (see *Delegate the decomposition too*). Keep in the main session only: quick single-file edits, tasks needing the user's input mid-flight, and work so context-coupled that briefing a worker costs more than doing it. The built-in Task tool remains for fast in-context fan-out — it bills the subscription, so prefer workers when either would do and the job is sizable.

## Spawning workers

**Always spawn via background Bash** (`run_in_background`) so this session stays free — you'll be notified when the command completes. Run **from the target repo directory** (cwd defines the worker's project and its sandbox-writable workspace). For non-repo work (research, generation), create and `cd` into a scratch directory — never spawn from `$HOME`, which would make the whole home dir writable under `acceptEdits`.

```bash
cd <target-repo> && claude-api -p "<self-contained task prompt>" \
  --output-format json > /tmp/worker-<slug>.json 2> /tmp/worker-<slug>.err
```

- Pick a **unique slug** (task name + a short timestamp/random suffix) — `/tmp/worker-*` is shared across sessions.
- Prompt must be self-contained: goal, constraints, a verification step ("run the tests and include the output"), and what to report.
- **Commit policy:** tell workers to leave changes uncommitted (or commit only on their own worktree branch, below) — integration and committing is this session's job. Nothing else stops parallel workers from committing over each other.
- Model: defaults to fable (worker settings); `--model sonnet` for lighter work, `--model opus` when fable is overkill but the task still needs strong reasoning.
- Concurrency: **spawn as many workers as the work decomposes into** — there is no fixed cap, and tokens are not the constraint. One worker per independent subtask (per file, per test target, per research question) is the right default; dozens in parallel is fine and usually the point. The only real limits are machine resources (if the box gets sluggish or you exhaust file handles, stagger the next batch) and API rate limits (a 429 in a worker's `.err` means back off and retry that worker, not that you over-delegated). For very wide work, prefer fewer workers that each fan out internally (see below) over hundreds of processes.

### Let workers decompose further

When breaking the task down is itself part of the work — a vague brief, an unfamiliar codebase, a scope you'd have to explore before you could split it sensibly — don't do that here. Hand the chunk over and let the worker work out the split. Exploration, planning, and execution then all run on API credits, and this session's context stays clean.

**Whether to split again is the receiving agent's call** — it has seen its chunk, you haven't. Tell it it may fan out and leave the judgment to it: most chunks just get done, a big one gets split, a genuinely large one gets split and its pieces split again. Depth follows the work rather than a plan. If you already know the structure — one job per package, one per failing test — handing down a pre-split is fine too; just don't invent a hierarchy you'd have to go exploring to be sure of.

Below the top level the mechanism is built-in delegation: **subagents** for a straight fan-out, an **agent team** when that level needs to delegate further, since teammates are full sessions that can split again while subagents are leaves.

Deep trees make failures hard to attribute, so ask each level to report upward naming any sub-unit that failed and why — a leaf failure should surface as a specific gap, not "the worker said it didn't finish."

> ⚠️ **Workers must fan out with their built-in subagents (the Agent/Task tool), never with `claude-api`.** The `delegate` skill and the `claude-api` wrapper are **main-session-only tools** — their entire purpose is crossing the subscription→API billing boundary, and a worker is already on the other side. Inside a worker, plain subagents are strictly better: same API billing, no session-startup cost, no ledger/FIFO plumbing, natively orchestrated, and they inherit the worker's permission mode automatically. (Workers also don't get this skill — it lives in `~/.claude/skills`, outside the worker's `CLAUDE_CONFIG_DIR` — so the only way one calls `claude-api` is if you tell it to. Don't.)

Make the mandate explicit in the worker's prompt:

> "Scope this yourself first, then split it into independent subtasks and run them **in parallel using your built-in subagents (the Agent tool), sending them in a single message so they run concurrently**. If a subtask is still too big to do in one go, have that layer split it the same way — assemble an agent team for it, since teammates can delegate further, and give each teammate this same instruction. Do not spawn `claude-api` or nested Claude Code processes at any level. Report a consolidated summary naming any sub-unit that failed and why."

- Pass the mandate down verbatim — every level needs to know it may split further and how, or the recursion stops at the first layer.
- Agent teams are enabled in the worker settings (see Swarms below), so any worker or teammate can lead one without extra setup.

### Parallel workers on the same repo → worktrees

If more than one worker will modify the same repo (or the tree is dirty), isolate each in its own worktree — **created by this session before spawning** (workers can't: `git worktree add` writes outside their sandbox):

```bash
WT=$(claude-api worktree add <slug>)   # prints the worktree path; branch worker/<slug>
cd "$WT" && claude-api -p "..." ...
```

After collecting and merging results: `claude-api worktree clean` removes merged worktrees and branches (`claude-api worktree list` to inspect).

## Collecting results

You'll be notified when the background spawn exits. **Check for failure before trusting the output** — any of these means the run failed: nonzero exit code of the background command, empty or unparseable `/tmp/worker-<slug>.json`, or `.is_error == true` / `.subtype != "success"` in it. On failure, read `/tmp/worker-<slug>.err`, then respin with a sharper prompt or resume (below) — respinning is cheap, don't hesitate.

On success, summarize `.result` for the user. **`.session_id` is the resume handle** (for stream-json workers it's in the initial `system`/`init` line of the `.ndjson`). Best-effort log (skip if `jq` is absent):

```bash
jq -c '{ts: now|todate, task: "<slug>", cost: .total_cost_usd, session: .session_id}' \
  /tmp/worker-<slug>.json >> ~/.claude-api/cost-log.jsonl 2>/dev/null || true
```

## Permissions

Headless workers never see permission prompts — an unauthorized tool call is simply denied, and the worker must route around it or report the gap. The wrapper resolves the worker's mode automatically (first match wins):

1. An explicit `--permission-mode …` / `--dangerously-skip-permissions` you pass at spawn.
2. **Inherited from this session when it runs elevated** (`bypassPermissions`, `dontAsk`, `auto`): a PreToolUse hook records the session's mode before every Bash call, so workers mirror the user's current session-level choice, including mid-session toggles. The user running this session elevated *is* the opt-in — don't ask again before spawning.
3. Floor default: `acceptEdits` — auto-approves file edits **and workspace-confined sandboxed bash** (test/build/lint loops generally work out of the box). Blocked on the floor: writes outside the workspace, network access (`curl`, `pip/npm install`), `git push`, and other unsandboxable commands.

For blocked categories, grant per spawn: `--allowedTools "Bash(npm install *),Bash(git push *),Bash(curl *)"` — match what the task actually needs (especially the verification step you asked for). The target repo's own `.claude/settings.json` / `settings.local.json` permission rules also apply to workers. If a worker reports it was blocked, respin with the specific missing grant; escalate to `bypassPermissions` yourself only when the user explicitly OKs it.

## Watching a long worker (no steering)

For jobs you want to *watch* but not steer, spawn with streaming output — no FIFO needed:

```bash
cd <target-repo> && claude-api -p "<task>" --output-format stream-json --verbose \
  > /tmp/worker-<slug>.ndjson 2> /tmp/worker-<slug>.err
```

Tail the `.ndjson` for progress; the final `result` line carries `.result` and `.session_id`.

## Talk to a running worker (mid-run steering)

For long jobs you expect to steer, start the worker reading a FIFO:

```bash
rm -f /tmp/worker-<slug>.in && mkfifo /tmp/worker-<slug>.in
tail -f /dev/null > /tmp/worker-<slug>.in & echo $! > /tmp/worker-<slug>.keeper   # holds the pipe open
cd <target-repo> && claude-api -p --input-format stream-json --output-format stream-json --verbose \
  < /tmp/worker-<slug>.in > /tmp/worker-<slug>.ndjson 2> /tmp/worker-<slug>.err &
printf '%s\n' '{"type":"user","message":{"role":"user","content":"<initial task>"}}' > /tmp/worker-<slug>.in
```

- **This worker is shell-backgrounded, not harness-tracked — no completion notification will arrive.** Poll by tailing the `.ndjson`; a `"type":"result"` line means the session ended.
- Send further messages with another `printf '{"type":"user",...}' > /tmp/worker-<slug>.in` — but **check the worker is still alive first** (`kill -0 $(pgrep -f "worker-<slug>")` or check for a `result` line): writing to a FIFO with no reader blocks forever. Safer: wrap writes in `perl -e 'alarm shift; exec @ARGV' 10 sh -c 'printf ... > fifo'`.
- Match replies on `"type":"assistant"` lines (plain grep also hits the echoed user events). To block until a reply, **poll — do not use `tail -f … | grep -q`**, which hangs when the match is the last line ever written: `i=0; while [ $i -lt 120 ]; do grep -q -E '"type":"assistant".*<marker>' <ndjson> && break; sleep 1; i=$((i+1)); done`.
- End the session with `kill "$(cat /tmp/worker-<slug>.keeper)"`, wait for the final `result` event, then **clean up**: `rm -f /tmp/worker-<slug>.in /tmp/worker-<slug>.keeper`.

## Follow-ups after completion

Workers stay resumable — steer turn-by-turn without a FIFO:

```bash
cd <target-repo> && claude-api --resume <session_id> -p "<follow-up>" --output-format json
```

## Swarms (agent teams — the whole swarm on API credits)

The worker identity has `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in its settings, so any worker can lead a swarm. Teammates are separate processes spawned by the lead and inherit its environment → **lead, all teammates, and their subagents bill the API key** — swarms are free too, so reach for them when work is genuinely parallel. Within the swarm, lead↔teammate communication is native (shared task list + mailbox). Size the team to the work, not to a process budget.

```bash
cd <target-repo> && claude-api -p "Assemble an agent team of <N> teammates to <goal>. Split the work as: <split>. Coordinate via the shared task list; report a consolidated summary." \
  --output-format json > /tmp/swarm-<slug>.json 2> /tmp/swarm-<slug>.err
```

Give the lead an explicit team size and work split. Agent teams are experimental: if a headless swarm misbehaves, run the lead interactively instead (`tmux new -d -s swarm-<slug> 'claude-api "<swarm prompt>"'`). **The tmux lead is interactive and CAN hang on a permission prompt** — check `tmux capture-pane -t swarm-<slug> -p` for pending prompts and answer via `tmux send-keys`, or pass the same `--allowedTools` grants you would headlessly. Never run swarms through the main session — every teammate would bill the subscription.

## Housekeeping

- `claude-api ps` — every spawned worker with liveness/exit status (from the wrapper's run ledger).
- `claude-api kill <pid>|--all` — stop runaway workers.
- `claude-api clean [--all]` — sweep dead FIFO keepers and stale `/tmp/worker-*` artifacts (`--all` also ends live streaming workers).
- `claude-api doctor [--ping]` — when spawning misbehaves: checks key, config, hook, symlinks (`--ping` does one live run).
- `claude-api selftest` — after Claude Code upgrades: re-validates the behaviors this skill depends on (spends a few sonnet runs).
