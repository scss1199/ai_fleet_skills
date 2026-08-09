#!/usr/bin/env python3
"""MTM module block #2 — turn the probe result into an actionable console list.

Pure function of redirect_uri_state.json: no network, no writes outside this
folder. Safe to re-run at any point; it never edits anything in Google.

Grouping by client_id matters: some clients are shared (ai-ut and ai-eatery sit
on the same client), and the rule is ADD ONLY — never touch an existing line, or
a working site loses its login.
"""
import collections
import json
import pathlib
import urllib.parse

HERE = pathlib.Path(__file__).parent
rows = json.loads((HERE / "redirect_uri_state.json").read_text(encoding="utf-8"))

# Sites whose probe says REGISTERED only because they still emit the
# pre-migration origin are read straight off the state file (google ==
# STALE_ORIGIN). This used to be a hand-written PENDING_ADDS list, which is the
# same trap as a hand-written SITES map: once ai-ziyaoastro's emit side was
# fixed on 2026-08-09 the row became a real MISMATCH and the stale hand entry
# printed a duplicate section telling the operator to redo work already done.
# Deriving it means the section appears exactly while the condition holds.

# operator 2026-08-06: 優先處理 fracdigi > jci-taipei > 其餘。fracdigi 已由探針
# 證實 REGISTERED（無 mismatch），所以清單從 jci-taipei 開始。
PRIORITY = ["ai-fracdigi", "ai-jci-taipei"]


def _rank(worker):
    return PRIORITY.index(worker) if worker in PRIORITY else len(PRIORITY)


bad = sorted((r for r in rows if r.get("google") == "MISMATCH"),
             key=lambda r: (_rank(r["worker"]), r["worker"]))
ok = [r for r in rows if r.get("google") == "REGISTERED"]
stale = [r for r in rows if r.get("google") == "STALE_ORIGIN"]
nologin = [r for r in rows if r.get("google") == "NO_LOGIN"]
by_client = collections.OrderedDict()
for r in bad:
    by_client.setdefault(r["client_id"], []).append(r)

lines = [
    "# redirect_uri_mismatch — console fix list",
    "",
    f"Source of truth: `redirect_uri_state.json` (probe run), {len(bad)} site(s) failing, "
    f"{len(by_client)} OAuth client(s) to edit.",
    "",
    "Rule: in the **Authorised redirect URIs** section (NOT JavaScript origins), "
    "click **+ Add URI**, paste the line, Save. **Only add** — never edit or delete "
    "an existing line; several of these clients are shared with live sites.",
    "",
    # `"…" + ", ".join(...) or "(none)"` was the original line: `+` binds tighter
    # than `or`, so the fallback could never fire and an empty OK set printed a
    # dangling colon instead. Build the two halves separately.
    "Already REGISTERED — no console action (verified by the same probe run): "
    + (", ".join(f"`{r['worker']}`" for r in ok) or "(none)"),
    "",
    # Printed so a worker with no login endpoint cannot silently vanish from the
    # coverage claim: "every site was checked" has to include the ones with
    # nothing to check.
    "No OAuth login endpoint — nothing to register: "
    + (", ".join(f"`{r['worker']}`" for r in nologin) or "(none)"),
    "",
]

for cid, items in by_client.items():
    project_number = cid.split("-")[0]
    console = f"https://console.cloud.google.com/auth/clients/{cid}?project={project_number}"
    workers = ", ".join(i["worker"] for i in items)
    lines.append(f"## {workers}")
    lines.append("")
    lines.append(f"- console: {console}")
    for i in items:
        lines.append(f"- ADD: `{i['redirect_uri']}`")
    lines.append("")

# A STALE_ORIGIN row is not in the MISMATCH set: its login sends a callback that
# IS registered, so Google is happy — it just points at a host that no longer
# serves the app, and the user is stranded after authenticating. Two edits are
# needed and the ORDER is load-bearing: register the new URI FIRST, then flip the
# app's emit side. Flipping first would turn a broken-after-login site into a
# site that cannot even reach consent.
for r in stale:
    cid = r["client_id"].split(".")[0]
    project_number = cid.split("-")[0]
    want = f"https://{r['probe_origin']}" + urllib.parse.urlparse(r["redirect_uri"]).path
    lines.append(f"## {r['worker']} (STALE_ORIGIN — pre-add, then flip the app's emit side)")
    lines.append("")
    lines.append(f"- console: https://console.cloud.google.com/auth/clients/{cid}"
                 f".apps.googleusercontent.com?project={project_number}")
    lines.append(f"- ADD: `{want}`")
    lines.append(f"- currently emitted (registered but dead): `{r['redirect_uri']}`")
    lines.append("- after the add: point the backend's `GOOGLE_REDIRECT_URI` at the same value")
    lines.append("")

lines += [
    "## Verify",
    "",
    "```bash",
    "python C:/ai_workspace/_skill/fleet-skills/ztm-oauth-redirect-fleet/scripts/probe_redirect_uri.py",
    "```",
    "",
    "Done when the stderr summary reads `BAD=0`. The probe is self-checking: "
    "`control_redirect_uri.py` proves it can still tell a registered URI from an "
    "unregistered one.",
    "",
]

out = HERE / "redirect_uri_fix_handoff.md"
out.write_text("\n".join(lines), encoding="utf-8")
print(f"wrote {out} — {len(bad)} sites / {len(by_client)} clients")
for cid, items in by_client.items():
    print(f"  {cid.split('-')[0]:14s} {cid[:34]:36s} {', '.join(i['worker'] for i in items)}")
