#!/usr/bin/env python3
r"""token-onboard.py — one flow for every "go get a free token" service.

The operator pasted a live GitHub PAT into a chat window because the instructions ended
at "copy the token" and left the last mile to improvisation. That is a process defect, not
a user error: any flow whose safe path depends on the human remembering an extra step will
leak eventually. This engine is the flow.

  1. request  — print the exact steps for ONE provider and arm the drop file
  2. (human)  — paste the token into _secrets/token-inbox.txt and save. Nothing else.
  3. ingest   — install it into the tool's own credential store, VERIFY, record masked,
                and wipe the drop file
  4. exec     — run any command with the credential injected from the vault

Invariants, in priority order. Every one of these is a thing that already went wrong:

  A. The value never reaches an agent context. Not printed, not returned, not logged.
  B. The value never reaches argv. On Windows any same-user process can read another's
     command line, and shells persist history. Secrets travel by stdin or by vault.
  C. The value never survives on disk outside the vault / the tool's own store. The drop
     file is wiped in a finally block; a wipe that fails is a LOUD failure, not a warning.
  D. Install is never reported as success without a passing verify command.
  E. Recipes are data (_registry/token-onboard.json), so a new provider is an edit, not a
     code change. That file is the operator's back door.

  python token-onboard.py list
  python token-onboard.py request cloudflare
  python token-onboard.py ingest
  python token-onboard.py verify [provider]
  python token-onboard.py exec cloudflare -- npx wrangler whoami
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from _atomicio import atomic_write  # noqa: E402  (needs HERE on sys.path first)

WS = os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace"
RECIPES = os.path.join(WS, "_registry", "token-onboard.json")
INVENTORY = os.path.join(WS, "_registry", "auth-inventory.json")
SECRETS = os.path.join(WS, "_secrets")
DROP = os.path.join(SECRETS, "token-inbox.txt")
LEDGER = os.path.join(SECRETS, "token-inbox.txt.done")

NO_WINDOW = 0x08000000 if os.name == "nt" else 0

HEADER = """\
# token-inbox -- paste ONE token per line, then SAVE. Nothing else to do.
# Format:  <provider> <token> [--account-id <id>]
# Example: cloudflare cf_xxxxxxxxxxxxxxxxxxxx --account-id 1234abcd
#
# NEVER paste a token into a chat window, a terminal command, or a commit.
# This file is gitignored, is wiped the moment it is ingested, and keeps only a
# masked record in token-inbox.txt.done.
#
# Which provider? ->  python %AI_WORKSPACE%\\_skill\\engines\\token-onboard.py list
# Lines starting with # are ignored.
"""


def _mask(tok):
    """Never the whole value. Enough to recognise, never enough to use."""
    if not tok:
        return "***"
    return (tok[:4] + "…" + tok[-3:]) if len(tok) > 12 else "***"


def _load(path, default):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh), ""
    except FileNotFoundError:
        return default, ""
    except (OSError, json.JSONDecodeError) as exc:
        return None, "cannot read %s (%s)" % (path, exc)


def recipes():
    doc, err = _load(RECIPES, None)
    if err:
        return None, err
    if doc is None:
        return None, ("%s is missing. It holds the per-provider steps; without it this "
                      "engine cannot tell you where to get a token or how to install it."
                      % RECIPES)
    provs = doc.get("providers")
    if not isinstance(provs, dict) or not provs:
        return None, "%s has no 'providers' object" % RECIPES
    return provs, ""


def _run(argv, stdin_text=None, timeout=120):
    """Run a command, optionally feeding a secret on stdin. Returns (rc, combined_output).

    stdin_text is the ONLY channel a secret may take into a subprocess. It is never
    interpolated into argv, so it cannot appear in a process listing or a shell history.
    """
    try:
        p = subprocess.run(argv, input=stdin_text, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout,
                           creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "%s: %s" % (type(exc).__name__, exc)
    return p.returncode, ((p.stdout or "") + (p.stderr or ""))


def _scrub(text, secret):
    """Last line of defence before any subprocess output is shown.

    A tool that echoes the token it was handed would otherwise print it straight into the
    agent's context through our own reporting path. Cheap, and the one time it matters is
    the time nothing else caught it.
    """
    if not secret or not text:
        return text
    return text.replace(secret, "[REDACTED]")


def cmd_list(args):
    provs, err = recipes()
    if err:
        print("TOKEN-ONBOARD CONFIG ERROR: %s" % err)
        return 2
    print("%-13s %-10s %-44s %s" % ("provider", "state", "get a token at", "scopes"))
    for name in sorted(provs):
        r = provs[name]
        state, _ = verify_one(name, r)
        print("%-13s %-10s %-44s %s"
              % (name, state, r.get("token_url", "?"),
                 ", ".join(r.get("scopes") or []) or "-"))
    print("\nTo add one:  python token-onboard.py request <provider>")
    return 0


def arm_drop(note="", keep=None):
    """Rewrite the drop file as header + note + `keep` lines.

    `keep` is how the plaintext gets destroyed without destroying anything irreplaceable:
    a line is dropped once its token exists somewhere else (a vault entry, a tool's
    credential store, the key matrix), and kept when it does not. Unconditionally
    truncating was a real defect — a token that failed to install, or that was still
    pending when the next `request` ran, was gone with no backup and no warning, and the
    operator had to go back to the provider and issue a new one.
    """
    os.makedirs(SECRETS, exist_ok=True)
    parts = [HEADER]
    if note:
        parts.append("#\n" + "".join("# %s\n" % ln for ln in note.splitlines()))
    if keep:
        parts.append("#\n# KEPT: these were NOT stored anywhere, so they are still only\n"
                     "# here. Fix the cause and re-run ingest, or delete them yourself.\n")
        parts.extend(ln.rstrip("\n") + "\n" for ln in keep)
    # Atomic: a truncate-then-write would destroy a kept token if the write failed halfway,
    # which is precisely the token this rewrite exists to preserve.
    atomic_write(DROP, "".join(parts))


def cmd_request(args):
    provs, err = recipes()
    if err:
        print("TOKEN-ONBOARD CONFIG ERROR: %s" % err)
        return 2
    name = args.provider.lower()
    r = provs.get(name)
    if not r:
        print("unknown provider %r. Known: %s" % (name, ", ".join(sorted(provs))))
        return 2
    scopes = ", ".join(r.get("scopes") or []) or "(none required)"
    steps = [
        "1. Open  %s" % r.get("token_url", "?"),
        "2. Create a token. Tick exactly: %s" % scopes,
        "3. Set expiry to the longest available — a token that expires is a task that",
        "   comes back. %s" % (r.get("expiry_note") or ""),
        "4. Copy it, then paste ONE line into:",
        "     %s" % DROP,
        "   like:  %s <token>%s" % (name, " --account-id <id>" if r.get("needs_account_id") else ""),
        "5. Save the file and tell me. Nothing else — I take it from there.",
    ]
    print("\n== %s ==" % name)
    for s in steps:
        if s.strip():
            print("  " + s)
    print("\n  DO NOT paste the token into chat, into a terminal command, or into a commit.")
    print("  This file is gitignored, and each line is wiped as soon as its token is stored.")
    # Arming must never destroy a token the operator already pasted but has not ingested —
    # asking for a Cloudflare token would otherwise silently shred a pending Fly one.
    pending = []
    if os.path.exists(DROP):
        try:
            with open(DROP, encoding="utf-8-sig") as fh:
                pending = [ln.rstrip("\n") for ln in fh
                           if ln.strip() and not ln.strip().startswith("#")]
        except OSError as exc:
            # Cannot read it, so cannot know what is in it. Arming anyway would replace a
            # file that may hold the only copy of a token — "unreadable" is not "empty".
            print("\n  REFUSING to arm: %s exists but cannot be read (%s).\n"
                  "  It may hold a token that exists nowhere else. Fix the permissions or\n"
                  "  move the file aside yourself, then run this again." % (DROP, exc))
            return 2
    arm_drop("waiting for: %s\nfrom: %s\nscopes: %s"
             % (name, r.get("token_url", "?"), scopes), keep=pending)
    print("\n  drop file armed: %s" % DROP)
    if pending:
        print("  (kept %d line(s) already waiting there — run `ingest` to store them)"
              % len(pending))
    return 0


def verify_one(name, recipe, token=None):
    """(state, detail). Pass `token` to judge THAT credential rather than a stored one.

    state is one of:

      OK        the credential is installed AND the provider accepted it
      MISSING   no credential, or the provider actually rejected it
      BLOCKED   bot-mitigation refused our client; the token was never judged
      QUOTA     provider identified the account but it has no credits/quota/license
      ACCOUNT   provider identified an account/org restriction; key churn will not fix it
      NO-TOOL   the provider's CLI is not installed on this machine
      NO-VERIFY unreachable, or the recipe declares no way to prove anything

    These are deliberately five states and not a bool. "flyctl is not installed", "groq's
    Cloudflare edge blocked our TLS fingerprint", and "the token is dead" call for
    completely different next actions; collapsing them sends the operator to go create a
    replacement token that will fail in exactly the same way.
    """
    vh = recipe.get("verify_http")
    def resolve():
        """(token, state, detail) — the credential to judge, or why we cannot judge one.

        `token` is passed in by the ingest path and is authoritative there. Looking the
        value back up instead would verify *a* stored credential, not *this* one: the key
        matrix keeps several keys per provider, so onboarding a dead groq key on top of a
        live one would re-verify the live one and stamp the dead one "verified".
        """
        if token is not None:
            return token, "", ""
        tok, verr = vault_get(recipe)
        if verr:
            return None, "NO-VERIFY", "%s — the token was NOT judged" % verr
        if tok:
            return tok, "", ""
        tok, serr = stored_token(name, recipe)
        if serr:
            return None, "NO-VERIFY", "%s — the token was NOT judged" % serr
        if not tok:
            return None, "MISSING", "no stored credential to verify"
        return tok, "", ""

    v = recipe.get("verify")
    is_cli = recipe.get("kind") == "cli"

    if vh and not (is_cli and token is None):
        # Preferred: most token services expose an identity endpoint, and an in-process
        # request keeps the secret out of argv entirely — no CLI needed, which is what
        # makes this flow work for a service that ships no CLI at all.
        #
        # For kind=cli this is the ONLY way to judge the token itself. Once handed to `gh`
        # we deliberately stop holding it, so afterwards all we can ask is whether the tool
        # reports itself authenticated — which it would also answer yes to if the install
        # had quietly left an older account active. During ingest we still have the value,
        # so we ask the provider about that exact token and keep the claim true.
        tok, state, detail = resolve()
        if state:
            return state, detail
        return _verify_http(vh, tok)

    if not v:
        return "NO-VERIFY", ("recipe defines no verify command, so an install here can "
                             "never be confirmed")
    if recipe.get("env"):
        # Vault-backed credentials live in no tool store, so verifying needs the same
        # injection exec does.
        tok, state, detail = resolve()
        if state:
            return state, detail
        rc, out = _exec_with_env(recipe, v, tok)
    else:
        rc, out = _run(v, timeout=recipe.get("verify_timeout", 60))
    if rc == 127:
        return "NO-TOOL", (out or "")[-300:]
    if rc != 0:
        return "MISSING", (out or "")[-400:]
    # Say exactly what was proved. With no token in hand this asked the TOOL, not the
    # provider, so it cannot distinguish the credential we installed from an older one the
    # tool may still consider active.
    scope = ("" if not is_cli else
             " [tool reports authenticated; this does not identify WHICH credential]")
    return "OK", ((out or "")[-400:] + scope)


# Cloudflare bot-mitigation codes. A response carrying one of these was rejected because
# of OUR TLS fingerprint, not because of the credential — urllib's ClientHello does not look
# like a browser's. Reporting these as a bad token sends the operator to create a
# replacement that will be blocked in exactly the same way.
# see %AI_WORKSPACE%\_skill\technique_output\70-pitfalls\cloudflare-ja3-fingerprinting.md
CF_BLOCK = ("error code: 1010", "error code: 1015", "error code: 1020",
            "error code: 1012", "Just a moment...")
# cf-mitigated is a RESPONSE HEADER, not body text. Cloudflare can serve a challenge with a
# 403 and a body containing none of the strings above, so searching only the body reports a
# perfectly good token as rejected.
CF_BLOCK_HEADERS = ("cf-mitigated",)


def _looks_blocked(code, body, headers=None):
    if code not in (403, 429, 503):
        return False
    if any(s in (body or "") for s in CF_BLOCK):
        return True
    for k in (headers or {}):
        if str(k).lower() in CF_BLOCK_HEADERS:
            return True
    return False


def _curl_http(spec, token, url, headers):
    """Same request, through curl's browser-shaped TLS. (code, body, resp_headers) or
    (None, why, {}).

    curl reads its options from STDIN via `-K -`, so the Authorization header — and the
    token inside it — never becomes a command-line argument. Response headers are dumped
    with `-D` because the block signal we care about most, cf-mitigated, is a header and
    never appears in the body at all.
    """
    import shutil
    import tempfile
    curl = shutil.which("curl")
    if not curl:
        return None, "curl unavailable", {}
    fd, hdr_path = tempfile.mkstemp(prefix="curlhdr-")
    os.close(fd)
    cfg = ['url = "%s"' % url.replace("\\", "\\\\").replace('"', '\\"'),
           "silent", "show-error", "location", "max-time = 30",
           'user-agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0"',
           'dump-header = "%s"' % hdr_path.replace("\\", "\\\\"),
           'write-out = "\\n<<<%{http_code}"']
    if spec.get("method", "GET") != "GET":
        cfg.append('request = "%s"' % spec["method"])
    for k, v in headers.items():
        cfg.append('header = "%s"' % ("%s: %s" % (k, v)).replace("\\", "\\\\").replace('"', '\\"'))
    try:
        rc, out = _run([curl, "-K", "-"], stdin_text="\n".join(cfg) + "\n", timeout=45)
        resp_headers = {}
        try:
            with open(hdr_path, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    if ":" in ln:
                        k, _, v = ln.partition(":")
                        resp_headers[k.strip().lower()] = v.strip()
        except OSError:
            pass
    finally:
        try:
            os.unlink(hdr_path)
        except OSError:
            pass
    if rc != 0:
        return None, "curl rc=%s %s" % (rc, _scrub(out, token)[:160]), {}
    body, _, tail = out.rpartition("<<<")
    try:
        return int(tail.strip()), body, resp_headers
    except ValueError:
        return None, "curl gave no status line", {}


def _verify_http(spec, token):
    """Ask the provider itself whether the token is good. (state, detail).

    The token goes into a request header built in memory. It is never an argument, never a
    file, and never in the returned detail — the response body is scrubbed before it can
    reach a report, because some APIs echo the credential back in an error object.
    """
    import urllib.error
    import urllib.request
    url = spec.get("url")
    if not url:
        return "NO-VERIFY", "verify_http has no url"
    headers = {}
    for k, v in (spec.get("headers") or {"Authorization": "Bearer {token}"}).items():
        headers[k] = v.replace("{token}", token)

    code = body = None
    resp_headers = {}
    try:
        req = urllib.request.Request(url, headers=headers, method=spec.get("method", "GET"))
        with urllib.request.urlopen(req, timeout=spec.get("timeout", 30)) as resp:
            body, code = resp.read(4096).decode("utf-8", "replace"), resp.status
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as exc:
        body = exc.read(4096).decode("utf-8", "replace") if exc.fp else ""
        code = exc.code
        try:
            resp_headers = {k.lower(): v for k, v in (exc.headers or {}).items()}
        except Exception:  # noqa: BLE001
            resp_headers = {}
    except (urllib.error.URLError, OSError):
        pass  # includes SSLError; curl gets a turn before we conclude anything

    if code is None or _looks_blocked(code, body, resp_headers):
        # Second opinion through a browser-shaped TLS stack. Only its answer is conclusive.
        c2, b2, h2 = _curl_http(spec, token, url, headers)
        if c2 is None:
            return "NO-VERIFY", ("cannot reach %s — %s. This is NOT evidence the token is "
                                 "bad." % (url, b2))
        code, body, resp_headers = c2, b2, h2
        if _looks_blocked(code, body, resp_headers):
            return "BLOCKED", ("HTTP %s bot-mitigation from %s even via curl. The token was "
                               "never checked; do not replace it on this basis." % (code, url))

    body = _scrub(body or "", token)
    want = spec.get("expect_status", 200)
    if code != want:
        low = body.lower()
        if any(term in low for term in ("credits", "quota", "billing", "license", "licenses")):
            return "QUOTA", ("HTTP %s: provider accepted the account context but reports "
                             "no quota/credits/license" % code)
        if "restricted" in low or "permission-denied" in low:
            return "ACCOUNT", "HTTP %s: provider reports an account/org permission restriction" % code
        return "MISSING", "HTTP %s (wanted %s): %s" % (code, want, body[:200])
    need = spec.get("expect_body")
    if need and need not in body:
        return "MISSING", "HTTP %s but body lacks %r: %s" % (code, need, body[:200])
    return "OK", "HTTP %s" % code


def stored_token(name, recipe):
    """(token, err) for providers whose store is not the vault. Both may be falsy.

    err is non-empty only when the store itself could not be read. "the matrix is corrupt"
    and "this provider has no key" are different problems with different fixes, and the
    first must never be reported as the second — same reason BLOCKED is not MISSING.

    Returns (None, "") for kind=cli by design: the point of handing a token to `gh` is that
    we stop holding it, so a CLI provider is verified by its own status command.
    """
    if recipe.get("kind") in POOL_KINDS:
        try:
            from _paths import API_MATRIX
            with open(API_MATRIX, encoding="utf-8-sig") as fh:
                m = json.load(fh)
        except (OSError, ValueError, ImportError) as exc:
            return None, "key matrix unreadable (%s)" % type(exc).__name__
        for k in m.get("keys", []):
            if k.get("provider") == name and k.get("key"):
                return k["key"], ""
    return None, ""


def vault_path(recipe):
    return recipe.get("vault_path") or ""


# Kinds whose credentials live in the shared key matrix rather than the vault: several
# keys per provider, each tagged with an account id. `stt` is storage-identical to `llm`
# and differs only in what the key is *called for*, which verify_http already expresses —
# so it must not get its own storage path. Before this existed, deepgram parsed fine and
# then died at install with "unknown kind 'stt'", which reads like a bad paste but is a
# gap in this file.
POOL_KINDS = ("llm", "stt")


def vault_get(recipe):
    """(value, err). err is non-empty only when the vault could not be read at all.

    An unreadable vault is not an empty vault. Collapsing the two would report a perfectly
    good credential as MISSING and send the operator to replace it — the same mistake as
    reporting a bot-mitigation block as a bad token.
    """
    p = vault_path(recipe)
    if not p:
        return None, ""
    try:
        import _secrets
        return _secrets.get(p), ""
    except Exception as exc:  # noqa: BLE001
        return None, "vault unreadable (%s)" % type(exc).__name__


def vault_set(recipe, value):
    p = vault_path(recipe)
    if not p:
        return False, "no vault_path in recipe"
    try:
        import _secrets
        _secrets.set(p, value)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, exc)


def _exec_with_env(recipe, argv, token, extra=None):
    """Run argv with the credential in the ENVIRONMENT of the child only.

    Not exported to the machine or the user profile: a permanent env-var change needs
    operator authorization (hub rule), and a process-scoped variable achieves the same
    thing for the one command that needs it.
    """
    env = dict(os.environ)
    env[recipe["env"]] = token
    for k, v in (extra or {}).items():
        env[k] = v
    try:
        p = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=recipe.get("verify_timeout", 120),
                           env=env, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "%s: %s" % (type(exc).__name__, exc)
    return p.returncode, _scrub((p.stdout or "") + (p.stderr or ""), token)


def install_one(name, recipe, token, account_id=None):
    """Install a token into wherever that provider keeps credentials. (ok, note)."""
    kind = recipe.get("kind")
    if kind == "cli":
        argv = list(recipe.get("install") or [])
        if not argv:
            return False, "recipe has kind=cli but no install command"
        rc, out = _run(argv, stdin_text=token, timeout=recipe.get("install_timeout", 120))
        if rc != 0:
            return False, _scrub(out[-400:], token)
        return True, ""
    if kind == "env":
        if not recipe.get("env") or not vault_path(recipe):
            return False, "recipe has kind=env but no env / vault_path"
        # Order matters. The account id is written FIRST because it is the step that can
        # fail without having destroyed anything; writing the token first and then failing
        # here would leave the previous working credential overwritten while the function
        # reports failure — the operator is told nothing happened, and the old token is gone.
        #
        # The two values are a PAIR, though: a Cloudflare account id addresses the account
        # the token belongs to. So the account id is rolled back if the token write then
        # fails, otherwise a reported failure would still leave a new id bound to the old
        # token — a combination that never existed and that nothing else would detect.
        prior_account, wrote_account = None, False
        if account_id and recipe.get("account_vault_path"):
            try:
                import _secrets
                prior_account = _secrets.get(recipe["account_vault_path"])
                _secrets.set(recipe["account_vault_path"], account_id)
                wrote_account = True
            except Exception as exc:  # noqa: BLE001
                return False, "account id not stored (token left untouched): %s" % exc
        ok, err = vault_set(recipe, token)
        if not ok:
            if wrote_account:
                try:
                    import _secrets
                    _secrets.set(recipe["account_vault_path"], prior_account)
                except Exception as exc2:  # noqa: BLE001
                    return False, ("%s; AND the account id could not be rolled back (%s) — "
                                   "it now points at the new account while the token is "
                                   "still the old one" % (err, exc2))
            return False, err
        return True, ""
    if kind in POOL_KINDS:
        # Delegate to the existing pool onboarder, but via stdin so the key never lands in
        # argv the way `key-onboard.py <provider> <key>` puts it there.
        argv = [sys.executable, os.path.join(HERE, "key-onboard.py"), name,
                "--key-stdin", "--no-validate"]
        if account_id:
            argv += ["--account-id", account_id]
        rc, out = _run(argv, stdin_text=token, timeout=180)
        if rc != 0:
            return False, _scrub(out[-400:], token)
        return True, ""
    return False, "unknown kind %r" % kind


def _already_stored(name, recipe, token):
    """Did this exact token reach a durable store, whatever the installer reported?

    Only ever used to AVOID keeping a redundant plaintext line, never to claim an install
    succeeded. Answering "no" is always safe (the line is kept and can be retried, since
    both installers upsert by value); answering "yes" wrongly would delete the last copy,
    so every failure path here deliberately returns False.
    """
    try:
        if recipe.get("kind") == "env":
            cur, err = vault_get(recipe)
            return (not err) and cur == token
        if recipe.get("kind") in POOL_KINDS:
            from _paths import API_MATRIX
            with open(API_MATRIX, encoding="utf-8-sig") as fh:
                m = json.load(fh)
            return any(k.get("provider") == name and k.get("key") == token
                       for k in m.get("keys", []))
    except Exception:  # noqa: BLE001
        return False
    # kind=cli keeps no readable copy by design, so this question cannot be answered.
    return False


def _parse_line(ln):
    """(provider, token, account_id, err). Flags are pulled out before positionals."""
    parts = ln.split()
    account = None
    if "--account-id" in parts:
        i = parts.index("--account-id")
        if i + 1 >= len(parts):
            return None, None, None, "--account-id with no value"
        account = parts[i + 1]
        del parts[i:i + 2]
    if len(parts) < 2:
        return None, None, None, "need '<provider> <token>'"
    if len(parts) > 2:
        return None, None, None, ("unexpected extra words — a token must not contain "
                                  "spaces; check you pasted only the token")
    return parts[0].lower(), parts[1], account, ""


def read_clipboard():
    """(text, err). Windows clipboard, read in-process so the value is never printed."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None, "ctypes unavailable"
    CF_UNICODETEXT = 13
    u32, k32 = ctypes.WinDLL("user32", use_last_error=True), ctypes.WinDLL("kernel32")
    # Every HANDLE-taking prototype must be declared. Without argtypes ctypes marshals a
    # 64-bit handle as a C int and raises "int too long to convert" — which surfaces on the
    # UNLOCK, i.e. after the value has been read, so the failure looks unrelated to setup.
    u32.OpenClipboard.argtypes = [wintypes.HWND]
    u32.GetClipboardData.argtypes, u32.GetClipboardData.restype = [wintypes.UINT], wintypes.HANDLE
    k32.GlobalLock.argtypes, k32.GlobalLock.restype = [wintypes.HANDLE], ctypes.c_void_p
    k32.GlobalUnlock.argtypes, k32.GlobalUnlock.restype = [wintypes.HANDLE], wintypes.BOOL
    if not u32.OpenClipboard(None):
        return None, "another process holds the clipboard"
    try:
        if not u32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None, "clipboard holds no text"
        h = u32.GetClipboardData(CF_UNICODETEXT)
        p = k32.GlobalLock(h)
        if not p:
            return None, "could not lock the clipboard buffer"
        try:
            return ctypes.c_wchar_p(p).value, ""
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def clear_clipboard():
    try:
        import ctypes
        u32 = ctypes.WinDLL("user32")
        if u32.OpenClipboard(None):
            try:
                u32.EmptyClipboard()
            finally:
                u32.CloseClipboard()
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def cmd_capture(args):
    """Take the token straight from the clipboard into the drop file, then ingest.

    This is the path that lets an agent drive the provider's own web UI end to end: the
    browser clicks the provider's Copy button, and this reads the clipboard in-process.
    The value is never printed, never returned to the agent and never passes through a
    chat message — the same guarantee the paste-it-yourself path gives, without needing
    the human at the keyboard at all.
    """
    provs, err = recipes()
    if err:
        print("TOKEN-ONBOARD CONFIG ERROR: %s" % err)
        return 2
    name = args.provider.lower()
    if name not in provs:
        print("unknown provider %r" % name)
        return 2
    tok, cerr = read_clipboard()
    if cerr or not tok:
        print("nothing captured: %s" % (cerr or "clipboard was empty"))
        return 2
    tok = tok.strip()
    if not tok or len(tok.split()) != 1:
        # A clipboard holding a sentence means the Copy button was missed and something
        # else was copied. Storing that produces a mystifying auth failure much later.
        print("clipboard does not look like a token (%d whitespace-separated parts) — "
              "not storing it" % len(tok.split()))
        return 2
    line = "%s %s%s" % (name, tok,
                        (" --account-id %s" % args.account_id) if args.account_id else "")
    with open(DROP, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    print("captured %s %s -> drop file; ingesting" % (name, _mask(tok)))
    rc = cmd_ingest(args)
    if not getattr(args, "keep_clipboard", False):
        # A credential left on the clipboard is pasteable by anything that asks for it.
        print("clipboard cleared: %s" % ("yes" if clear_clipboard() else "FAILED"))
    return rc


def cmd_ingest(args):
    provs, err = recipes()
    if err:
        print("TOKEN-ONBOARD CONFIG ERROR: %s" % err)
        return 2
    if not os.path.exists(DROP):
        arm_drop()
        print("token-inbox: created (nothing pending). Run `request <provider>` first.")
        return 1
    with open(DROP, encoding="utf-8-sig") as fh:
        raw = fh.read()
    pending = [ln.strip() for ln in raw.splitlines()
               if ln.strip() and not ln.strip().startswith("#")]
    if not pending:
        print("token-inbox: empty — nothing to ingest.")
        return 1

    done, failed, keep = [], 0, []
    try:
        for ln in pending:
            name, token, account, perr = _parse_line(ln)

            def report(msg, _tok=token, _line=ln):
                """Single choke point for everything that gets printed OR written to the
                ledger. Scrubbing here rather than at each producer is deliberate: a note
                may come from an arbitrary CLI or an exception string, and those routinely
                echo back the credential they were handed. Relying on every producer to
                remember would work until the one that forgets — which is how the token
                would end up in a file on disk, since `done` is also the ledger."""
                out = _scrub(msg, _tok)
                # Belt and braces: never let a raw input line through either.
                return _scrub(out, _line)

            if perr:
                # Never echo the line: it contains the token. Keep it — a malformed line
                # still holds a real credential that exists nowhere else, and the operator
                # only has to fix the formatting.
                done.append("SKIP (%s) — line kept for you to correct" % perr)
                keep.append(ln)
                failed += 1
                continue
            r = provs.get(name)
            if not r:
                done.append(report("SKIP %s (unknown provider — add it to %s); line kept"
                                   % (name, os.path.basename(RECIPES))))
                keep.append(ln)
                failed += 1
                continue
            stored = False
            try:
                # A vault-backed credential is overwritten in place, so an unverified token
                # would destroy a WORKING one before anything noticed — and because it is
                # then "stored", the drop-file line goes too, leaving no copy of either.
                # Both verify paths can judge a token held in hand, so when something is
                # already there, prove the new one first. Nothing to lose means nothing to
                # prove: a first-time install still proceeds even if the network is down.
                prior, prior_unknown = None, False
                if r.get("kind") == "env":
                    prior, perr = vault_get(r)
                    # An unreadable vault is not an empty vault. Treating it as empty here
                    # is the worst version of that mistake anywhere in this file: it skips
                    # the check and lets an unverified token overwrite a credential we
                    # simply could not see. Not knowing means assuming something is there.
                    prior_unknown = bool(perr)
                if (prior and prior != token) or prior_unknown:
                    pstate, pnote = verify_one(name, r, token=token)
                    if pstate != "OK":
                        done.append(report(
                            "REFUSED %s %s — %s: %s; %s, line kept"
                            % (name, _mask(token), pstate, str(pnote)[:160],
                               "vault unreadable so an existing credential cannot be ruled "
                               "out" if prior_unknown else "existing credential kept")))
                        keep.append(ln)
                        failed += 1
                        continue
                ok, note = install_one(name, r, token, account)
                if not ok:
                    # A non-zero exit does not prove nothing was written. key-onboard.py
                    # can update the matrix and then die before returning, and a child
                    # killed between those two points would otherwise leave us keeping a
                    # plaintext line for a key that is already stored. Ask the store.
                    landed = _already_stored(name, r, token)
                    done.append(report(
                        "%s %s %s — install: %s; line %s"
                        % ("WARN" if landed else "FAIL", name, _mask(token), note,
                           "dropped (token IS in the store despite the error)" if landed
                           else "kept")))
                    if not landed:
                        keep.append(ln)
                    failed += 1
                    continue
                # Stored somewhere durable from here on, so the plaintext line is now
                # redundant and gets dropped regardless of what verification says.
                stored = True
                # D: installed is not the same as working. Say which one happened, and
                # only record success once the provider itself confirmed THIS token —
                # not merely some credential that happens to be on file for this provider.
                state, vnote = verify_one(name, r, token=token)
                if state == "OK":
                    iok, ierr = record_inventory(name, r)
                    done.append(report(
                        "OK   %s %s — installed and verified%s"
                        % (name, _mask(token),
                           "" if iok else " (inventory NOT updated: %s)" % ierr)))
                    if not iok:
                        failed += 1
                else:
                    done.append(report("WARN %s %s — stored, but NOT confirmed (%s): %s"
                                       % (name, _mask(token), state, str(vnote)[:200])))
                    failed += 1
            except Exception as exc:  # noqa: BLE001
                # One provider's recipe must not cost another provider's token. Without
                # this, an unexpected error on line 2 escapes to the finally block, which
                # rewrites the drop file — destroying a token that was never installed and
                # that the operator would have to re-issue at the provider.
                #
                # `stored` decides the opposite risk. A failure raised AFTER the token
                # reached a durable store (a verify command that throws, a corrupt
                # inventory) must not resurrect the plaintext line: the secret is already
                # safe, so keeping it would leave a copy on disk for nothing.
                done.append(report("%s %s %s — %s: %s; line %s"
                                   % ("WARN" if stored else "FAIL", name, _mask(token),
                                      type(exc).__name__, exc,
                                      "dropped (token IS stored)" if stored else "kept")))
                if not stored:
                    keep.append(ln)
                failed += 1
    finally:
        # C: removing the stored plaintext is not optional and not best-effort. If it
        # cannot be removed, that is the worst outcome this engine has, and it must not be
        # a line buried in a success report. `keep` holds only lines whose token reached no
        # other store, so rewriting here destroys nothing that has no copy.
        wiped, werr = True, ""
        try:
            arm_drop(keep=keep)
        except OSError as exc:
            wiped, werr = False, str(exc)
        ledger_err = ""
        try:
            if done:
                with open(LEDGER, "a", encoding="utf-8") as fh:
                    fh.write("%s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                    fh.write("\n".join("  " + d for d in done) + "\n")
        except OSError as exc:
            # Not fatal — the credential is installed and the plaintext is gone — but the
            # masked record is the only durable evidence of what happened, so losing it
            # silently would leave the operator with no way to audit this run.
            ledger_err = str(exc)

    for d in done:
        print(d)
    if not wiped:
        print("\n*** SECURITY: could not wipe %s (%s). A PLAINTEXT TOKEN IS STILL ON DISK."
              "\n*** Delete the file yourself now, then revoke and reissue the token."
              % (DROP, werr))
        return 2
    if ledger_err:
        print("\nWARNING: stored lines removed, but the masked record could not be written "
              "to %s (%s) — this run leaves no audit trail." % (LEDGER, ledger_err))
    else:
        print("\nstored lines removed; masked record in %s" % os.path.basename(LEDGER))
    if keep:
        print("%d line(s) KEPT in %s — their tokens reached no other store, so deleting "
              "them would have cost you a trip back to the provider. Plaintext is still "
              "in that file until you re-run ingest or clear it." % (len(keep), DROP))
    return 1 if failed else 0


def record_inventory(name, recipe):
    """Tell auth_check this service is solved, so no agent ever punts it to the operator.

    (ok, err). Swallowing a failure here used to be invisible: the run reported success
    while auth_check went on saying UNKNOWN, so the next agent would still punt the service
    back to the operator and nobody would know why.
    """
    doc, err = _load(INVENTORY, {"services": {}})
    if err or not isinstance(doc, dict):
        return False, err or "inventory is not an object"
    # `services` being present is not the same as it being usable. A hand-edit leaving it as
    # a list would raise here, and the caller's per-line handler would then keep a plaintext
    # line whose token is already safely stored — leaving the secret on disk for no reason.
    if not isinstance(doc.get("services", {}), dict):
        return False, ("inventory 'services' is %s, expected an object — refusing to "
                       "overwrite a file someone edited by hand"
                       % type(doc["services"]).__name__)
    doc.setdefault("services", {})
    for key in (recipe.get("service_key") or name,):
        doc["services"][key] = {
            "authorized": True,
            "method": "browser-free",
            "path": "credential installed by token-onboard.py; run "
                    "`token-onboard.py exec %s -- <cmd>` or use the tool directly" % name,
            "vault": vault_path(recipe) or "tool's own credential store",
            "cite": "token-onboard.py + _registry/token-onboard.json",
            "operator_action": "none",
        }
    try:
        atomic_write(INVENTORY, json.dumps(doc, ensure_ascii=False, indent=1))
    except OSError as exc:
        return False, str(exc)
    return True, ""


def cmd_verify(args):
    provs, err = recipes()
    if err:
        print("TOKEN-ONBOARD CONFIG ERROR: %s" % err)
        return 2
    names = [args.provider.lower()] if args.provider else sorted(provs)
    bad = 0
    for n in names:
        r = provs.get(n)
        if not r:
            print("%-14s unknown provider" % n)
            bad += 1
            continue
        state, note = verify_one(n, r)
        hint = {"MISSING": "  -> token-onboard.py request %s" % n,
                "NO-TOOL": "  -> install %s first: %s"
                           % (n, r.get("install_tool_hint") or "(no hint in recipe)"),
                "BLOCKED": "  -> client blocked, token NOT judged; leave it alone",
                "QUOTA": "  -> wait/add credits/switch provider; do NOT mint another same-account key",
                "ACCOUNT": "  -> repair the account/org; do NOT churn keys",
                "NO-VERIFY": "  -> unreachable or no verify defined; token NOT judged"}
        print("%-13s %-10s%s" % (n, state, hint.get(state, "")))
        if state != "OK":
            bad += 1
            # The reason is the whole value of a failed verify. Detail is already scrubbed
            # of the token by _verify_http / _scrub before it gets here.
            if note:
                print("%-13s   %s" % ("", str(note).replace("\n", " ")[:300]))
    return 1 if bad else 0


def cmd_exec(args):
    provs, err = recipes()
    if err:
        print("TOKEN-ONBOARD CONFIG ERROR: %s" % err)
        return 2
    r = provs.get(args.provider.lower())
    if not r:
        print("unknown provider %r" % args.provider)
        return 2
    if not args.argv:
        print("nothing to run — put the command after `--`")
        return 2
    if not r.get("env"):
        print("%s does not use an injected env var; run the tool directly (its own "
              "credential store already has the token)." % args.provider)
        return 2
    tok, verr = vault_get(r)
    if verr:
        print("%s: %s — refusing to run, since a command launched without the credential "
              "would fail in a way that looks like a bad token." % (args.provider, verr))
        return 2
    if not tok:
        print("%s has no stored credential — run: token-onboard.py request %s"
              % (args.provider, args.provider))
        return 2
    extra = {}
    if r.get("account_env") and r.get("account_vault_path"):
        try:
            import _secrets
            acct = _secrets.get(r["account_vault_path"])
            if acct:
                extra[r["account_env"]] = acct
        except Exception:  # noqa: BLE001
            pass
    rc, out = _exec_with_env(r, args.argv, tok, extra)
    if out:
        print(out.rstrip())
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("list")
    rq = sub.add_parser("request")
    rq.add_argument("provider")
    sub.add_parser("ingest")
    cp = sub.add_parser("capture")
    cp.add_argument("provider")
    cp.add_argument("--account-id", dest="account_id")
    cp.add_argument("--keep-clipboard", action="store_true")
    vf = sub.add_parser("verify")
    vf.add_argument("provider", nargs="?")
    ex = sub.add_parser("exec")
    ex.add_argument("provider")
    # dest must NOT be "cmd" — that is the subparsers' own dest and would be clobbered.
    ex.add_argument("argv", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    if a.cmd == "list":
        return cmd_list(a)
    if a.cmd == "request":
        return cmd_request(a)
    if a.cmd == "ingest":
        return cmd_ingest(a)
    if a.cmd == "capture":
        return cmd_capture(a)
    if a.cmd == "verify":
        return cmd_verify(a)
    if a.cmd == "exec":
        # REMAINDER keeps a leading "--" as a literal token; strip only that one, since a
        # later "--" may belong to the wrapped command (e.g. `npm run x -- --flag`).
        argv = list(a.argv)
        if argv and argv[0] == "--":
            argv = argv[1:]
        a.argv = argv
        return cmd_exec(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
