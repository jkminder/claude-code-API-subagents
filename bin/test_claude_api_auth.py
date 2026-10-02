#!/usr/bin/env python3
"""claude-api's AUTH_MODE (fleet.conf; Julian's D159 = C, 2026-10-02): api keeps
the apiKeyHelper requirement and spawns with no token; enterprise reads the
Enterprise OAuth token from 1Password (a fake with-op here) into
CLAUDE_CODE_OAUTH_TOKEN for the worker and empties apiKeyHelper through the
injected --settings (merged into the model pin; alone beside a caller's
--model; a caller's own --settings is warned, not merged). Any other AUTH_MODE
refuses without showing the value, and is a FAIL row in doctor. The injected model is fleet.conf's
MODEL_DEFAULT (Julian's D165 = A, 2026-10-02), claude-fable-5 without one; only
the fleet's canonical id (claude-<fable|mythos|opus>-<n>[-<n>...]) passes, and
any other value, a pasted token included, refuses before claude starts and
without showing the value; a caller's --model or --settings still bypasses the
pin. An OAUTH_TOKEN_REF that is not an op:// reference (a pasted token) refuses
in claude-api and is a FAIL row in doctor, before op runs and without showing
the value. Hermetic: throwaway HOME and config dir, a fake claude on PATH, no
key, no network.
Run: python3 bin/test_claude_api_auth.py
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_API = os.path.join(HERE, "claude-api")
TOKEN_REF = "op://Fellow - Julian Minder/Claude Enterprise Token/credential"
FAKE_TOKEN = "sk-ant-oat01-FAKEFAKEFAKE"   # token-shaped, not a real token
TMP = tempfile.mkdtemp(prefix="claude-api-auth-test-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
FAKE_BIN = os.path.join(TMP, "fakebin")
os.makedirs(FAKE_BIN)
CLAUDE_REC = os.path.join(TMP, "claude-calls.log")   # the fake claude's argv, one CALL block per start
with open(os.path.join(FAKE_BIN, "claude"), "w") as f:
    f.write('#!/usr/bin/env bash\n'
            '{ echo CALL; for a in "$@"; do printf \'ARG %s\\n\' "$a"; done; } >> ' + repr(CLAUDE_REC) + '\n'
            'echo "CLAUDE_FAKE oauth_set=${CLAUDE_CODE_OAUTH_TOKEN:+1} len=${#CLAUDE_CODE_OAUTH_TOKEN}"\n'
            'for a in "$@"; do printf \'ARG %s\\n\' "$a"; done\n')
os.chmod(os.path.join(FAKE_BIN, "claude"), 0o755)
REC = os.path.join(TMP, "op-calls.log")
OP = os.path.join(TMP, "fake-with-op")
with open(OP, "w") as f:
    f.write("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> " + repr(REC) + "\n"
            "if [ -n \"${FAKE_OP_FAIL:-}\" ]; then exit 1; fi\nprintf '%s\\n' tok-abc-123\n")
os.chmod(OP, 0o755)
n = 0


def case(label, *, helper, conf_lines, args=("-p", "say hi"), env_extra=None,
         model_line="MODEL_DEFAULT=claude-fable-5-1"):
    global n
    n += 1
    home = os.path.join(TMP, "home%d" % n)
    cfg = os.path.join(home, ".claude-api")
    os.makedirs(cfg)
    settings = {"model": "claude-fable-5-1"}
    if helper:
        settings["apiKeyHelper"] = "/x/with-op op read 'op://v/i/credential'"
    with open(os.path.join(cfg, "settings.json"), "w") as f:
        json.dump(settings, f)
    conf = os.path.join(TMP, "fleet%d.conf" % n)
    with open(conf, "w") as f:
        f.write("".join(l + "\n" for l in ([model_line] if model_line else []) + list(conf_lines)))
    for rec in (REC, CLAUDE_REC):
        if os.path.exists(rec):
            os.remove(rec)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_CODE_", "CLAUDE_API_", "ANTHROPIC_", "AUTH_MODE", "OAUTH_TOKEN_REF",
                                "MODEL_DEFAULT"))}
    env.update({"HOME": home, "FLEET_CONF": conf, "CLAUDE_API_WITH_OP": OP,
                "PATH": FAKE_BIN + os.pathsep + env.get("PATH", "")})
    if env_extra:
        env.update(env_extra)
    r = subprocess.run(["bash", CLAUDE_API, "--permission-mode", "acceptEdits", *args],
                       capture_output=True, text=True, env=env, timeout=60, cwd=TMP)
    calls = open(REC).read().splitlines() if os.path.exists(REC) else []
    print("ok  %s (rc %d)" % (label, r.returncode))
    return r, calls


def settings_arg(r):
    args = [l[4:] for l in r.stdout.splitlines() if l.startswith("ARG ")]
    for i, a in enumerate(args):
        if a == "--settings":
            return args[i + 1]
    return None


def claude_record():
    """The fake claude's argv since the last case(); "" when it never started."""
    return open(CLAUDE_REC).read() if os.path.exists(CLAUDE_REC) else ""


def refused_unshown(r, calls, value, message):
    """The last case() refused with exit 1 and `message` (a format naming that
    case's fleet.conf), the value shows nowhere: not in stdout or stderr, not in
    any file under the case's HOME (the run ledger lives there), not on a
    command line (the fake claude never started), and op never ran."""
    conf = os.path.join(TMP, "fleet%d.conf" % n)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and message % conf in r.stderr, out
    shown = out.replace(conf, "<conf>")   # the path is random text a short value could match
    assert value not in shown and "FAKEFAKE" not in shown, out
    for d, _, files in os.walk(os.path.join(TMP, "home%d" % n)):
        for name in files:
            with open(os.path.join(d, name), errors="replace") as f:
                assert value not in f.read(), os.path.join(d, name)
    assert claude_record() == "" and calls == [], (claude_record(), calls)


r, calls = case("api mode is the default: no token, no overlay, no op call", helper=True, conf_lines=[])
assert r.returncode == 0, r.stdout + r.stderr
assert "CLAUDE_FAKE oauth_set= len=0" in r.stdout, r.stdout
assert settings_arg(r) == '{"model": "claude-fable-5-1"}', r.stdout
assert calls == [], calls

r, calls = case("api mode still refuses without an apiKeyHelper", helper=False, conf_lines=[])
assert r.returncode == 1 and "no API key source" in r.stderr, r.stdout + r.stderr

r, calls = case("enterprise: token in the worker's environment, helper emptied beside the model pin",
                helper=True, conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF])
assert r.returncode == 0, r.stdout + r.stderr
assert "CLAUDE_FAKE oauth_set=1 len=11" in r.stdout, r.stdout
assert settings_arg(r) == '{"model": "claude-fable-5-1", "apiKeyHelper": ""}', r.stdout
assert calls == ["op read " + TOKEN_REF], calls
assert "tok-abc-123" not in r.stdout + r.stderr

r, calls = case("enterprise beside a caller --model: the overlay alone", helper=False,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF],
                args=("--model", "claude-fable-5-1", "-p", "say hi"))
assert r.returncode == 0, r.stdout + r.stderr
assert settings_arg(r) == '{"apiKeyHelper": ""}', r.stdout
assert "oauth_set=1" in r.stdout

r, calls = case("enterprise beside a caller --settings: warned, not merged", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF],
                args=("--settings", '{"model": "x"}', "-p", "say hi"))
assert r.returncode == 0, r.stdout + r.stderr
assert settings_arg(r) == '{"model": "x"}' and "oauth_set=1" in r.stdout, r.stdout
assert "apiKeyHelper overlay is not merged" in r.stderr, r.stderr

r, calls = case("enterprise without OAUTH_TOKEN_REF refuses before any read", helper=True, conf_lines=["AUTH_MODE=enterprise"])
assert r.returncode == 1 and "OAUTH_TOKEN_REF is unset" in r.stderr and calls == [], r.stderr

r, calls = case("enterprise refuses when op cannot read the token", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], env_extra={"FAKE_OP_FAIL": "1"})
assert r.returncode == 1 and "cannot read the Enterprise token" in r.stderr and "CLAUDE_FAKE" not in r.stdout, r.stderr

# --- an AUTH_MODE that is neither api nor enterprise: refused, never printed ---
AUTH_REFUSAL = "claude-api: AUTH_MODE (value not shown) is neither api nor enterprise. Fix %s"
r, calls = case("a token-shaped AUTH_MODE in fleet.conf refuses without showing it", helper=True,
                conf_lines=["AUTH_MODE=" + FAKE_TOKEN])
refused_unshown(r, calls, FAKE_TOKEN, AUTH_REFUSAL)

r, calls = case("a token-shaped AUTH_MODE in the environment refuses without showing it", helper=True,
                conf_lines=["AUTH_MODE=api"], env_extra={"AUTH_MODE": FAKE_TOKEN})
refused_unshown(r, calls, FAKE_TOKEN, AUTH_REFUSAL)

# --- a token pasted where the 1Password reference belongs: refused, never printed ---
# With op working and failing, so neither the spawn nor the op-read failure line
# can carry the value.
for op_fail in ("", "1"):
    r, calls = case("enterprise refuses a non-op:// OAUTH_TOKEN_REF without printing it (op %s)"
                    % ("failing" if op_fail else "working"), helper=True,
                    conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + FAKE_TOKEN],
                    env_extra={"FAKE_OP_FAIL": op_fail} if op_fail else None)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "OAUTH_TOKEN_REF is not an op:// reference (value not shown)" in r.stderr, out
    assert os.path.join(TMP, "fleet%d.conf" % n) in r.stderr, out            # the refusal names this case's fleet.conf
    assert FAKE_TOKEN not in out and "FAKEFAKE" not in out, out
    assert "CLAUDE_FAKE" not in r.stdout and calls == [], (out, calls)   # no spawn, op never ran
# The other source: claude-api clears OAUTH_TOKEN_REF near the top (the line
# OAUTH_TOKEN_REF=""), so its fleet_key never sees a same-named environment
# variable and fleet.conf's reference is the one used. A token in that variable
# therefore never reaches op or a message.
for op_fail in ("", "1"):
    extra = {"OAUTH_TOKEN_REF": FAKE_TOKEN}
    if op_fail:
        extra["FAKE_OP_FAIL"] = op_fail
    r, calls = case("a token in the OAUTH_TOKEN_REF environment variable is never read or printed (op %s)"
                    % ("failing" if op_fail else "working"), helper=True,
                    conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], env_extra=extra)
    out = r.stdout + r.stderr
    assert r.returncode == (1 if op_fail else 0) and calls == ["op read " + TOKEN_REF], (out, calls)
    assert FAKE_TOKEN not in out and "FAKEFAKE" not in out, out


def doctor(label, conf_lines, env_extra=None):
    """bin/doctor in a throwaway HOME (no --ping: nothing live), the fake with-op
    and the fake claude on PATH. Its rc is not asserted: the throwaway HOME lacks
    the skill install, which fails doctor on its own."""
    global n
    n += 1
    home = os.path.join(TMP, "dochome%d" % n)
    os.makedirs(os.path.join(home, ".claude-api"))
    conf = os.path.join(TMP, "docfleet%d.conf" % n)
    with open(conf, "w") as f:
        f.write("".join(l + "\n" for l in conf_lines))
    if os.path.exists(REC):
        os.remove(REC)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_CODE_", "CLAUDE_API_", "ANTHROPIC_", "AUTH_MODE", "OAUTH_TOKEN_REF",
                                "MODEL_DEFAULT"))}
    env.update({"HOME": home, "FLEET_CONF": conf, "CLAUDE_API_WITH_OP": OP,
                "PATH": FAKE_BIN + os.pathsep + env.get("PATH", "")})
    env.update(env_extra or {})
    r = subprocess.run(["bash", os.path.join(HERE, "doctor")], capture_output=True, text=True, env=env,
                       timeout=60, cwd=TMP)
    calls = open(REC).read().splitlines() if os.path.exists(REC) else []
    print("ok  doctor: %s" % label)
    return r, calls


r, calls = doctor("enterprise with an op:// ref reads the token once, never shows it",
                  ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF])
assert "  ok    the Enterprise token reads from 1Password (not shown; 11 chars)" in r.stdout, r.stdout + r.stderr
assert calls == ["op read " + TOKEN_REF] and "tok-abc-123" not in r.stdout + r.stderr, (calls, r.stdout)
for where, conf_ref, env_ref in (("fleet.conf", FAKE_TOKEN, None), ("the environment", TOKEN_REF, FAKE_TOKEN)):
    r, calls = doctor("a non-op:// OAUTH_TOKEN_REF from %s is a FAIL row that never shows the value" % where,
                      ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + conf_ref],
                      {"OAUTH_TOKEN_REF": env_ref} if env_ref else None)
    out = r.stdout + r.stderr
    assert "  FAIL  OAUTH_TOKEN_REF is not an op:// reference (value not shown)" in r.stdout, out
    assert FAKE_TOKEN not in out and "FAKEFAKE" not in out, out
    assert calls == [], calls                                               # op never ran

# An AUTH_MODE claude-api refuses is a FAIL row in doctor too (it used to be
# read as api mode, so doctor passed a fleet.conf on which every spawn failed),
# from either source and without the value.
DOCTOR_AUTH_FAIL = "  FAIL  AUTH_MODE (value not shown) is neither api nor enterprise, so claude-api refuses every spawn"
for where, conf_lines, env_extra in (("fleet.conf", ["AUTH_MODE=" + FAKE_TOKEN], None),
                                     ("the environment", ["AUTH_MODE=api"], {"AUTH_MODE": FAKE_TOKEN})):
    r, calls = doctor("an AUTH_MODE from %s that is neither api nor enterprise is a FAIL row, value not shown" % where,
                      conf_lines, env_extra)
    out = r.stdout + r.stderr
    assert DOCTOR_AUTH_FAIL in r.stdout, out
    assert FAKE_TOKEN not in out and "FAKEFAKE" not in out, out
    assert calls == [], calls
for label, conf_lines in (("no AUTH_MODE line (api)", []), ("AUTH_MODE=api", ["AUTH_MODE=api"]),
                          ("AUTH_MODE=enterprise", ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF])):
    r, calls = doctor("%s has no AUTH_MODE FAIL row" % label, conf_lines)
    assert "AUTH_MODE (value not shown)" not in r.stdout + r.stderr, r.stdout + r.stderr

# --- the worker model: fleet.conf's MODEL_DEFAULT (D165 = A), a canonical id only ---
r, calls = case("the worker runs fleet.conf's MODEL_DEFAULT", helper=True, conf_lines=[],
                model_line="MODEL_DEFAULT=claude-opus-5-5")
assert r.returncode == 0, r.stdout + r.stderr
assert settings_arg(r) == '{"model": "claude-opus-5-5"}', r.stdout

r, calls = case("a quoted MODEL_DEFAULT reads like the fleet grammar", helper=True, conf_lines=[],
                model_line='MODEL_DEFAULT="claude-opus-5-5"')
assert r.returncode == 0 and settings_arg(r) == '{"model": "claude-opus-5-5"}', r.stdout + r.stderr

r, calls = case("no MODEL_DEFAULT in fleet.conf: the built-in claude-fable-5", helper=True, conf_lines=[],
                model_line=None)
assert r.returncode == 0 and settings_arg(r) == '{"model": "claude-fable-5"}', r.stdout + r.stderr

r, calls = case("MODEL_DEFAULT from the environment wins over fleet.conf", helper=True, conf_lines=[],
                model_line="MODEL_DEFAULT=claude-opus-5-5", env_extra={"MODEL_DEFAULT": "claude-fable-5-1"})
assert r.returncode == 0 and settings_arg(r) == '{"model": "claude-fable-5-1"}', r.stdout + r.stderr

# Only the fleet's canonical id passes: the rule of agent-skills'
# skills/handlers/bin/fleet_conf.sh fleet_model_required. The last three values
# passed the old check (any [A-Za-z0-9._-] string) onto the worker's command line.
MODEL_REFUSAL = ("claude-api: MODEL_DEFAULT (value not shown) from the environment or %s is not a canonical "
                 "fable/mythos/opus model id (claude-<family>-<n>[-<n>...])")
for bad in ("claude-opus-5-5 # inline comment", 'claude"x', "-opus", "claude opus",
            "claude-sonnet-5", "sonnet", "claude-opus-5.5"):
    r, calls = case("a MODEL_DEFAULT that is not a canonical id refuses before claude runs: %r" % bad,
                    helper=True, conf_lines=[], model_line="MODEL_DEFAULT=" + bad)
    refused_unshown(r, calls, bad, MODEL_REFUSAL)

# --- a token pasted as MODEL_DEFAULT, from either source: refused before it
# reaches the worker's command line (the --settings argument) or the run
# ledger, never printed. The ledger keeps the first 200 characters of the
# command line; for a -p spawn those are the injected headless briefing, so the
# interactive spawn is the one whose ledger line would carry --settings. ---
for where, conf_model, env_model in (("fleet.conf", FAKE_TOKEN, None),
                                     ("the environment", "claude-fable-5-1", FAKE_TOKEN)):
    for args in (("-p", "say hi"), ("say hi",)):
        r, calls = case("a token-shaped MODEL_DEFAULT in %s refuses (args: %s); claude never starts"
                        % (where, " ".join(args)), helper=True, conf_lines=[],
                        model_line="MODEL_DEFAULT=" + conf_model,
                        env_extra={"MODEL_DEFAULT": env_model} if env_model else None, args=args)
        refused_unshown(r, calls, FAKE_TOKEN, MODEL_REFUSAL)

# A caller's own --model or --settings still bypasses the pin: MODEL_DEFAULT is
# never read, so a token there reaches no command line and no output.
for flag, value in (("--model", "claude-sonnet-5"), ("--settings", '{"model": "claude-sonnet-5"}')):
    r, calls = case("a caller %s wins: no injection, and MODEL_DEFAULT is never read" % flag, helper=True,
                    conf_lines=[], model_line="MODEL_DEFAULT=" + FAKE_TOKEN, args=(flag, value, "-p", "say hi"))
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "ARG " + value in r.stdout, out
    assert settings_arg(r) == (None if flag == "--model" else value), out
    assert FAKE_TOKEN not in out + claude_record(), (out, claude_record())

r, calls = case("enterprise beside an Opus default: model and emptied helper in one --settings", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF],
                model_line="MODEL_DEFAULT=claude-opus-5-5")
assert r.returncode == 0 and settings_arg(r) == '{"model": "claude-opus-5-5", "apiKeyHelper": ""}', r.stdout + r.stderr

meta_env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE_", "CLAUDE_API_"))}
meta_env.update({"HOME": os.path.join(TMP, "home-meta"), "FLEET_CONF": os.path.join(TMP, "fleet3.conf"),
                 "CLAUDE_API_WITH_OP": OP, "PATH": FAKE_BIN + os.pathsep + os.environ.get("PATH", "")})
os.makedirs(os.path.join(TMP, "home-meta", ".claude-api"))
if os.path.exists(REC):
    os.remove(REC)
r2 = subprocess.run(["bash", CLAUDE_API, "--version"], capture_output=True, text=True, timeout=60, env=meta_env, cwd=TMP)
assert r2.returncode == 0 and "CLAUDE_FAKE oauth_set= len=0" in r2.stdout, r2.stdout + r2.stderr
assert not os.path.exists(REC), "a meta command read the token"
print("ok  a meta command (--version) under enterprise conf passes through without a token (rc %d)" % r2.returncode)
print("all %d claude-api auth cases passed" % (n + 1))
