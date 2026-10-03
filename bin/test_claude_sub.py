#!/usr/bin/env python3
"""claude-sub starts claude only on Julian's personal claude.ai login: the
config dir's .credentials.json must record claudeAiOauth.subscriptionType max
or pro. Anything else (enterprise, team, an empty or missing type, a missing,
unreadable or malformed file, a type that is not a plain name) exits 3 with a
one-line fix on stderr, claude never starts, and no other part of the file
reaches stdout or stderr. It also exits 3 when anything (a directory, a file,
a dangling symlink) is at the Anthropic profile store path the child claude
reads: $XDG_CONFIG_HOME/anthropic, else $HOME/.config/anthropic, each
variable trimmed of surrounding whitespace, and when the config dir's
settings.json sets an apiKeyHelper or an env entry for a variable that
outranks the login, or cannot be read or parsed (no value from it is shown).
Before exec, claude-sub unsets every variable that outranks the login
(ANTHROPIC_CONFIG_DIR, which names the store, and CLAUDE_SECURESTORAGE_CONFIG_DIR,
also when empty, included; XDG_CONFIG_HOME stays) and the calling Claude Code
session's own variables. The config dir is $HOME/.claude-sub unless
CLAUDE_SUB_CONFIG_DIR names another; an inherited CLAUDE_CONFIG_DIR (every
fleet seat carries $HOME/.claude-api) is neither run on nor named in a fix,
and $HOME/.claude, the dir before 2026-10-03, is never read on its own.
claude gets --model sonnet before the caller's arguments unless they carry
their own --model. Check 16 of bin/selftest, cut out of the file and run
alone, passes beside a profile store of the caller's (at
$XDG_CONFIG_HOME/anthropic or $HOME/.config/anthropic) and shows claude-sub's
exit code and stderr when it fails.
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
import re
import shlex
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
# Four more in claude 2.1.288 (unset since 2026-10-03): the login's storage dir
# and host-supplied auth (reviewer f1979 [9], f1954 [2]).
HOST_VARS = ["CLAUDE_SECURESTORAGE_CONFIG_DIR", "CLAUDE_CODE_HOST_AUTH_ENV_VAR",
             "CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST", "CLAUDE_CODE_HOST_CREDS_FILE"]
# Every variable that outranks the login: the settings check refuses an env
# entry for any of them in the config dir's settings.json.
AUTH_VARS = [v for v in OLD_UNSET_VARS if not v.startswith("CLAUDE_API_")] + NEW_AUTH_VARS + \
    ["ANTHROPIC_CONFIG_DIR"] + HOST_VARS
KEEP = "CLAUDE_SUB_TEST_KEEP"   # set beside them and never unset: proves the record sees what crosses
MISSING = object()
DIRECTORY = object()   # run(settings=DIRECTORY): settings.json is a directory, so it cannot be read
n = 0


def creds(sub_type):
    """A credentials file like claude's, the OAuth tokens included (fake ones)."""
    oauth = {"accessToken": FAKE_TOKEN, "refreshToken": FAKE_TOKEN + "-refresh",
             "expiresAt": 1790000000000, "scopes": ["user:inference", "user:profile"]}
    if sub_type is not MISSING:
        oauth["subscriptionType"] = sub_type
    return {"claudeAiOauth": oauth}


def run(content=None, *, raw=None, unreadable=False, cfg_at="tmp", make_cfg=True, env_extra=None, home=None,
        args=(), settings=None):
    """claude-sub 'probe' <args> in a fresh throwaway HOME (`home`, when given,
    is one the caller made with fresh()). The config dir (cfg_at) is
    CLAUDE_SUB_CONFIG_DIR=<tmp>/cfgN ("tmp"), $HOME/.claude-sub with the
    variable unset ("default"), or CLAUDE_SUB_CONFIG_DIR=$HOME/.claude
    ("home_claude"); make_cfg=False leaves it uncreated. Its .credentials.json
    holds `content` as JSON, or the text `raw`, or is a directory with
    unreadable, or is absent. Its settings.json is absent (settings None),
    `settings` as JSON (a dict or list), the text `settings` (a str), or a
    directory (DIRECTORY). An inherited XDG_CONFIG_HOME is dropped, like
    every CLAUDE* and ANTHROPIC* variable. Returns the result, the config dir
    and the fake claude's record (None when it never started)."""
    global n
    n += 1
    if home is None:
        home = os.path.join(TMP, "home%d" % n)
        os.makedirs(home)
    cfg = {"tmp": os.path.join(TMP, "cfg%d" % n), "default": os.path.join(home, ".claude-sub"),
           "home_claude": os.path.join(home, ".claude")}[cfg_at]
    if make_cfg:
        os.makedirs(cfg, exist_ok=True)
    else:
        assert content is None and raw is None and not unreadable
        assert not os.path.lexists(cfg), cfg
    path = os.path.join(cfg, ".credentials.json")
    if content is not None:
        with open(path, "w") as f:
            json.dump(content, f)
    elif raw is not None:
        with open(path, "w") as f:
            f.write(raw)
    elif unreadable:
        os.makedirs(path)
    spath = os.path.join(cfg, "settings.json")
    if settings is DIRECTORY:
        os.makedirs(spath)
    elif isinstance(settings, str):
        with open(spath, "w") as f:
            f.write(settings)
    elif settings is not None:
        with open(spath, "w") as f:
            json.dump(settings, f)
    if os.path.exists(REC):
        os.remove(REC)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC")) and k != "XDG_CONFIG_HOME"}
    env.update({"HOME": home, "PATH": FAKE_BIN + os.pathsep + env.get("PATH", "")})
    if cfg_at != "default":
        env["CLAUDE_SUB_CONFIG_DIR"] = cfg
    env.update(env_extra or {})
    r = subprocess.run(["bash", CLAUDE_SUB, "probe", *args], capture_output=True, text=True, env=env, timeout=60,
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


def refusal(cfg, detail, plain_login=False):
    login_cmd = "claude" if plain_login else "CLAUDE_CONFIG_DIR=%s claude" % cfg
    return ("claude-sub: refused. It needs Julian's personal claude.ai login (subscription type max or pro) "
            "in %s, but %s. Fix: in a devbox terminal run %s, type /login, choose the claude.ai subscription "
            "and sign in with the personal account.\n" % (cfg, detail, login_cmd))


def assert_ran(r, cfg, rec, argv=("-p", "probe", "--model", "sonnet")):
    assert rec is not None, "claude never started: rc %d, stderr %r" % (r.returncode, r.stderr)
    assert r.returncode == 0 and r.stdout == "FAKE_CLAUDE_RAN\n" and r.stderr == "", (r.returncode, r.stdout, r.stderr)
    got, cfgs, names = parse(rec)
    assert got == list(argv), got
    assert cfgs == [cfg], (cfgs, cfg)   # claude runs on the dir whose login was checked
    return names


def assert_refused(r, cfg, rec, detail, plain_login=False):
    out = r.stdout + r.stderr
    assert rec is None, "claude started on a refused login (rc %d)" % r.returncode
    assert r.returncode == 3, (r.returncode, out)
    assert r.stdout == "", out
    assert r.stderr == refusal(cfg, detail, plain_login), out
    assert "—" not in r.stderr, "an em dash in the refusal"
    assert FAKE_TOKEN not in out and "FAKEFAKE" not in out, out


def assert_settings_refused(r, cfg, rec, detail, fix):
    out = r.stdout + r.stderr
    assert rec is None, "claude started beside a settings.json that outranks the login (rc %d)" % r.returncode
    assert r.returncode == 3 and r.stdout == "", (r.returncode, out)
    assert r.stderr == ("claude-sub: refused. Claude reads %s/settings.json, and %s. Fix: %s (claude-sub never "
                        "prints a value from it).\n" % (cfg, detail, fix)), out
    assert "\u2014" not in r.stderr, "an em dash in the refusal"
    assert FAKE_TOKEN not in out and "FAKE" not in out, out


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


@case("max in the default config dir ($HOME/.claude-sub): claude starts on that dir")
def _():
    r, cfg, rec = run(creds("max"), cfg_at="default")
    assert_ran(r, cfg, rec)


@case("max only in $HOME/.claude (the default dir before 2026-10-03), CLAUDE_SUB_CONFIG_DIR unset: refused, "
      "claude-sub checks only $HOME/.claude-sub")
def _():
    home = fresh("home")
    os.makedirs(os.path.join(home, ".claude"))
    with open(os.path.join(home, ".claude", ".credentials.json"), "w") as f:
        json.dump(creds("max"), f)
    r, cfg, rec = run(cfg_at="default", home=home)
    assert_refused(r, cfg, rec, "its .credentials.json does not exist")


@case("no $HOME/.claude-sub at all (never logged in): refused with the /login fix for that dir")
def _():
    r, cfg, rec = run(cfg_at="default", make_cfg=False)
    assert_refused(r, cfg, rec, "its .credentials.json does not exist")


# Every fleet seat runs with CLAUDE_CONFIG_DIR=~/.claude-api, the identity all
# workers share. claude-sub must neither run on it nor print a fix that logs
# the personal account into it (reviewer f1979 [6]).
def api_dir(home, sub_type=None):
    """$HOME/.claude-api like the fleet's: a settings.json with a fake
    apiKeyHelper, and a login of `sub_type` when given. Returns its path."""
    path = os.path.join(home, ".claude-api")
    os.makedirs(path)
    with open(os.path.join(path, "settings.json"), "w") as f:
        json.dump({"apiKeyHelper": "printf " + FAKE_TOKEN}, f)
    if sub_type is not None:
        with open(os.path.join(path, ".credentials.json"), "w") as f:
            json.dump(creds(sub_type), f)
    return path


@case("an inherited CLAUDE_CONFIG_DIR=$HOME/.claude-api, max in $HOME/.claude-sub: claude starts on "
      "$HOME/.claude-sub")
def _():
    home = fresh("home")
    r, cfg, rec = run(creds("max"), cfg_at="default", home=home, env_extra={"CLAUDE_CONFIG_DIR": api_dir(home)})
    assert_ran(r, cfg, rec)


@case("an inherited CLAUDE_CONFIG_DIR=$HOME/.claude-api holding a max login, no $HOME/.claude-sub: refused, and "
      "the fix names $HOME/.claude-sub, never $HOME/.claude-api")
def _():
    home = fresh("home")
    r, cfg, rec = run(cfg_at="default", make_cfg=False, home=home,
                      env_extra={"CLAUDE_CONFIG_DIR": api_dir(home, "max")})
    assert_refused(r, cfg, rec, "its .credentials.json does not exist")
    assert ".claude-api" not in r.stderr, r.stderr


@case("CLAUDE_SUB_CONFIG_DIR set beside an inherited CLAUDE_CONFIG_DIR (an enterprise login there): claude starts "
      "on CLAUDE_SUB_CONFIG_DIR")
def _():
    home = fresh("home")
    r, cfg, rec = run(creds("max"), home=home, env_extra={"CLAUDE_CONFIG_DIR": api_dir(home, "enterprise")})
    assert_ran(r, cfg, rec)


MODEL_CASES = [   # (label, the caller's arguments after the prompt, claude's argv)
    ("no --model from the caller: --model sonnet goes before the caller's arguments",
     ("--allowedTools", "mcp__claude_ai_Todoist__find-tasks"),
     ["-p", "probe", "--model", "sonnet", "--allowedTools", "mcp__claude_ai_Todoist__find-tasks"]),
    ("--model opus from the caller: claude gets only the caller's model",
     ("--model", "opus"), ["-p", "probe", "--model", "opus"]),
    ("--model=claude-opus-5-5 from the caller: claude gets only that",
     ("--model=claude-opus-5-5",), ["-p", "probe", "--model=claude-opus-5-5"]),
    ("--model after other arguments: claude gets only the caller's model",
     ("--allowedTools", "x", "--model", "haiku"), ["-p", "probe", "--allowedTools", "x", "--model", "haiku"]),
]
for label, args, argv in MODEL_CASES:
    @case(label)
    def _(args=args, argv=argv):
        r, cfg, rec = run(creds("max"), args=args)
        assert_ran(r, cfg, rec, argv)


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


@case("enterprise in the default config dir: the fix names CLAUDE_CONFIG_DIR=$HOME/.claude-sub")
def _():
    r, cfg, rec = run(creds("enterprise"), cfg_at="default")
    assert_refused(r, cfg, rec, 'its login is subscription type "enterprise"')


@case("CLAUDE_SUB_CONFIG_DIR=$HOME/.claude with an enterprise login: the fix is a plain `claude` and /login")
def _():
    r, cfg, rec = run(creds("enterprise"), cfg_at="home_claude")
    assert_refused(r, cfg, rec, 'its login is subscription type "enterprise"', plain_login=True)


for label, names in (("the calling session's variables", SESSION_VARS),
                     ("ANTHROPIC_UNIX_SOCKET, _FEDERATION_RULE_ID, _ORGANIZATION_ID and _PROFILE", NEW_AUTH_VARS),
                     ("CLAUDE_SECURESTORAGE_CONFIG_DIR and the host-auth variables", HOST_VARS),
                     ("the variables claude-sub already unset", OLD_UNSET_VARS)):
    @case("%s, set in the parent, are absent in claude" % label)
    def _(names=names):
        r, cfg, rec = run(creds("max"), env_extra={v: "1" for v in names + [KEEP]})
        seen = assert_ran(r, cfg, rec)
        assert KEEP in seen, "the record misses a variable that crosses"
        left = [v for v in names if v in seen]
        assert not left, "still set in claude: %s" % left


# claude 2.1.288 reads its login from CLAUDE_SECURESTORAGE_CONFIG_DIR when the
# variable is defined, and from ~/.claude (Julian's Enterprise login) when it is
# empty, so the empty value must go too (reviewer f1979 [9]).
@case("CLAUDE_SECURESTORAGE_CONFIG_DIR set empty in the parent is absent in claude, and claude starts")
def _():
    r, cfg, rec = run(creds("max"), env_extra={"CLAUDE_SECURESTORAGE_CONFIG_DIR": "", KEEP: "1"})
    seen = assert_ran(r, cfg, rec)
    assert KEEP in seen, "the record misses a variable that crosses"
    assert "CLAUDE_SECURESTORAGE_CONFIG_DIR" not in seen, "CLAUDE_SECURESTORAGE_CONFIG_DIR still set in claude"


# The config dir's settings.json: an apiKeyHelper there, or an env entry for a
# variable that outranks the login, would win over the login it checked
# (reviewer f1954 [3], f1979 [10]). Values are fake tokens; none may show.
SETS = "which claude would use instead of the subscription login"
UNKNOWN = "so claude-sub cannot tell whether it sets an apiKeyHelper or an auth variable"
SETTINGS_REFUSALS = [   # (label, settings, detail, fix)
    ("an apiKeyHelper", {"apiKeyHelper": "printf " + FAKE_TOKEN}, "it sets apiKeyHelper, " + SETS,
     "remove those keys from it"),
    ("an env block with ANTHROPIC_API_KEY beside an unrelated entry",
     {"env": {"ANTHROPIC_API_KEY": FAKE_TOKEN, "FOO": "1"}}, "it sets env.ANTHROPIC_API_KEY, " + SETS,
     "remove those keys from it"),
    ("an apiKeyHelper and an env block with CLAUDE_SECURESTORAGE_CONFIG_DIR set empty",
     {"apiKeyHelper": "x", "env": {"CLAUDE_SECURESTORAGE_CONFIG_DIR": ""}},
     "it sets apiKeyHelper, env.CLAUDE_SECURESTORAGE_CONFIG_DIR, " + SETS, "remove those keys from it"),
    ("an env block naming every variable claude-sub unsets as outranking the login",
     {"env": {v: FAKE_TOKEN for v in AUTH_VARS}},
     "it sets %s, %s" % (", ".join("env." + v for v in sorted(AUTH_VARS)), SETS), "remove those keys from it"),
    ("malformed JSON (a cut-off file)", '{"apiKeyHelper": "printf %s' % FAKE_TOKEN,
     "it is not a JSON object with an object as env, " + UNKNOWN, "repair it"),
    ("JSON that is not an object", [{"apiKeyHelper": "x"}], "it is not a JSON object with an object as env, " + UNKNOWN,
     "repair it"),
    ("an env that is not an object", {"env": ["ANTHROPIC_API_KEY=" + FAKE_TOKEN]},
     "it is not a JSON object with an object as env, " + UNKNOWN, "repair it"),
    ("a directory in place of the file", DIRECTORY, "it cannot be read, " + UNKNOWN,
     "make it a readable file"),
]
for label, settings, detail, fix in SETTINGS_REFUSALS:
    @case("max login, settings.json with %s: refused with exit 3 and the fix, claude never starts, no value shown"
          % label)
    def _(settings=settings, detail=detail, fix=fix):
        r, cfg, rec = run(creds("max"), settings=settings)
        assert_settings_refused(r, cfg, rec, detail, fix)


@case("max login, settings.json with an empty apiKeyHelper, a model and env entries that outrank nothing: "
      "claude starts")
def _():
    r, cfg, rec = run(creds("max"), settings={"apiKeyHelper": "", "model": "opus",
                                               "env": {"FOO": "1", "ANTHROPIC_MODEL": "claude-sonnet-5"}})
    assert_ran(r, cfg, rec)


@case("the default config dir's settings.json with an apiKeyHelper: refused, naming $HOME/.claude-sub")
def _():
    r, cfg, rec = run(creds("max"), cfg_at="default", settings={"apiKeyHelper": "printf " + FAKE_TOKEN})
    assert_settings_refused(r, cfg, rec, "it sets apiKeyHelper, " + SETS, "remove those keys from it")


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


# selftest's check 16 runs claude-sub against a stub claude. It used to inherit
# the caller's HOME and XDG_CONFIG_HOME, so a store of the caller's failed it as
# "claude-sub passed through: ''", the reason left in a file (reviewer r1965
# [18]). selftest as a whole reads the caller's real fleet.conf, so these cases
# cut the check out of bin/selftest (its step line up to the next step line)
# and run it alone with selftest's own step/ok/bad helpers, in a throwaway
# work dir and HOME.
SELFTEST = os.path.join(HERE, "selftest")


def selftest_check16(bin_dir, home, xdg=None):
    """The claude-sub check of bin/selftest, alone, with claude-sub from
    bin_dir, the caller's HOME `home` and XDG_CONFIG_HOME `xdg` (None: unset).
    Returns the result."""
    with open(SELFTEST) as f:
        lines = f.read().splitlines(keepends=True)
    steps = [i for i, l in enumerate(lines) if l.startswith('step "')]
    start = [i for i in steps if "claude-sub" in lines[i]]
    assert len(start) == 1, "selftest has %d claude-sub checks" % len(start)
    end = [i for i in steps if i > start[0]]
    assert end, "no step after the claude-sub check"
    helpers = [l for l in lines if re.match(r"(step|ok|bad)\(\) ", l)]
    assert len(helpers) == 3, helpers
    work = fresh("work")
    script = ("set -uo pipefail\nfails=0\nWORK=%s\nBIN_DIR=%s\n" % (shlex.quote(work), shlex.quote(bin_dir))
              + "".join(helpers) + 'cd "$WORK" || exit 99\n' + "".join(lines[start[0]:end[0]])
              + '[ "$fails" -eq 0 ]\n')
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("CLAUDE", "ANTHROPIC")) and k != "XDG_CONFIG_HOME"}
    env["HOME"] = home
    if xdg is not None:
        env["XDG_CONFIG_HOME"] = xdg
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env=env, timeout=60, cwd=work,
                          stdin=subprocess.DEVNULL)


CALLER_STORES = [   # (label, store under XDG_CONFIG_HOME rather than HOME)
    ("a store at the caller's $XDG_CONFIG_HOME/anthropic", True),
    ("a store at the caller's $HOME/.config/anthropic, XDG_CONFIG_HOME unset", False),
]
for label, under_xdg in CALLER_STORES:
    @case("selftest check 16 beside %s: PASS (it runs in its own HOME, XDG_CONFIG_HOME unset)" % label)
    def _(under_xdg=under_xdg):
        home, xdg = fresh("home"), fresh("xdg") if under_xdg else None
        make_store(os.path.join(xdg, "anthropic") if under_xdg else os.path.join(home, ".config", "anthropic"))
        r = selftest_check16(HERE, home, xdg)
        assert r.returncode == 0 and "   PASS\n" in r.stdout and "FAIL" not in r.stdout, (r.returncode, r.stdout,
                                                                                       r.stderr)


@case("selftest check 16 when claude-sub fails: the FAIL line carries its exit code and stderr")
def _():
    stub_dir = fresh("stubbin")
    with open(os.path.join(stub_dir, "claude-sub"), "w") as f:
        f.write("#!/usr/bin/env bash\necho 'claude-sub: refused. STUB REASON' >&2\necho 'second line' >&2\nexit 3\n")
    os.chmod(os.path.join(stub_dir, "claude-sub"), 0o755)
    r = selftest_check16(stub_dir, fresh("home"))
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert ("   FAIL: claude-sub (exit 3) passed through: ''; its stderr: claude-sub: refused. STUB REASON "
            "second line \n") in r.stdout, r.stdout


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
