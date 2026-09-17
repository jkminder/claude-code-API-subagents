#!/usr/bin/env python3
"""setup-worker's hooks merge (2026-09-17): the user's hooks from
~/.claude/settings.json are mirrored into the worker identity, and hook groups
only the worker file carries (a fleet's API-only gates) survive a rerun; a hook
the user removed from the user file leaves the worker file too, tracked in
<config dir>/run/mirrored-hooks.json. Hermetic: a throwaway HOME and config
dir, no key, no claude on PATH needed (setup-worker only warns).
Run: python3 bin/test_setup_worker_hooks.py
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SETUP = os.path.join(HERE, "setup-worker")
TMP = tempfile.mkdtemp(prefix="setup-worker-hooks-test-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
HOME = os.path.join(TMP, "home")
CFG = os.path.join(HOME, ".claude-api")
USER = os.path.join(HOME, ".claude", "settings.json")
WORKER = os.path.join(CFG, "settings.json")
RECORD = os.path.join(CFG, "run", "mirrored-hooks.json")


def group(cmd, matcher="Bash"):
    return {"matcher": matcher, "hooks": [{"type": "command", "command": cmd}]}


USER_GATE = group("$HOME/.local/bin/user-gate")
WORKER_GATE = group("$HOME/repositories/x/sbatch-gate")          # only the worker file carries it
WORKER_PIN = group("$HOME/repositories/x/pin-session-name", "")  # a SessionStart group only the worker has


def write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)


def read(path):
    with open(path) as f:
        return json.load(f)


def run():
    env = dict(os.environ, HOME=HOME, CLAUDE_API_CONFIG_DIR=CFG)
    env.pop("CLAUDE_API_KEY_CMD", None)
    r = subprocess.run([SETUP], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    return r.stdout


def commands(cfg, event):
    return [h["command"] for g in cfg.get("hooks", {}).get(event, []) for h in g.get("hooks", [])]


def test_worker_only_groups_survive_and_user_hooks_are_mirrored():
    shutil.rmtree(HOME, ignore_errors=True)
    write(USER, {"hooks": {"PreToolUse": [USER_GATE]}})
    write(WORKER, {"apiKeyHelper": "printf sk-dummy-test",
                   "hooks": {"PreToolUse": [WORKER_GATE], "SessionStart": [WORKER_PIN]}})
    out = run()
    cfg = read(WORKER)
    pre = commands(cfg, "PreToolUse")
    assert pre[0] == USER_GATE["hooks"][0]["command"], ("the user's hooks come first", pre)
    assert WORKER_GATE["hooks"][0]["command"] in pre, ("the worker-only gate survived", pre)
    assert any("permission-mode-hook" in c for c in pre), ("the registration step still adds its hook", pre)
    assert commands(cfg, "SessionStart") == [WORKER_PIN["hooks"][0]["command"]], cfg.get("hooks")
    assert cfg["apiKeyHelper"] == "printf sk-dummy-test", "customizations survive"
    assert "worker-only hook group(s) kept" in out and "sbatch-gate" in out and "pin-session-name" in out, out
    assert "user hooks mirrored into worker settings" in out, out
    assert read(RECORD) == {"PreToolUse": [USER_GATE]}, ("the record is the user set as mirrored", read(RECORD))


def test_rerun_is_idempotent():
    before = open(WORKER).read()
    out = run()                                   # a second run may only reorder once (user groups first)
    out = run()
    after = open(WORKER).read()
    assert "user hooks mirrored" not in out and "worker settings OK" in out, out
    assert json.loads(after)["hooks"]["PreToolUse"][0] == USER_GATE, json.loads(after)["hooks"]
    assert set(commands(json.loads(after), "PreToolUse")) == set(commands(json.loads(before), "PreToolUse"))
    assert commands(json.loads(after), "SessionStart") == [WORKER_PIN["hooks"][0]["command"]]


def test_a_hook_the_user_removed_leaves_the_worker_file_too():
    user = read(USER)
    user["hooks"]["PreToolUse"] = [g for g in user["hooks"]["PreToolUse"] if g != USER_GATE]
    write(USER, user)
    out = run()
    cfg = read(WORKER)
    pre = commands(cfg, "PreToolUse")
    assert USER_GATE["hooks"][0]["command"] not in pre, ("a previously mirrored group is not worker-only", pre)
    assert WORKER_GATE["hooks"][0]["command"] in pre, ("the hand-added gate stays", pre)
    assert any("permission-mode-hook" in c for c in pre), pre
    assert commands(cfg, "SessionStart") == [WORKER_PIN["hooks"][0]["command"]], cfg.get("hooks")
    assert "user hooks mirrored into worker settings" in out, out
    assert USER_GATE not in read(RECORD).get("PreToolUse", []), read(RECORD)


def test_without_a_record_every_worker_only_group_is_kept():
    """The first run after this change on an install whose worker file already
    carries mirrored groups: nothing is dropped (a stale mirrored group survives
    once and is named), because no record says which groups the mirror wrote."""
    os.remove(RECORD)
    stale = group("$HOME/.local/bin/removed-long-ago")
    cfg = read(WORKER)
    cfg["hooks"]["PreToolUse"].append(stale)
    write(WORKER, cfg)
    out = run()
    pre = commands(read(WORKER), "PreToolUse")
    assert stale["hooks"][0]["command"] in pre and WORKER_GATE["hooks"][0]["command"] in pre, pre
    assert "removed-long-ago" in out and "worker-only hook group(s) kept" in out, out
    assert os.path.exists(RECORD)


def test_malformed_worker_hooks_are_replaced_not_crashed():
    cfg = read(WORKER)
    cfg["hooks"] = {"PreToolUse": "not a list", "Stop": [{"matcher": "", "hooks": []}, "junk"]}
    write(WORKER, cfg)
    run()
    hooks = read(WORKER)["hooks"]
    assert "Stop" not in hooks, ("empty and non-dict groups are dropped", hooks)
    assert isinstance(hooks["PreToolUse"], list) and any("permission-mode-hook" in c for c in commands(read(WORKER), "PreToolUse")), hooks


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    order = [test_worker_only_groups_survive_and_user_hooks_are_mirrored, test_rerun_is_idempotent,
             test_a_hook_the_user_removed_leaves_the_worker_file_too,
             test_without_a_record_every_worker_only_group_is_kept, test_malformed_worker_hooks_are_replaced_not_crashed]
    assert sorted(t.__name__ for t in tests) == sorted(t.__name__ for t in order), "runner misses a test"
    for t in order:
        t()
        print("ok", t.__name__)
    print(f"{len(order)} tests passed")
