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

HERE = pathlib.Path(__file__).parent
rows = json.loads((HERE / "redirect_uri_state.json").read_text(encoding="utf-8"))

# (client_id without suffix, URI to add, worker) — sites whose probe says
# REGISTERED only because they still point at the pre-migration origin.
PENDING_ADDS = [
    ("433379372607-rde329v31tp5mslqjbj2p6tj8231h1ki",
     "https://ai-ziyaoastro.kyloren.workers.dev/api/auth/google/callback",
     "ai-ziyaoastro"),
]

# operator 2026-08-06: 優先處理 fracdigi > jci-taipei > 其餘。fracdigi 已由探針
# 證實 REGISTERED（無 mismatch），所以清單從 jci-taipei 開始。
PRIORITY = ["ai-fracdigi", "ai-jci-taipei"]


def _rank(worker):
    return PRIORITY.index(worker) if worker in PRIORITY else len(PRIORITY)


bad = sorted((r for r in rows if r.get("google") == "MISMATCH"),
             key=lambda r: (_rank(r["worker"]), r["worker"]))
ok = [r for r in rows if r.get("google") == "REGISTERED"]
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
    "Already REGISTERED — no console action (verified by the same probe run): "
    + ", ".join(f"`{r['worker']}`" for r in ok) or "(none)",
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

# ai-ziyaoastro is not in the MISMATCH set: its login still sends the *Vercel*
# callback, which is registered, so it works today. Repointing the Fly backend's
# GOOGLE_REDIRECT_URI to the Worker before this URI is registered would break a
# currently-working login, so the two steps must land together — hence it belongs
# in the same console session rather than in a later one.
for cid, ruri, worker in PENDING_ADDS:
    project_number = cid.split("-")[0]
    lines.append(f"## {worker} (pre-add, then flip the backend env)")
    lines.append("")
    lines.append(f"- console: https://console.cloud.google.com/auth/clients/{cid}"
                 f".apps.googleusercontent.com?project={project_number}")
    lines.append(f"- ADD: `{ruri}`")
    lines.append("- after the add: set the Fly backend `GOOGLE_REDIRECT_URI` to the same value")
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
