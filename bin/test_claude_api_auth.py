#!/usr/bin/env python3
"""claude-api's AUTH_MODE (fleet.conf; Julian's D159 = C, 2026-10-02): api keeps
the apiKeyHelper requirement and spawns with no token; enterprise reads the
Enterprise OAuth token from 1Password (a fake with-op here) into
CLAUDE_CODE_OAUTH_TOKEN for the worker and empties apiKeyHelper through the
injected --settings (merged into the model pin; alone beside a caller's
--model; a caller's own --settings is warned, not merged). Hermetic: throwaway
HOME and config dir, a fake claude on PATH, no key, no network.
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
TMP = tempfile.mkdtemp(prefix="claude-api-auth-test-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
FAKE_BIN = os.path.join(TMP, "fakebin")
os.makedirs(FAKE_BIN)
with open(os.path.join(FAKE_BIN, "claude"), "w") as f:
    f.write('#!/usr/bin/env bash\necho "CLAUDE_FAKE oauth_set=${CLAUDE_CODE_OAUTH_TOKEN:+1} len=${#CLAUDE_CODE_OAUTH_TOKEN}"\n'
            'for a in "$@"; do printf \'ARG %s\\n\' "$a"; done\n')
os.chmod(os.path.join(FAKE_BIN, "claude"), 0o755)
REC = os.path.join(TMP, "op-calls.log")
OP = os.path.join(TMP, "fake-with-op")
with open(OP, "w") as f:
    f.write("#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> " + repr(REC) + "\n"
            "if [ -n \"${FAKE_OP_FAIL:-}\" ]; then exit 1; fi\nprintf '%s\\n' tok-abc-123\n")
os.chmod(OP, 0o755)
n = 0


def case(label, *, helper, conf_lines, args=("-p", "say hi"), env_extra=None):
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
        f.write("MODEL_DEFAULT=claude-fable-5-1\n" + "".join(l + "\n" for l in conf_lines))
    if os.path.exists(REC):
        os.remove(REC)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE_CODE_", "CLAUDE_API_", "ANTHROPIC_", "AUTH_MODE", "OAUTH_TOKEN_REF"))}
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


r, calls = case("api mode is the default: no token, no overlay, no op call", helper=True, conf_lines=[])
assert r.returncode == 0, r.stdout + r.stderr
assert "CLAUDE_FAKE oauth_set= len=0" in r.stdout, r.stdout
assert settings_arg(r) == '{"model": "claude-fable-5"}', r.stdout
assert calls == [], calls

r, calls = case("api mode still refuses without an apiKeyHelper", helper=False, conf_lines=[])
assert r.returncode == 1 and "no API key source" in r.stderr, r.stdout + r.stderr

r, calls = case("enterprise: token in the worker's environment, helper emptied beside the model pin",
                helper=True, conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF])
assert r.returncode == 0, r.stdout + r.stderr
assert "CLAUDE_FAKE oauth_set=1 len=11" in r.stdout, r.stdout
assert settings_arg(r) == '{"model": "claude-fable-5", "apiKeyHelper": ""}', r.stdout
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

r, calls = case("unknown AUTH_MODE refuses", helper=True, conf_lines=["AUTH_MODE=bogus"])
assert r.returncode == 1 and "neither api nor enterprise" in r.stderr, r.stderr

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
