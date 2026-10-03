#!/usr/bin/env python3
"""claude-sub starts claude only on Julian's personal claude.ai login: the
config dir's .credentials.json must record claudeAiOauth.subscriptionType max
or pro. Anything else (enterprise, team, an empty or missing type, a missing,
unreadable or malformed file, a type that is not a plain name) exits 3 with a
one-line fix on stderr, claude never starts, and no other part of the file
reaches stdout or stderr. It also exits 3 when anything (a directory, a file,
a dangling symlink) is at the Anthropic profile store path the child claude
reads: $XDG_CONFIG_HOME/anthropic, else $HOME/.config/anthropic, each
variable trimmed of surrounding whitespace. Before exec, claude-sub unsets
every variable that outranks the login (ANTHROPIC_CONFIG_DIR, which names the
store, included; XDG_CONFIG_HOME stays) and the calling Claude Code session's
own variables.
Hermetic: a throwaway HOME and config dir, no inherited XDG_CONFIG_HOME, fake
profile stores holding fake data, a fake claude on PATH that records
its argv, its CLAUDE_CONFIG_DIR (a path this test made) and the NAMES of its
environment variables (never a value), no key, no network. Every case runs
even when an earlier one fails; the exit code is 1 when any case failed.
Run: python3 bin/test_claude_sub.py
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CLAUDE_SUB = os.path.join(HERE, "claude-sub")
FAKE_TOKEN = "sk-ant-oat01-FAKEFAKEFAKE"   # token-shaped, not a real token
TMP = tempfile.mkdtemp(prefix="claude-sub-test-")
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
FAKE_BIN = os.path.join(TMP, "fakebin")
os.makedirs(FAKE_BIN)
REC = os.path.join(TMP, "claude-calls.log")   # the fake claude's record, one CALL block per start
with open(os.path.join(FAKE_BIN, "claude"), "w") as f:
    f.write('#!/usr/bin/env bash\n'
            '{ echo CALL\n'
            '  for a in "$@"; do printf \'ARG %s\\n\' "$a"; done\n'
            '  printf \'CFG %s\\n\' "${CLAUDE_CONFIG_DIR-}"\n'
            '  compgen -e | sed \'s/^/ENV /\'\n'
            '} >> ' + repr(REC) + '\n'
            'echo FAKE_CLAUDE_RAN\n')
os.chmod(os.path.join(FAKE_BIN, "claude"), 0o755)

# The calling Claude Code session's variables (unset since 2026-10-02).
SESSION_VARS = ["CLAUDE_CODE_ENTRYPOINT", "CLAUDECODE", "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_AGENT_SDK_VERSION",
                "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_SESSION_ATTENDED", "CLAUDE_CODE_MESSAGING_SOCKET",
                "CLAUDE_CODE_MESSAGING_TOKEN", "CLAUDE_CODE_EXECPATH", "CLAUDE_PID"]
# Four more that outrank the stored login in claude 2.1.287 (unset since 2026-10-02).
NEW_AUTH_VARS = ["ANTHROPIC_UNIX_SOCKET", "ANTHROPIC_FEDERATION_RULE_ID", "ANTHROPIC_ORGANIZATION_ID",
                 "ANTHROPIC_PROFILE"]
# The variables claude-sub unset before.
OLD_UNSET_VARS = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
                  "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR", "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
                  "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                  "CLAUDE_CODE_USE_ANTHROPIC_AWS", "CLAUDE_CODE_USE_ANTHROPIC_GOOGLE_CLOUD",
                  "CLAUDE_CODE_USE_MANTLE", "CLAUDE_CODE_USE_GATEWAY",
                  "CLAUDE_API_PARENT_SID", "CLAUDE_API_SPAWNER_SID"]
KEEP = "CLAUDE_SUB_TEST_KEEP"   # set beside them and never unset: proves the record sees what crosses
MISSING = object()
n = 0


def creds(sub_type):
    """A credentials file like claude's, the OAuth tokens included (fake ones)."""
    oauth = {"accessToken": FAKE_TOKEN, "refreshToken": FAKE_TOKEN + "-refresh",
             "expiresAt": 1790000000000, "scopes": ["user:inference", "user:profile"]}
    if sub_type is not MISSING:
        oauth["subscriptionType"] = sub_type
    return {"claudeAiOauth": oauth}


def run(content=None, *, raw=None, unreadable=False, default_dir=False, env_extra=None, home=None):
    """claude-sub 'probe' in a fresh throwaway HOME (`home`, when given, is one
    the caller made with fresh()). The config dir is
    CLAUDE_SUB_CONFIG_DIR=<tmp>/cfgN, or $HOME/.claude (the variable unset) with
    default_dir. Its .credentials.json holds `content` as JSON, or the text
    `raw`, or is a directory with unreadable, or is absent. An inherited
    XDG_CONFIG_HOME is dropped, like every CLAUDE* and ANTHROPIC* variable.
    Returns the result, the config dir and the fake claude's record (None when
    it never started)."""
    global n
    n += 1
    if home is None:
        home = os.path.join(TMP, "home%d" % n)
        os.makedirs(home)
    cfg = os.path.join(home, ".claude") if default_dir else os.path.join(TMP, "cfg%d" % n)
    os.makedirs(cfg, exist_ok=True)
    path = os.path.join(cfg, ".credentials.json")
    if content is not None:
        with open(path, "w") as f:
            json.dump(content, f)
    elif raw is not None:
        with open(path, "w") as f:
            f.write(raw)
    elif unreadable:
        os.makedirs(path)
    if os.path.exists(REC):
        os.remove(REC)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC")) and k != "XDG_CONFIG_HOME"}
    env.update({"HOME": home, "PATH": FAKE_BIN + os.pathsep + env.get("PATH", "")})
    if not default_dir:
        env["CLAUDE_SUB_CONFIG_DIR"] = cfg
    env.update(env_extra or {})
    r = subprocess.run(["bash", CLAUDE_SUB, "probe"], capture_output=True, text=True, env=env, timeout=60,
                       cwd=TMP, stdin=subprocess.DEVNULL)
    rec = open(REC).read() if os.path.exists(REC) else None
    return r, cfg, rec


def fresh(name):
    """A new empty directory under TMP."""
    global n
    n += 1
    path = os.path.join(TMP, "%s%d" % (name, n))
    os.makedirs(path)
    return path


def make_store(path, kind="dir"):
    """Something at `path`, where claude may look for an Anthropic profile store:
    a store directory whose default profile uses OIDC federation (fake data, no
    credentials), a plain file, or a dangling symlink. Returns `path`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if kind == "dir":
        os.makedirs(os.path.join(path, "configs"))
        with open(os.path.join(path, "configs", "default.json"), "w") as f:
            json.dump({"authentication": {"type": "oidc_federation"}}, f)
    elif kind == "file":
        with open(path, "w") as f:
            f.write("not a store\n")
    else:
        assert kind == "dangling", kind
        target = os.path.join(TMP, "no-such-store")
        assert not os.path.lexists(target), target
        os.symlink(target, path)
    return path


def parse(rec):
    """The fake claude's record → (argv, [CLAUDE_CONFIG_DIR], set of env names)."""
    lines = rec.splitlines()
    assert lines.count("CALL") == 1, "claude started %d times" % lines.count("CALL")
    return ([l[4:] for l in lines if l.startswith("ARG ")], [l[4:] for l in lines if l.startswith("CFG ")],
            {l[4:] for l in lines if l.startswith("ENV ")})


def refusal(cfg, detail, default_dir=False):
    login_cmd = "claude" if default_dir else "CLAUDE_CONFIG_DIR=%s claude" % cfg
    return ("claude-sub: refused. It needs Julian's personal claude.ai login (subscription type max or pro) "
            "in %s, but %s. Fix: in a devbox terminal run %s, type /login, choose the claude.ai subscription "
            "and sign in with the personal account.\n" % (cfg, detail, login_cmd))


def assert_ran(r, cfg, rec):
    assert rec is not None, "claude never started: rc %d, stderr %r" % (r.returncode, r.stderr)
    assert r.returncode == 0 and r.stdout == "FAKE_CLAUDE_RAN\n" and r.stderr == "", (r.returncode, r.stdout, r.stderr)
    argv, cfgs, names = parse(rec)
    assert argv == ["-p", "probe"], argv
    assert cfgs == [cfg], (cfgs, cfg)   # claude runs on the dir whose login was checked
    return names


def assert_refused(r, cfg, rec, detail, default_dir=False):
    out = r.stdout + r.stderr
    assert rec is None, "claude started on a refused login (rc %d)" % r.returncode
    assert r.returncode == 3, (r.returncode, out)
    assert r.stdout == "", out
    assert r.stderr == refusal(cfg, detail, default_dir), out
    assert "—" not in r.stderr, "an em dash in the refusal"
    assert FAKE_TOKEN not in out and "FAKEFAKE" not in out, out


def assert_store_refused(r, rec, store):
    out = r.stdout + r.stderr
    assert rec is None, "claude started beside a profile store (rc %d)" % r.returncode
    assert r.returncode == 3 and r.stdout == "", (r.returncode, out)
    assert r.stderr == ("claude-sub: refused. An Anthropic profile store exists at %s, and claude can run on a "
                        "profile from it instead of the subscription login, without saying so. Fix: move %s away "
                        "(claude-sub never reads it), or point XDG_CONFIG_HOME at a directory without an anthropic "
                        "store for this run.\n" % (store, store)), out
    assert "—" not in r.stderr, "an em dash in the refusal"


CASES = []


def case(label):
    def register(fn):
        CASES.append((label, fn))
        return fn
    return register


for sub_type in ("max", "pro"):
    @case("%s: claude starts once, with -p and the prompt, on the checked config dir" % sub_type)
    def _(sub_type=sub_type):
        r, cfg, rec = run(creds(sub_type))
        assert_ran(r, cfg, rec)


@case("max in the default config dir ($HOME/.claude): claude starts on that dir")
def _():
    r, cfg, rec = run(creds("max"), default_dir=True)
    assert_ran(r, cfg, rec)


NO_TYPE = "its .credentials.json has no claudeAiOauth.subscriptionType"
REFUSALS = [
    ("enterprise", dict(content=creds("enterprise")), 'its login is subscription type "enterprise"'),
    ("team", dict(content=creds("team")), 'its login is subscription type "team"'),
    ("an empty subscriptionType", dict(content=creds("")), NO_TYPE),
    ("no subscriptionType field", dict(content=creds(MISSING)), NO_TYPE),
    ("no claudeAiOauth object", dict(content={"mcpOAuth": {"srv": {"accessToken": FAKE_TOKEN}}}), NO_TYPE),
    ("no .credentials.json", dict(), "its .credentials.json does not exist"),
    ("malformed JSON (a cut-off file that names max)",
     dict(raw='{"claudeAiOauth": {"accessToken": "%s", "subscriptionType": "max"' % FAKE_TOKEN),
     "its .credentials.json is malformed"),
    ("JSON that is not an object", dict(raw=json.dumps([creds("max")])), "its .credentials.json is malformed"),
    ("a .credentials.json that cannot be read (a directory)", dict(unreadable=True),
     "its .credentials.json cannot be read"),
    ("a token where the type belongs", dict(content=creds(FAKE_TOKEN)),
     "its subscription type is not a plain name (value not shown)"),
    ("a type that is not a string", dict(content=creds(5)),
     "its subscription type is not a plain name (value not shown)"),
]
for label, kwargs, detail in REFUSALS:
    @case("%s: refused with exit 3 and the fix, claude never starts, no token shown" % label)
    def _(kwargs=kwargs, detail=detail):
        r, cfg, rec = run(**kwargs)
        assert_refused(r, cfg, rec, detail)


@case("enterprise in the default config dir: the fix is a plain `claude` and /login")
def _():
    r, cfg, rec = run(creds("enterprise"), default_dir=True)
    assert_refused(r, cfg, rec, 'its login is subscription type "enterprise"', default_dir=True)


for label, names in (("the calling session's variables", SESSION_VARS),
                     ("ANTHROPIC_UNIX_SOCKET, _FEDERATION_RULE_ID, _ORGANIZATION_ID and _PROFILE", NEW_AUTH_VARS),
                     ("the variables claude-sub already unset", OLD_UNSET_VARS)):
    @case("%s, set in the parent, are absent in claude" % label)
    def _(names=names):
        r, cfg, rec = run(creds("max"), env_extra={v: "1" for v in names + [KEEP]})
        seen = assert_ran(r, cfg, rec)
        assert KEEP in seen, "the record misses a variable that crosses"
        left = [v for v in names if v in seen]
        assert not left, "still set in claude: %s" % left


# The Anthropic profile store (claude 2.1.287, read from its binary on
# 2026-10-03): claude reads it at $ANTHROPIC_CONFIG_DIR, else
# $XDG_CONFIG_HOME/anthropic, else $HOME/.config/anthropic, and a profile there
# can replace the login without a word.
@case("ANTHROPIC_CONFIG_DIR, set in the parent to a profile store, is absent in claude, and claude starts")
def _():
    store = make_store(os.path.join(fresh("acd"), "anthropic"))
    r, cfg, rec = run(creds("max"), env_extra={"ANTHROPIC_CONFIG_DIR": store, KEEP: "1"})
    seen = assert_ran(r, cfg, rec)
    assert KEEP in seen, "the record misses a variable that crosses"
    assert "ANTHROPIC_CONFIG_DIR" not in seen, "ANTHROPIC_CONFIG_DIR still set in claude"


@case("XDG_CONFIG_HOME set, no store under it: claude starts, and XDG_CONFIG_HOME reaches claude")
def _():
    r, cfg, rec = run(creds("max"), env_extra={"XDG_CONFIG_HOME": fresh("xdg")})
    assert "XDG_CONFIG_HOME" in assert_ran(r, cfg, rec), "XDG_CONFIG_HOME did not reach claude"


@case("a store at $XDG_CONFIG_HOME/anthropic: refused with exit 3 and the fix, claude never starts")
def _():
    xdg = fresh("xdg")
    store = make_store(os.path.join(xdg, "anthropic"))
    r, cfg, rec = run(creds("max"), env_extra={"XDG_CONFIG_HOME": xdg})
    assert_store_refused(r, rec, store)


@case("whitespace around XDG_CONFIG_HOME: a store at the trimmed path is refused")
def _():
    xdg = fresh("xdg")
    store = make_store(os.path.join(xdg, "anthropic"))
    r, cfg, rec = run(creds("max"), env_extra={"XDG_CONFIG_HOME": " %s\t" % xdg})
    assert_store_refused(r, rec, store)


@case("XDG_CONFIG_HOME set, no store there, a store at $HOME/.config/anthropic: claude starts (it reads only the "
      "XDG path)")
def _():
    home = fresh("home")
    make_store(os.path.join(home, ".config", "anthropic"))
    r, cfg, rec = run(creds("max"), home=home, env_extra={"XDG_CONFIG_HOME": fresh("xdg")})
    assert_ran(r, cfg, rec)


HOME_STORES = [   # (label, XDG_CONFIG_HOME or None for unset, what is at $HOME/.config/anthropic)
    ("XDG_CONFIG_HOME unset, a store directory at $HOME/.config/anthropic", None, "dir"),
    ("XDG_CONFIG_HOME whitespace only, a store directory at $HOME/.config/anthropic", " \t ", "dir"),
    ("XDG_CONFIG_HOME unset, a plain file at $HOME/.config/anthropic", None, "file"),
    ("XDG_CONFIG_HOME unset, a dangling symlink at $HOME/.config/anthropic", None, "dangling"),
]
for label, xdg, kind in HOME_STORES:
    @case("%s: refused with exit 3 and the fix, claude never starts" % label)
    def _(xdg=xdg, kind=kind):
        home = fresh("home")
        store = make_store(os.path.join(home, ".config", "anthropic"), kind)
        r, cfg, rec = run(creds("max"), home=home, env_extra=None if xdg is None else {"XDG_CONFIG_HOME": xdg})
        assert_store_refused(r, rec, store)


failed = []
for label, fn in CASES:
    try:
        fn()
    except AssertionError as e:
        failed.append(label)
        print("FAIL  %s: %s" % (label, e))
    else:
        print("ok    %s" % label)
if failed:
    print("%d of %d claude-sub cases FAILED" % (len(failed), len(CASES)))
    sys.exit(1)
print("all %d claude-sub cases passed" % len(CASES))
