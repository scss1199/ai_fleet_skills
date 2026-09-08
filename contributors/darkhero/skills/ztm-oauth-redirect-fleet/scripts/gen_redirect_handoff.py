#!/usr/bin/env python3
"""MTM module block #2 — turn the probe result into an actionable console list.

Pure function of redirect_uri_state.json: no network, no writes outside this
folder. Safe to re-run at any point; it never edits anything in Google.

Grouping by client_id matters: some clients are shared (ai-ut and ai-eatery sit
on the same client), and the rule is ADD ONLY — never touch an existing line, or
a working site loses its login.

THE ADD LINE IS NEVER THE EMITTED URI
-------------------------------------
Every `ADD:` value is `row["desired_redirect_uri"]`, which the probe derives from
the inventory's canonical_origin plus the callback path. The previous version
printed `row["redirect_uri"]` — the URI the app currently sends — for the whole
MISMATCH section. For a site that is BOTH unregistered and pointing at a dead
host that instruction registers the dead host: the operator does the console
work, the probe turns green, and the login is still broken. This module now
refuses to print such a line at all (see _assert_never_stale).

Rows that cannot be fixed in the console at all — a service that declares Google
SSO and serves no login endpoint, or a deployed worker missing from
inventory.json — get their own section instead of being dropped. They were
previously invisible here AND excluded from the probe's failure count.
"""
import collections
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
STATE_PATH = HERE / "redirect_uri_state.json"
OUT_PATH = HERE / "redirect_uri_fix_handoff.md"

# Must match probe_redirect_uri.SCHEMA_VERSION. Reading an older state file with
# this code would silently treat missing fields as "fine" and emit a console list
# built from absent evidence.
EXPECTED_SCHEMA = 2

# operator 2026-08-06: 優先處理 fracdigi > jci-taipei > 其餘。
PRIORITY = ["ai-fracdigi", "ai-jci-taipei"]

STALE_ORIGIN_VERDICTS = {"STALE", "INSECURE_SCHEME", "CREDENTIALS", "MALFORMED"}


def _rank(worker):
    return PRIORITY.index(worker) if worker in PRIORITY else len(PRIORITY)


def load_state(path=None):
    data = json.loads(pathlib.Path(path or STATE_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "rows" not in data:
        raise SystemExit(
            "redirect_uri_state.json is not a schema-versioned envelope. "
            "Re-run probe_redirect_uri.py; do not hand-edit the state file.")
    schema = data.get("schema")
    if schema != EXPECTED_SCHEMA:
        raise SystemExit(
            f"state schema {schema!r} != expected {EXPECTED_SCHEMA}. "
            "Re-run probe_redirect_uri.py rather than reading it with this code.")
    return data


def _console_url(client_id):
    cid = client_id or ""
    project_number = cid.split("-")[0]
    return f"https://console.cloud.google.com/auth/clients/{cid}?project={project_number}"


def _assert_never_stale(row, add_uri):
    """Hard stop: an ADD line must never be a URI we just proved is wrong.

    This is an assertion and not a filter on purpose. If the derivation ever
    regresses to echoing the emitted URI, the correct outcome is a crashed
    generator, not a plausible-looking console list.
    """
    if row.get("origin") in STALE_ORIGIN_VERDICTS and add_uri == row.get("redirect_uri"):
        raise AssertionError(
            f"{row['worker']}: refusing to emit ADD for a {row['origin']} callback "
            f"({add_uri!r}). desired_redirect_uri derivation is broken.")


def client_users(rows):
    """client_id -> every service on it, blocked or not.

    The shared-client warning must NOT be derived from the addable rows alone.
    Measured 2026-08-10: `ai-ut` needed an ADD on the client `ai-eatery` already
    uses successfully. Only one row was addable, so the "shared client" line was
    suppressed on exactly the client where a careless edit takes a *working* site
    offline — the warning went quiet precisely when it mattered most.
    """
    users = collections.OrderedDict()
    for r in rows:
        cid = r.get("client_id")
        if cid:
            users.setdefault(cid, []).append(r["worker"])
    return users


def classify_rows(rows):
    """Split into: needs a console ADD / already clean / N-A / not fixable here."""
    addable, clean, not_applicable, unfixable = [], [], [], []
    for r in rows:
        if r.get("verdict") == "NOT_APPLICABLE":
            not_applicable.append(r)
            continue
        if not r.get("blocking"):
            clean.append(r)
            continue
        if r.get("desired_redirect_uri") and r.get("client_id"):
            addable.append(r)
        else:
            unfixable.append(r)
    addable.sort(key=lambda r: (_rank(r["worker"]), r["worker"]))
    return addable, clean, not_applicable, unfixable


def build_handoff(state):
    rows = state["rows"]
    addable, clean, not_applicable, unfixable = classify_rows(rows)
    users = client_users(rows)

    by_client = collections.OrderedDict()
    for r in addable:
        by_client.setdefault(r["client_id"], []).append(r)

    lines = [
        "# redirect_uri — console fix list",
        "",
        f"Source of truth: `redirect_uri_state.json` schema {state.get('schema')}, "
        f"probed {state.get('generated_at')}.",
        f"{len(addable)} site(s) need a console ADD across {len(by_client)} OAuth client(s); "
        f"{len(unfixable)} blocked site(s) cannot be fixed in the console.",
        "",
        "Rule: in the **Authorised redirect URIs** section (NOT JavaScript origins), "
        "click **+ Add URI**, paste the line, Save. **Only add** — never edit or delete "
        "an existing line; several of these clients are shared with live sites.",
        "",
        "Every `ADD` value below is derived from the service's declared "
        "`canonical_origin` in `inventory.json`, not from the URI the app currently "
        "emits. Where those differ the app's emit side must be flipped too, and the "
        "row says so.",
        "",
        "Green — registered, origin matches, verified by this probe run: "
        + (", ".join(f"`{r['worker']}`" for r in clean) or "(none)"),
        "",
        "No Google SSO by design (`expects_login: false`) — nothing to register: "
        + (", ".join(f"`{r['worker']}`" for r in not_applicable) or "(none)"),
        "",
    ]

    for cid, items in by_client.items():
        workers = ", ".join(i["worker"] for i in items)
        lines.append(f"## {workers}")
        lines.append("")
        lines.append(f"- console: {_console_url(cid)}")
        on_client = sorted(users.get(cid, []))
        if len(on_client) > 1:
            others = [w for w in on_client if w not in {i["worker"] for i in items}]
            lines.append(f"- **shared client** — {len(on_client)} services depend on it "
                         f"({', '.join(on_client)}). ADD ONLY.")
            if others:
                lines.append(f"  - already working on this client, do NOT touch their lines: "
                             f"{', '.join(f'`{w}`' for w in others)}")
        for i in items:
            add = i["desired_redirect_uri"]
            _assert_never_stale(i, add)
            lines.append(f"- ADD: `{add}`")
            lines.append(f"  - {i['worker']}: registration={i['registration']} origin={i['origin']}")
            if i.get("redirect_uri") and i["redirect_uri"] != add:
                lines.append(f"  - currently emitted (do NOT register this): `{i['redirect_uri']}`")
                # ORDER IS LOAD-BEARING: register the new URI first, then flip the
                # app. Flipping first turns a broken-after-login site into a site
                # that cannot reach consent at all.
                lines.append("  - after the add: point the backend's `GOOGLE_REDIRECT_URI` "
                             "at the ADD value — in that order, never before.")
            for reason in i.get("reasons", []):
                lines.append(f"  - reason: {reason}")
        lines.append("")

    if unfixable:
        lines.append("## Blocked, but NOT a console problem")
        lines.append("")
        lines.append("No redirect URI can be registered for these. Adding one would not "
                     "help; the service itself has to change.")
        lines.append("")
        for r in unfixable:
            lines.append(f"- `{r['worker']}` — login={r['login']} "
                         f"registration={r['registration']} origin={r['origin']}")
            for reason in r.get("reasons", []):
                lines.append(f"  - {reason}")
        lines.append("")

    lines += [
        "## Verify",
        "",
        "```bash",
        "python C:/ai_workspace/_skill/fleet-skills/ztm-oauth-redirect-fleet/scripts/probe_redirect_uri.py",
        "```",
        "",
        "Done when the stderr summary reads `BLOCKED=0` and the process exits 0. "
        "The probe is self-checking: `control_redirect_uri.py` proves it can still "
        "tell a registered URI from an unregistered one, and exits non-zero when it "
        "cannot.",
        "",
    ]
    return lines


def main(argv=None):
    state = load_state()
    lines = build_handoff(state)
    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    addable, _clean, _na, unfixable = classify_rows(state["rows"])
    by_client = collections.OrderedDict()
    for r in addable:
        by_client.setdefault(r["client_id"], []).append(r)
    print(f"wrote {OUT_PATH} — {len(addable)} sites / {len(by_client)} clients "
          f"/ {len(unfixable)} not console-fixable")
    for cid, items in by_client.items():
        print(f"  {cid.split('-')[0]:14s} {cid[:34]:36s} "
              f"{', '.join(i['worker'] for i in items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
