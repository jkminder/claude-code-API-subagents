#!/usr/bin/env python3
"""claude-api's AUTH_MODE (fleet.conf; Julian's D159 = C, 2026-10-02): api keeps
the apiKeyHelper requirement and spawns with no token; enterprise reads the
Enterprise OAuth token from 1Password (a fake with-op here) into
CLAUDE_CODE_OAUTH_TOKEN for the worker and empties apiKeyHelper through the
injected --settings (merged into the model pin; alone beside a caller's
--model; a caller's own --settings is warned, not merged). Any other AUTH_MODE
refuses without showing the value, and is a FAIL row in doctor. An AUTH_MODE
or OAUTH_TOKEN_REF exported empty is not set (fleet.conf's value applies) and
reaches the worker, and doctor's children, still empty; a non-empty export
wins over the file. In enterprise
mode a leftover apiKeyHelper is a WARN row in doctor that names the workers it
still reaches. The injected model is fleet.conf's
MODEL_DEFAULT (Julian's D165 = A, 2026-10-02), with no built-in default: unset,
claude-api refuses like the seat launchers (Julian's D73); only
the fleet's canonical id (claude-<fable|mythos|opus>-<n>[-<n>...]) passes, and
any other value, a pasted token included, refuses before claude starts and
without showing the value; a caller's --model or --settings still bypasses the
pin, and runs with MODEL_DEFAULT unset. An OAUTH_TOKEN_REF that is not op:// plus exactly three non-empty segments
(a pasted token, alone or inside an op:// value) refuses in claude-api and is a
FAIL row in doctor, before op runs and without showing the value (both tools
read an exported OAUTH_TOKEN_REF before fleet.conf and name the source); when op
cannot read a well-formed one, neither shows the reference, and op's stderr (a
fake op echoes the reference back, literally as op 2.38.1 does or in a changed
form) is shown with the reference and each of its segments replaced by <ref>,
or withheld whole when 6 letters or digits in a row from a reference word
survive that (compared in any letter case; a name word, 1 to 15 ASCII letters
only, is not checked, so op's and with-op's real failures show on the fleet's
reference); op's message is read into memory, never into a file, from a second
read whose stdout (the token, should op answer that time) shows nowhere.
selftest's no-API checks (SELFTEST_SKIP_LIVE=1), run beside a
fleet.conf that says AUTH_MODE=enterprise, pass without calling with-op, op or
a claude session, both when an exported FLEET_CONF names that file and when
FLEET_CONF is unset and the file is at $HOME/.config/fleet/fleet.conf (a fleet
box's layout); a copy of selftest whose own fleet.conf reaches op fails, its op
stub records each call (never the reference) and check 19 names the count
first. Hermetic: throwaway HOME and config dir, a fake
claude on PATH, no key, no network.
Run: python3 bin/test_claude_api_auth.py
"""
import atexit
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_API = os.path.join(HERE, "claude-api")
TOKEN_REF = "op://Fellow - Julian Minder/Claude Enterprise Token/credential"
FAKE_TOKEN = "sk-ant-oat01-FAKEFAKEFAKE"   # token-shaped, not a real token
FLAKY_TOKEN = "sk-ant-oat01-FAKEFLAKYTOKEN"   # made up: what an op that answers the second read prints
FLAKY_ERR = "[WARN] 2026/10/03 07:24:46 a warning beside the token"
TMP = tempfile.mkdtemp(prefix="claude-api-auth-test-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
FAKE_BIN = os.path.join(TMP, "fakebin")
os.makedirs(FAKE_BIN)
CLAUDE_REC = os.path.join(TMP, "claude-calls.log")   # the fake claude's argv, one CALL block per start
with open(os.path.join(FAKE_BIN, "claude"), "w") as f:
    f.write('#!/usr/bin/env bash\n'
            '{ echo CALL; for a in "$@"; do printf \'ARG %s\\n\' "$a"; done; } >> ' + repr(CLAUDE_REC) + '\n'
            'echo "CLAUDE_FAKE oauth_set=${CLAUDE_CODE_OAUTH_TOKEN:+1} len=${#CLAUDE_CODE_OAUTH_TOKEN}"\n'
            'echo "CLAUDE_FAKE_ENV auth_mode=[${AUTH_MODE-unset}] ref=[${OAUTH_TOKEN_REF-unset}]"\n'
            'for a in "$@"; do printf \'ARG %s\\n\' "$a"; done\n')
os.chmod(os.path.join(FAKE_BIN, "claude"), 0o755)
REC = os.path.join(TMP, "op-calls.log")
OP = os.path.join(TMP, "fake-with-op")
# FAKE_OP_ECHO fails the way op does, repeating the reference on stderr. "1":
# the reference and its vault segment, literally. "op-2.38": op 2.38.1's own
# wording for an item it cannot find (measured 2026-10-03), which repeats the
# reference, the vault, the item and "<vault>/<item>" literally. The other
# modes repeat a piece in a changed form (reviewer f1954 [1]). FAKE_OP_ENV_OUT
# names a file that gets the AUTH_MODE this child of the tool inherited.
# FAKE_OP_SAYS: exit 1 with that text on stderr. FAKE_OP_FLAKY: the first call
# fails saying nothing, a later one prints FLAKY_TOKEN on stdout and FLAKY_ERR
# on stderr (an op that fails once and then answers; reviewer f1971 [15]).
FAKE_OP = r'''#!/usr/bin/env python3
import json, os, sys, urllib.parse
args = sys.argv[1:]
with open(@REC@, "a") as f:
    f.write(" ".join(args) + "\n")
if os.environ.get("FAKE_OP_ENV_OUT"):
    with open(os.environ["FAKE_OP_ENV_OUT"], "a") as f:
        f.write("AUTH_MODE=[%s]\n" % os.environ.get("AUTH_MODE", "unset"))
if os.environ.get("FAKE_OP_FLAKY"):
    with open(@REC@) as f:
        if len(f.read().splitlines()) == 1:
            sys.exit(1)
    print(@FLAKY_TOKEN@)
    sys.stderr.write(@FLAKY_ERR@ + "\n")
    sys.exit(0)
if os.environ.get("FAKE_OP_SAYS"):
    sys.stderr.write(os.environ["FAKE_OP_SAYS"] + "\n")
    sys.exit(1)
mode = os.environ.get("FAKE_OP_ECHO", "")
if mode:
    ref = args[2]
    vault, _, rest = ref[len("op://"):].partition("/")
    item, _, field = rest.partition("/")
    msg = {
        "1": f"[ERROR] could not read secret '{ref}': vault '{vault}' not found",
        "op-2.38": (f"[ERROR] 2026/10/03 07:24:46 could not read secret '{ref}': could not get item {vault}/{item}: "
                    f"\"{item}\" isn't an item in the \"{vault}\" vault. Specify the item with its UUID, name, or domain."),
        "lower": "[ERROR] could not read secret " + ref.lower(),
        "json": "[ERROR] " + json.dumps({"reference": ref}),
        "url": "[ERROR] could not read secret " + urllib.parse.quote(ref, safe=":/"),
        "escaped": "[ERROR] could not read secret " + ref.replace(" ", "\\ "),
        "words": " ".join(f"[ERROR] field '{w}' not found" for w in field.split()),
        "truncated": f"[ERROR] vault '{vault[:19]}...' not found",
        "attribute": "[ERROR] '" + ref.partition("?attribute=")[2] + "' is not a valid attribute",
    }[mode]
    sys.stderr.write(msg + "\n")
    sys.exit(1)
if os.environ.get("FAKE_OP_FAIL"):
    sys.exit(1)
print("tok-abc-123")
'''
with open(OP, "w") as f:
    f.write(FAKE_OP.replace("@REC@", repr(REC)).replace("@FLAKY_TOKEN@", repr(FLAKY_TOKEN))
            .replace("@FLAKY_ERR@", repr(FLAKY_ERR)))
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

# An AUTH_MODE exported empty is not set: fleet.conf's value (or the api
# default) decides, and the worker inherits AUTH_MODE as the caller exported
# it, still empty. claude-api used to assign the file's value to the inherited
# name, which kept the export flag, so every worker carried the file's value
# as an exported AUTH_MODE that a nested claude-api or happy-api reads as
# winning over the file (reviewer r1965 [17]). A non-empty export still wins.
# OAUTH_TOKEN_REF, exported empty beside it, reaches the worker empty too.
EXPORTED_MODE = [   # (label, AUTH_MODE line in fleet.conf or None, exported AUTH_MODE, the mode that applies)
    ("exported empty, fleet.conf says enterprise: enterprise", "AUTH_MODE=enterprise", "", "enterprise"),
    ("exported empty, no AUTH_MODE line: the api default", None, "", "api"),
    ("exported api, fleet.conf says enterprise: the export wins", "AUTH_MODE=enterprise", "api", "api"),
]
for label, mode_line, exported, mode in EXPORTED_MODE:
    r, calls = case("AUTH_MODE %s; the worker sees AUTH_MODE as exported" % label, helper=True,
                    conf_lines=([mode_line] if mode_line else []) + ["OAUTH_TOKEN_REF=" + TOKEN_REF],
                    env_extra={"AUTH_MODE": exported, "OAUTH_TOKEN_REF": ""})
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    if mode == "enterprise":
        assert calls == ["op read " + TOKEN_REF] and "CLAUDE_FAKE oauth_set=1 len=11" in r.stdout, (out, calls)
        assert settings_arg(r) == '{"model": "claude-fable-5-1", "apiKeyHelper": ""}', out
    else:
        assert calls == [] and "CLAUDE_FAKE oauth_set= len=0" in r.stdout, (out, calls)
        assert settings_arg(r) == '{"model": "claude-fable-5-1"}', out
    assert "CLAUDE_FAKE_ENV auth_mode=[%s] ref=[]\n" % exported in r.stdout, out

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
# The refusal names where the value came from and how to fix it there.
r, calls = case("a token in fleet.conf's OAUTH_TOKEN_REF: the refusal names the file and the fix", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + FAKE_TOKEN])
conf = os.path.join(TMP, "fleet%d.conf" % n)
assert r.returncode == 1 and ("claude-api: OAUTH_TOKEN_REF is not an op:// reference (value not shown); it comes "
                              "from %s. Set OAUTH_TOKEN_REF=op://<vault>/<item>/credential in %s." % (conf, conf)
                              ) in r.stderr, r.stderr

# The other source: an exported OAUTH_TOKEN_REF wins over fleet.conf, in
# claude-api as in doctor, happy-api and every fleet reader (claude-api used to
# assign the name before reading it, which hid the exported value and made it
# read fleet.conf only). A token in that variable is refused before op runs and
# never printed, and the refusal names the environment.
ENV_REF = "op://Fellow - Julian Minder/Another Item/credential"
API_ENV_REFUSAL = ("claude-api: OAUTH_TOKEN_REF is not an op:// reference (value not shown); it comes from the "
                   "environment variable OAUTH_TOKEN_REF, which wins over the file. Fix or unset the exported "
                   "OAUTH_TOKEN_REF.")
for op_fail in ("", "1"):
    extra = {"OAUTH_TOKEN_REF": FAKE_TOKEN}
    if op_fail:
        extra["FAKE_OP_FAIL"] = op_fail
    r, calls = case("a token in the exported OAUTH_TOKEN_REF is refused before op, unshown, source named (op %s)"
                    % ("failing" if op_fail else "working"), helper=True,
                    conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], env_extra=extra)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and API_ENV_REFUSAL in r.stderr, out
    assert calls == [] and claude_record() == "", (calls, claude_record())
    assert FAKE_TOKEN not in out and "FAKEFAKE" not in out, out
    for d, _, files in os.walk(os.path.join(TMP, "home%d" % n)):
        for name in files:
            with open(os.path.join(d, name), errors="replace") as f:
                assert FAKE_TOKEN not in f.read(), os.path.join(d, name)

r, calls = case("an exported OAUTH_TOKEN_REF wins over fleet.conf's (both well formed)", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF],
                env_extra={"OAUTH_TOKEN_REF": ENV_REF})
assert r.returncode == 0 and "oauth_set=1" in r.stdout and calls == ["op read " + ENV_REF], \
    (r.stdout + r.stderr, calls)

r, calls = case("a good exported OAUTH_TOKEN_REF is used while fleet.conf holds a token", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + FAKE_TOKEN],
                env_extra={"OAUTH_TOKEN_REF": ENV_REF})
out = r.stdout + r.stderr
assert r.returncode == 0 and calls == ["op read " + ENV_REF] and FAKE_TOKEN not in out, (out, calls)

r, calls = case("an empty exported OAUTH_TOKEN_REF falls through to fleet.conf", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF],
                env_extra={"OAUTH_TOKEN_REF": ""})
assert r.returncode == 0 and calls == ["op read " + TOKEN_REF], (r.stdout + r.stderr, calls)

# --- the shape of OAUTH_TOKEN_REF, the same rule in claude-api and doctor: op://
# and exactly three non-empty segments (vault, item, field) separated by "/", no
# "/", newline, carriage return or tab inside a segment, 256 characters at most.
# A token can still ride inside a well-formed reference, and op echoes the
# reference back on stderr (FAKE_OP_ECHO), so the op-read failure line never
# shows the reference and shows op's stderr with the reference and each of its
# segments replaced by <ref>. Every shape runs before the block's assert, so a
# run on an older claude-api or doctor lists each one that leaks. ---
REF_SHAPES = [   # (label, OAUTH_TOKEN_REF in fleet.conf, refused before op runs)
    ("a token as the vault, op://<token>/x/y", "op://%s/x/y" % FAKE_TOKEN, False),
    ("the good reference, a space and a token", TOKEN_REF + " " + FAKE_TOKEN, False),
    ("the good reference itself", TOKEN_REF, False),
    ("op://<token>, a newline, /x/y (fleet.conf keeps the first line)", "op://%s\n/x/y" % FAKE_TOKEN, True),
    ("four segments, a token last", TOKEN_REF + "/" + FAKE_TOKEN, True),
    ("a tab inside a segment", "op://v/i\t%s/f" % FAKE_TOKEN, True),
    ("an empty segment", "op://%s//f" % FAKE_TOKEN, True),
    ("257 characters", "op://v/i/" + FAKE_TOKEN + "x" * (257 - len("op://v/i/") - len(FAKE_TOKEN)), True),
]
REDACTED_ECHO = "[ERROR] could not read secret '<ref>': vault '<ref>' not found"
API_REF_REFUSAL = "claude-api: OAUTH_TOKEN_REF is not an op:// reference (value not shown)"
API_OP_FAIL = ("claude-api: op cannot read the Enterprise token at the reference in OAUTH_TOKEN_REF (not shown). "
               "Is the 1Password item there and ~/.config/op/service-account-token in place (mode 600)? "
               "with-op: %s; stderr: %s" % (OP, REDACTED_ECHO))
bad = []
for label, ref, refused in REF_SHAPES:
    r, calls = case("claude-api, OAUTH_TOKEN_REF %s, op failing and echoing it: %s"
                    % (label, "refused before op" if refused else "op's stderr shown redacted"), helper=True,
                    conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + ref], env_extra={"FAKE_OP_ECHO": "1"})
    out = r.stdout + r.stderr
    want = (API_REF_REFUSAL in r.stderr and calls == []) if refused else \
        (API_OP_FAIL in r.stderr and calls == ["op read " + ref] * 2)
    if not (want and r.returncode == 1 and ref not in out and FAKE_TOKEN not in out and "FAKEFAKE" not in out
            and claude_record() == ""):
        bad.append((label, r.returncode, calls, out))
assert not bad, bad

ref256 = "op://v/i/" + "x" * (256 - len("op://v/i/"))
r, calls = case("claude-api: a 256-character reference still reaches op and reads", helper=True,
                conf_lines=["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + ref256])
assert r.returncode == 0 and "oauth_set=1" in r.stdout and calls == ["op read " + ref256], (r.stdout + r.stderr, calls)


def doctor(label, conf_lines, env_extra=None, helper=False):
    """bin/doctor in a throwaway HOME (no --ping: nothing live), the fake with-op
    and the fake claude on PATH; with helper, the config dir's settings.json
    carries an apiKeyHelper. Its rc is not asserted: the throwaway HOME lacks
    the skill install, which fails doctor on its own."""
    global n
    n += 1
    home = os.path.join(TMP, "dochome%d" % n)
    os.makedirs(os.path.join(home, ".claude-api"))
    if helper:
        with open(os.path.join(home, ".claude-api", "settings.json"), "w") as f:
            json.dump({"apiKeyHelper": "/x/with-op op read 'op://v/i/credential'"}, f)
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
# A leftover apiKeyHelper in enterprise mode is a WARN row naming the workers it
# still reaches: claude-api empties it only through the --settings it injects.
# The row used to say every worker empties it.
r, calls = doctor("enterprise with a leftover apiKeyHelper: the WARN row names who still runs it",
                  ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], helper=True)
assert ("  WARN  an apiKeyHelper is still in %s/settings.json. claude-api empties it for a worker through the "
        "--settings it injects, but a worker given its own --settings runs it and bills the API key unless that "
        "--settings carries \"apiKeyHelper\": \"\". Remove it once every seat has restarted on the token.\n"
        % os.path.join(TMP, "dochome%d" % n, ".claude-api")) in r.stdout, r.stdout
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
# doctor reads AUTH_MODE as claude-api does: exported empty, fleet.conf's
# enterprise applies, and doctor's children (op here, the --ping worker) inherit
# AUTH_MODE still empty, not the file's value (reviewer r1965 [17]).
OP_ENV = os.path.join(TMP, "op-env.log")
r, calls = doctor("AUTH_MODE exported empty: fleet.conf's enterprise applies, op inherits AUTH_MODE empty",
                  ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], {"AUTH_MODE": "", "FAKE_OP_ENV_OUT": OP_ENV})
conf = os.path.join(TMP, "docfleet%d.conf" % n)
assert "  ok    AUTH_MODE=enterprise: OAUTH_TOKEN_REF set (not shown), from %s\n" % conf in r.stdout, r.stdout
assert calls == ["op read " + TOKEN_REF], calls
with open(OP_ENV) as f:
    seen = f.read()
assert seen == "AUTH_MODE=[]\n", seen

# The OAUTH_TOKEN_REF shapes again, in doctor, plus a newline from the
# environment (a variable of that name wins over fleet.conf, as in claude-api).
DOC_REF_FAIL = "  FAIL  OAUTH_TOKEN_REF is not an op:// reference (value not shown)"
DOC_OP_FAIL = ("  FAIL  op cannot read the Enterprise token at the reference in OAUTH_TOKEN_REF (not shown)"
               " — stderr: " + REDACTED_ECHO)
bad = []
for label, conf_ref, env_ref, refused in ([(l, ref, None, refused) for l, ref, refused in REF_SHAPES]
                                          + [("the good reference, a newline and a token, from the environment",
                                              TOKEN_REF, TOKEN_REF + "\n" + FAKE_TOKEN, True)]):
    ref = env_ref or conf_ref
    extra = {"FAKE_OP_ECHO": "1"}
    if env_ref:
        extra["OAUTH_TOKEN_REF"] = env_ref
    r, calls = doctor("OAUTH_TOKEN_REF %s, op failing and echoing it: %s"
                      % (label, "a FAIL row before op" if refused else "op's stderr shown redacted"),
                      ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + conf_ref], extra)
    out = r.stdout + r.stderr
    want = (DOC_REF_FAIL in r.stdout and calls == []) if refused else \
        (DOC_OP_FAIL in r.stdout and calls == ["op read " + ref] * 2)
    if not (want and ref not in out and FAKE_TOKEN not in out and "FAKEFAKE" not in out):
        bad.append((label, calls, out))
assert not bad, bad


def op_failure(tool, label, conf_lines, extra):
    """claude-api (a -p spawn) or doctor, with op failing: (r, op calls, what
    the failure line shows of op's stderr or None without exactly one such
    line, whether the tool otherwise behaved: claude-api exits 1 and never
    starts claude; doctor's rc is not asserted)."""
    if tool == "claude-api":
        r, calls = case("claude-api, " + label, helper=True, conf_lines=conf_lines, env_extra=extra)
        lines = [l for l in r.stderr.splitlines() if l.startswith("claude-api: op cannot read")]
        shown = lines[0].split("; stderr: ", 1)[1] if len(lines) == 1 else None
        return r, calls, shown, r.returncode == 1 and claude_record() == ""
    r, calls = doctor(label, conf_lines, extra)
    lines = [l for l in r.stdout.splitlines() if l.startswith("  FAIL  op cannot read")]
    shown = lines[0].split(" — stderr: ", 1)[1] if len(lines) == 1 else None
    return r, calls, shown, True


# op repeating the reference in a changed form (reviewer f1954 [1]), in both
# tools. op 2.38.1 repeats the whole reference and its segments literally
# (FAKE_OP_ECHO=op-2.38), which the replacement covers, so op's message shows;
# a JSON-quoted copy is replaced too. A piece in any other form (URL-encoded,
# escaped, lower-cased, split into words, cut short, an attribute alone)
# withholds the whole message once 6 letters or digits in a row from a checked
# word of the reference (any word but a name word: 1 to 15 ASCII letters only)
# survive the replacement, compared in any letter case. Every mode runs against
# every reference before the block's assert, so a run on an older tool lists
# each leak.
ECHO_REFS =[TOKEN_REF + " " + FAKE_TOKEN, "op://%s/x/y" % FAKE_TOKEN, TOKEN_REF + "?attribute=" + FAKE_TOKEN]
# cut to 19 characters, the vault keeps exactly 6 letters of the token's random
# part ("sk-ant-oat01-FAKEFA"): the shortest piece that withholds
ECHO_MODES = ["op-2.38", "lower", "json", "url", "escaped", "words", "truncated", "attribute"]
WITHHELD = "(withheld: it repeats part of the reference in a changed form)"
MUST_WITHHOLD = ({("url", 0), ("escaped", 0), ("words", 0), ("truncated", 1), ("attribute", 2)}
                 | {("lower", i) for i in range(len(ECHO_REFS))})
MUST_SHOW = {(mode, i) for mode in ("op-2.38", "json") for i in range(len(ECHO_REFS))}
OP_238_SHOWN = ("[ERROR] 2026/10/03 07:24:46 could not read secret '<ref>': could not get item <ref>/<ref>: "
                "\"<ref>\" isn't an item in the \"<ref>\" vault. Specify the item with its UUID, name, or domain.")
bad = []
for tool in ("claude-api", "doctor"):
    for mode in ECHO_MODES:
        for i, ref in enumerate(ECHO_REFS):
            r, calls, shown, ok = op_failure(tool, "op repeating the reference (%s) of shape %d" % (mode, i),
                                             ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + ref], {"FAKE_OP_ECHO": mode})
            out = r.stdout + r.stderr
            ok = ok and shown is not None and calls == ["op read " + ref] * 2
            low = out.lower()   # a lower-cased copy leaks the token too
            ok = ok and "fakefa" not in low and FAKE_TOKEN.lower() not in low and ref.lower() not in low
            if (mode, i) in MUST_WITHHOLD:
                ok = ok and shown.strip() == WITHHELD
            if (mode, i) in MUST_SHOW:
                ok = ok and WITHHELD not in shown and "<ref>" in shown
            if not ok:
                bad.append((tool, mode, i, calls, out))
assert not bad, bad
# One pass of the replacement: a segment that is also part of "<ref>" never
# cuts into a <ref> already written (one replacement after another did:
# "'<<ref>>'").
for tool in ("claude-api", "doctor"):
    conf_lines = ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=op://ref/q/z"]
    want = "[ERROR] could not read secret '<ref>': vault '<ref>' not found"
    if tool == "claude-api":
        r, calls = case("claude-api: a segment named ref leaves the <ref> marks whole", helper=True,
                        conf_lines=conf_lines, env_extra={"FAKE_OP_ECHO": "1"})
        assert r.stderr.rstrip(" \n").endswith("; stderr: " + want), r.stderr
    else:
        r, calls = doctor("a segment named ref leaves the <ref> marks whole", conf_lines, {"FAKE_OP_ECHO": "1"})
        assert "— stderr: " + want + "\n" in r.stdout, r.stdout
# op 2.38.1's own wording on the fleet's reference shows whole, every name in it replaced
for tool in ("claude-api", "doctor"):
    conf_lines = ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF]
    if tool == "claude-api":
        r, calls = case("claude-api: op 2.38.1's wording on the fleet's reference shows", helper=True,
                        conf_lines=conf_lines, env_extra={"FAKE_OP_ECHO": "op-2.38"})
        assert r.stderr.rstrip(" \n").endswith("; stderr: " + OP_238_SHOWN), r.stderr
    else:
        r, calls = doctor("op 2.38.1's wording on the fleet's reference shows", conf_lines, {"FAKE_OP_ECHO": "op-2.38"})
        assert ("  FAIL  op cannot read the Enterprise token at the reference in OAUTH_TOKEN_REF (not shown) — stderr: "
                + OP_238_SHOWN) in r.stdout, r.stdout
    assert "Fellow" not in r.stdout + r.stderr and "Enterprise Token" not in r.stdout + r.stderr, r.stdout + r.stderr
# Longest first (reviewer f1971 [16]): a segment that starts a longer segment
# never cuts into it. Shortest first turned the item "Vault <token>" into
# "<ref> <token>" (then withheld whole) and the item "Fellow Token" into
# "<ref> Token".
bad = []
for tool in ("claude-api", "doctor"):
    for ref in ("op://Vault/Vault %s/credential" % FAKE_TOKEN, "op://Fellow/Fellow Token/credential"):
        r, calls, shown, ok = op_failure(tool, "the item starts with the vault's name: replaced longest first",
                                         ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + ref], {"FAKE_OP_ECHO": "op-2.38"})
        out = r.stdout + r.stderr
        if not (ok and shown == OP_238_SHOWN and "FAKEFAKE" not in out.upper() and calls == ["op read " + ref] * 2):
            bad.append((tool, ref, calls, out))
assert not bad, bad

# What a seat on this box reads when op cannot start (reviewer f1971 [14]): the
# four bootstrap-file refusals of agent-skills' with-op in its words (HOME
# /home/jkminder, user jkminder) and two op errors, a bad service-account token
# and a config directory op does not own (strings in op 2.38.1; how op joins
# their parts is assumed). On the fleet's reference every word is a name word,
# which the check skips, so each shows whole, with the exact replacement
# applied ("credentials" holds the field segment "credential"); the check used
# to withhold all of them and blame the reference ("minder", "credential").
BOOTSTRAP_FILE = "/home/jkminder/.config/op/service-account-token"
WITH_OP_REFUSALS = [
    "with-op: op bootstrap token file missing: " + BOOTSTRAP_FILE
    + " (the one sanctioned on-disk secret; see CLAUDE.md 'Secrets and API keys')",
    "with-op: cannot stat " + BOOTSTRAP_FILE,
    "with-op: refusing " + BOOTSTRAP_FILE + ": mode and owner are '644 jkminder', must be '600 jkminder' "
    "(chmod 600 and chown jkminder it)",
    "with-op: op bootstrap token file is empty: " + BOOTSTRAP_FILE,
]
OP_NOT_OWNED = ("[ERROR] 2026/10/03 07:24:46 Can't continue. We can't safely access \"/home/jkminder/.config/op\" "
                "because it's not owned by the current user. Change the owner or logged in user and try again.")
REAL_FAILURES = [(said, said) for said in WITH_OP_REFUSALS + [OP_NOT_OWNED]] + [
    ("[ERROR] 2026/10/03 07:24:46 failed to DecodeSACredentials: invalid credentials provided",
     "[ERROR] 2026/10/03 07:24:46 failed to DecodeSACredentials: invalid <ref>s provided")]
bad = []
for tool in ("claude-api", "doctor"):
    for i, (said, want) in enumerate(REAL_FAILURES):
        r, calls, shown, ok = op_failure(tool, "op's real failure %d on the fleet's reference shows" % i,
                                         ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], {"FAKE_OP_SAYS": said})
        if not (ok and shown == want and calls == ["op read " + TOKEN_REF] * 2):
            bad.append((tool, said, r.stdout + r.stderr))
assert not bad, bad

# The withhold rule at its edges (reviewer f1971 [16]): (OAUTH_TOKEN_REF, what
# op says on stderr, withheld?). Runs of exactly 6 ("ab12cd", "qwerty") are one
# window each, found in any letter case; their 5-character pieces show, and so
# does a word whose runs are 5 long. A word of 15 ASCII letters only is a name
# word and is not checked; 16 letters, or one digit, '-' or '_', make a word
# checked (reviewer r1982 [8]: 'sk-ant-FAKEFAKE' is 15 characters). A shown
# message is unchanged (no exact piece of the reference is in it).
EDGES = [
    ("op://Vault/Item/key ab12cd-QWERTY", "[ERROR] field 'ab12cd' not found", True),
    ("op://Vault/Item/key ab12cd-QWERTY", "[ERROR] field 'qwerty' not found", True),
    ("op://Vault/Item/key ab12cd-QWERTY", "[ERROR] ab12c b12cd qwert werty", False),
    ("op://Vault/Item/key ab12c-QWERT", "[ERROR] field 'ab12c-qwert' not found", False),
    ("op://Vault/Item/key Abcdefghijklmno", "[ERROR] could not read secret op://vault/item/key abcdefghijklmno", False),
    ("op://Vault/Item/key Abcdefghijklmnop", "[ERROR] could not read secret op://vault/item/key abcdefghijklmnop", True),
    ("op://Vault/Item/key Qwertyui", "[ERROR] could not read secret op://vault/item/key qwertyui", False),
    ("op://Vault/Item/key Qwerty1i", "[ERROR] could not read secret op://vault/item/key qwerty1i", True),
    ("op://Vault/Item/key sk-ant-FAKEFAKE", "[ERROR] could not read secret op://vault/item/key sk-ant-fakefake", True),
    ("op://Vault/Item/key sk_ant_FAKEFAKE", "[ERROR] could not read secret op://vault/item/key sk_ant_fakefake", True),
]
bad = []
for tool in ("claude-api", "doctor"):
    for i, (ref, said, withheld) in enumerate(EDGES):
        r, calls, shown, ok = op_failure(tool, "the withhold rule's edge %d (%s)" % (i, "withheld" if withheld else "shown"),
                                         ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + ref], {"FAKE_OP_SAYS": said})
        if not (ok and shown == (WITHHELD if withheld else said) and calls == ["op read " + ref] * 2):
            bad.append((tool, ref, said, r.stdout + r.stderr))
assert not bad, bad

# op's reason comes from a second read whose stdout goes to /dev/null (reviewer
# f1971 [15]). An op that fails the first read and answers the second prints
# the token on that stdout: the failure line shows the second read's stderr
# only, and the token shows nowhere.
bad = []
for tool in ("claude-api", "doctor"):
    r, calls, shown, ok = op_failure(tool, "op fails the first read and answers the second: the token shows nowhere",
                                     ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], {"FAKE_OP_FLAKY": "1"})
    out = r.stdout + r.stderr
    if not (ok and shown == FLAKY_ERR and calls == ["op read " + TOKEN_REF] * 2 and "FAKEFLAKY" not in out.upper()):
        bad.append((tool, calls, out))
assert not bad, bad
# op's message is held in memory, never in a file: with no usable temporary
# directory the failure line still carries it (claude-api used to stop at
# mktemp, doctor at the redirect into an unnamed file).
for tool in ("claude-api", "doctor"):
    extra = {"FAKE_OP_ECHO": "1", "TMPDIR": os.path.join(TMP, "no-such-dir")}
    conf_lines = ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF]
    if tool == "claude-api":
        r, calls = case("claude-api: op's message needs no temporary file", helper=True, conf_lines=conf_lines,
                        env_extra=extra)
        assert API_OP_FAIL in r.stderr and r.returncode == 1, r.stderr
    else:
        r, calls = doctor("op's message needs no temporary file", conf_lines, extra)
        assert DOC_OP_FAIL in r.stdout, r.stdout + r.stderr
    assert calls == ["op read " + TOKEN_REF] * 2, calls

# doctor names the source of the reference too, and reads the exported one.
DOC_ENV_FAIL = ("  FAIL  OAUTH_TOKEN_REF is not an op:// reference (value not shown); it comes from the "
                "environment variable OAUTH_TOKEN_REF, which wins over the file. Fix or unset the exported "
                "OAUTH_TOKEN_REF.")
r, calls = doctor("a token in the exported OAUTH_TOKEN_REF: the FAIL row names the environment",
                  ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], {"OAUTH_TOKEN_REF": FAKE_TOKEN})
out = r.stdout + r.stderr
assert DOC_ENV_FAIL in r.stdout and calls == [] and FAKE_TOKEN not in out and "FAKEFAKE" not in out, out
r, calls = doctor("a token in fleet.conf's OAUTH_TOKEN_REF: the FAIL row names the file",
                  ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + FAKE_TOKEN])
conf = os.path.join(TMP, "docfleet%d.conf" % n)
assert ("  FAIL  OAUTH_TOKEN_REF is not an op:// reference (value not shown); it comes from %s. Set "
        "OAUTH_TOKEN_REF=op://<vault>/<item>/credential in %s." % (conf, conf)) in r.stdout, r.stdout
r, calls = doctor("an exported OAUTH_TOKEN_REF: the ok row names the environment and op reads that one",
                  ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF], {"OAUTH_TOKEN_REF": ENV_REF})
out = r.stdout + r.stderr
assert ("  ok    AUTH_MODE=enterprise: OAUTH_TOKEN_REF set (not shown), from the environment variable "
        "OAUTH_TOKEN_REF, which wins over the file") in r.stdout and calls == ["op read " + ENV_REF], (out, calls)
assert ENV_REF not in out and TOKEN_REF not in out, out
r, calls = doctor("OAUTH_TOKEN_REF from fleet.conf: the ok row names the file",
                  ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + TOKEN_REF])
conf = os.path.join(TMP, "docfleet%d.conf" % n)
assert "  ok    AUTH_MODE=enterprise: OAUTH_TOKEN_REF set (not shown), from %s" % conf in r.stdout, r.stdout

# claude-api and doctor take the reference from the same source: on each pair
# of values below both read the same reference (the same op call) or both
# refuse it before op runs. The two disagreed before claude-api honoured an
# exported OAUTH_TOKEN_REF.
AGREE = [   # (label, fleet.conf value, exported value or None)
    ("fleet.conf only", TOKEN_REF, None),
    ("an exported reference over fleet.conf's", TOKEN_REF, ENV_REF),
    ("an exported reference over a token in fleet.conf", FAKE_TOKEN, ENV_REF),
    ("an exported token over a good fleet.conf", TOKEN_REF, FAKE_TOKEN),
    ("an empty export over a good fleet.conf", TOKEN_REF, ""),
    ("a token in fleet.conf, nothing exported", FAKE_TOKEN, None),
]
bad = []
for label, conf_ref, env_ref in AGREE:
    extra = {} if env_ref is None else {"OAUTH_TOKEN_REF": env_ref}
    conf_lines = ["AUTH_MODE=enterprise", "OAUTH_TOKEN_REF=" + conf_ref]
    ra, api_calls = case("claude-api, source agreement: " + label, helper=True, conf_lines=conf_lines,
                         env_extra=extra)
    rd, doc_calls = doctor("source agreement: " + label, conf_lines, extra)
    api_refused = API_REF_REFUSAL in ra.stderr
    doc_refused = DOC_REF_FAIL in rd.stdout
    if api_calls != doc_calls or api_refused != doc_refused:
        bad.append((label, api_calls, doc_calls, api_refused, doc_refused))
assert not bad, bad

# --- the worker model: fleet.conf's MODEL_DEFAULT (D165 = A), a canonical id only ---
r, calls = case("the worker runs fleet.conf's MODEL_DEFAULT", helper=True, conf_lines=[],
                model_line="MODEL_DEFAULT=claude-opus-5-5")
assert r.returncode == 0, r.stdout + r.stderr
assert settings_arg(r) == '{"model": "claude-opus-5-5"}', r.stdout

r, calls = case("a quoted MODEL_DEFAULT reads like the fleet grammar", helper=True, conf_lines=[],
                model_line='MODEL_DEFAULT="claude-opus-5-5"')
assert r.returncode == 0 and settings_arg(r) == '{"model": "claude-opus-5-5"}', r.stdout + r.stderr

# No built-in default (Julian's D73): an unset MODEL_DEFAULT refuses like the
# seat launchers, naming the file to fix; claude never starts and op never runs.
UNSET_REFUSAL = "claude-api: MODEL_DEFAULT is not set — it has no built-in default."
for label, model_line, extra in (("no MODEL_DEFAULT line in fleet.conf", None, None),
                                 ("an empty MODEL_DEFAULT= line", "MODEL_DEFAULT=", None),
                                 ("an exported empty MODEL_DEFAULT and no line", None, {"MODEL_DEFAULT": ""}),
                                 ("no fleet.conf at all", None, {"FLEET_CONF": os.path.join(TMP, "absent.conf")})):
    r, calls = case("unset MODEL_DEFAULT refuses before claude runs: " + label, helper=True, conf_lines=[],
                    model_line=model_line, env_extra=extra)
    out = r.stdout + r.stderr
    conf = (extra or {}).get("FLEET_CONF") or os.path.join(TMP, "fleet%d.conf" % n)
    assert r.returncode == 1 and UNSET_REFUSAL in r.stderr, out
    assert "to %s (or export MODEL_DEFAULT for this run), or pass --model." % conf in r.stderr, out
    assert claude_record() == "" and calls == [], (claude_record(), calls)

r, calls = case("unset in fleet.conf, exported: the exported id runs", helper=True, conf_lines=[],
                model_line=None, env_extra={"MODEL_DEFAULT": "claude-opus-5-5"})
assert r.returncode == 0 and settings_arg(r) == '{"model": "claude-opus-5-5"}', r.stdout + r.stderr

r, calls = case("unset, but the caller passes --model: runs, nothing injected", helper=True, conf_lines=[],
                model_line=None, args=("--model", "claude-fable-5-1", "-p", "say hi"))
assert r.returncode == 0 and settings_arg(r) is None and "ARG claude-fable-5-1" in r.stdout, r.stdout + r.stderr

# The --settings bypass with the key unset too: the caller's --settings is the
# only one claude gets, and nothing refuses. A refusal of --settings callers on
# an unset key passed every case above (reviewer r1965 [4]).
r, calls = case("unset, but the caller passes --settings: runs on the caller's --settings alone", helper=True,
                conf_lines=[], model_line=None, args=("--settings", '{"model": "claude-sonnet-5"}', "-p", "say hi"))
out = r.stdout + r.stderr
assert r.returncode == 0 and "MODEL_DEFAULT" not in r.stderr, out
assert [l for l in r.stdout.splitlines() if l.startswith("ARG ")].count("ARG --settings") == 1, out
assert settings_arg(r) == '{"model": "claude-sonnet-5"}', out

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

# selftest's no-API checks (11-19, what SELFTEST_SKIP_LIVE=1 runs) use no
# credential, whatever AUTH_MODE the box uses: selftest exports FLEET_CONF to
# its own file (AUTH_MODE=api), and CLAUDE_API_WITH_OP points at a stub that
# records each call and fails. They used to take AUTH_MODE from the caller's
# fleet.conf, so on an enterprise box every claude-api spawn in them read the
# real Enterprise token through with-op. Here selftest runs through that switch
# (checks 1-10 never start) in a throwaway HOME and TMPDIR beside a fleet.conf
# that says AUTH_MODE=enterprise, with a fake reference and a MODEL_DEFAULT
# like a fleet box. Traps for with-op, op and a claude session sit first on
# PATH: on a real box those would be the real ones, so any call to them fails
# these runs (the claude trap answers --version, which doctor asks in check
# 19). Four runs, side by side:
# - "env": the caller exports FLEET_CONF naming that file.
# - "exported": as "env", and the caller also exports AUTH_MODE=enterprise and
#   OAUTH_TOKEN_REF, as a seat's shell may. The environment wins over the file,
#   so only selftest's own unset keeps checks 11-19 in api mode (reviewer r1982
#   [13]: without it 6 of them fail).
# - "home": FLEET_CONF unset and the file at $HOME/.config/fleet/fleet.conf, a
#   fleet box's layout. Only this run sees selftest's own FLEET_CONF lose its
#   export, since an inherited variable stays exported (reviewer f1979 [7]).
# - "op": a copy of selftest whose own fleet.conf says AUTH_MODE=enterprise, so
#   its spawns reach op. It must fail without a trap call, its op stub must
#   record each call (never the reference), and check 19's FAIL line must start
#   with that count (reviewer f1979 [8]). A copy that lost the stub, its export
#   or check 19 (f) passes a trap call or loses the count.
# Every run must leave the caller's fleet.conf as it was: a selftest that took
# an exported FLEET_CONF for its own would write AUTH_MODE=api into it, and
# pass.
ST_CONF = ("AUTH_MODE=enterprise\nOAUTH_TOKEN_REF=op://Selftest Vault/Selftest Item/credential\n"
           "MODEL_DEFAULT=claude-opus-5-5\n")
ST_RUNS = []   # (label, name, Popen, stdout path, traps log path, the caller's fleet.conf)


def op_reaching_selftest(path):
    """A copy of bin/selftest at `path` whose own fleet.conf (checks 11-19)
    says AUTH_MODE=enterprise with a fake reference, and whose BIN_DIR is this
    bin dir. Each edited line must occur once: if one moved, update this."""
    with open(os.path.join(HERE, "selftest")) as f:
        src = f.read()
    for old, new in (("printf 'AUTH_MODE=api\\nMODEL_DEFAULT=claude-opus-5-5\\n' > \"$FLEET_CONF\"",
                      "printf 'AUTH_MODE=enterprise\\nOAUTH_TOKEN_REF=op://Selftest Vault/Selftest Item/credential"
                      "\\nMODEL_DEFAULT=claude-opus-5-5\\n' > \"$FLEET_CONF\""),
                     ('BIN_DIR="$(cd "$(dirname "$SRC")" && pwd)"', "BIN_DIR=" + shlex.quote(HERE))):
        assert src.count(old) == 1, "selftest has %d copies of %r" % (src.count(old), old)
        src = src.replace(old, new)
    with open(path, "w") as f:
        f.write(src)
    return path


def start_selftest(label, name, conf_at, script=None, exported=None):
    """Starts selftest's checks 11-19 in TMP/<name> (throwaway HOME, TMPDIR,
    traps first on PATH) beside the enterprise fleet.conf ST_CONF, exported as
    FLEET_CONF (conf_at "env") or at $HOME/.config/fleet/fleet.conf with
    FLEET_CONF unset ("home"). `exported`: more variables the caller exports."""
    st_dir = os.path.join(TMP, name)
    st_trapbin, st_home, st_tmp = (os.path.join(st_dir, d) for d in ("trapbin", "home", "tmp"))
    for d in (st_trapbin, st_home, st_tmp):
        os.makedirs(d)
    traps = os.path.join(st_dir, "traps.log")
    for trap, body in (("with-op", "echo with-op >> %s\nexit 98\n"), ("op", "echo op >> %s\nexit 98\n"),
                       ("claude", '[ "$*" = --version ] && { echo "0.0.0 (trap)"; exit 0; }\n'
                                  'echo claude >> %s\nexit 98\n')):
        with open(os.path.join(st_trapbin, trap), "w") as f:
            f.write("#!/usr/bin/env bash\n" + body % shlex.quote(traps))
        os.chmod(os.path.join(st_trapbin, trap), 0o755)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC", "SELFTEST_"))
           and k not in ("AUTH_MODE", "OAUTH_TOKEN_REF", "MODEL_DEFAULT", "XDG_CONFIG_HOME", "FLEET_CONF")}
    env.update({"HOME": st_home, "TMPDIR": st_tmp, "SELFTEST_SKIP_LIVE": "1",
                "PATH": st_trapbin + os.pathsep + os.environ.get("PATH", "")})
    env.update(exported or {})
    if conf_at == "env":
        conf = os.path.join(st_dir, "fleet.conf")
        env["FLEET_CONF"] = conf
    else:
        assert conf_at == "home", conf_at
        conf = os.path.join(st_home, ".config", "fleet", "fleet.conf")
        os.makedirs(os.path.dirname(conf))
    with open(conf, "w") as f:
        f.write(ST_CONF)
    out = os.path.join(st_dir, "stdout")
    with open(out, "w") as fo, open(os.path.join(st_dir, "stderr"), "w") as fe:
        proc = subprocess.Popen(["bash", script or os.path.join(HERE, "selftest")], stdout=fo, stderr=fe, text=True,
                                env=env, cwd=st_tmp, stdin=subprocess.DEVNULL)
    ST_RUNS.append((label, name, proc, out, traps, conf))


start_selftest("selftest checks 11-19 beside an enterprise fleet.conf named by an exported FLEET_CONF",
               "selftest-env", "env")
start_selftest("selftest checks 11-19 with AUTH_MODE=enterprise and OAUTH_TOKEN_REF exported by the caller",
               "selftest-exported", "env",
               exported={"AUTH_MODE": "enterprise", "OAUTH_TOKEN_REF": "op://Selftest Vault/Selftest Item/credential"})
start_selftest("selftest checks 11-19 beside an enterprise fleet.conf at $HOME/.config/fleet/fleet.conf, "
               "FLEET_CONF unset", "selftest-home", "home")
start_selftest("a selftest copy whose own fleet.conf reaches op: fails, the op stub records the calls, check 19 "
               "names the count first", "selftest-op", "home",
               op_reaching_selftest(os.path.join(TMP, "selftest-op-reaching")))
st = {}
for label, name, proc, out, traps, conf in ST_RUNS:
    rc = proc.wait(timeout=600)
    n += 1
    print("ok  %s (rc %d)" % (label, rc))
    with open(out) as f:
        stdout = f.read()
    trap_calls = open(traps).read() if os.path.exists(traps) else ""
    assert trap_calls == "", ("with-op, op or a claude session on PATH ran", label, trap_calls, stdout)
    with open(conf) as f:
        assert f.read() == ST_CONF, ("selftest changed the caller's fleet.conf", label, conf)
    st[name] = (rc, stdout)
for name in ("selftest-env", "selftest-exported", "selftest-home"):
    rc, stdout = st[name]
    assert rc == 0 and "selftest: checks 11-19 passed (live checks 1-10 SKIPPED)\n" in stdout, (name, stdout)
    assert stdout.count("   PASS\n") == 9 and "FAIL" not in stdout, (name, stdout)
rc, stdout = st["selftest-op"]
assert rc == 1, stdout
kept = re.findall(r"^artifacts kept in (.+)$", stdout, re.M)
assert len(kept) == 1, stdout
op_calls_path = os.path.join(kept[0], "op-stub.calls")
assert os.path.exists(op_calls_path), ("the op stub recorded no call", stdout)
with open(op_calls_path) as f:
    op_calls = f.read().splitlines()
assert op_calls and set(op_calls) == {"called"}, op_calls   # one line per call, never the reference
check19 = stdout[stdout.index("== 19/19"):].splitlines()
assert check19[1].startswith("   FAIL: key path: op was called in checks 11-19: the op stub recorded %d call(s) "
                             "(the t*.err files name the failing spawns)" % len(op_calls)), check19
print("all %d claude-api auth cases passed" % (n + 1))
