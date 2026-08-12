#!/usr/bin/env python
"""console_add_redirect.py — 全艦隊 Google OAuth console redirect URI 的讀取與 ADD-ONLY 補寫。

任何 seat 都可以直接呼叫（腳本在 hub 共用區，不需要各站複製）。
`AI_WORKSPACE` 實測未設（Machine/User/Process 皆空，2026-08-12），所以下面用字面路徑：

    set P=C:\\ai_workspace\\_skill\\fleet-skills\\ztm-oauth-redirect-fleet\\scripts

    python %P%\\console_add_redirect.py verify --from-state          # 我進得去哪些專案（唯讀）
    python %P%\\console_add_redirect.py verify --client <client_id>  # 單一 client 唯讀
    python %P%\\console_add_redirect.py add --client <id> --add <uri>
    python %P%\\console_add_redirect.py sync --from-state            # dry-run 全艦隊
    python %P%\\console_add_redirect.py sync --from-state --apply    # 真的寫

產出（report/截圖）寫到 `_logs/oauth-redirect-fleet/`，刻意在技能樹外——見下方 `OUT`。

Why this exists
---------------
`known-failures.md`「The console edit cannot be automated」講的是**沒有公開 API**
（`gcloud alpha iam oauth-clients` 是 Workforce Identity Federation、
`gcloud iap oauth-clients` 只有 IAP brand），那點依然成立。改變的是瀏覽器面：
`_registry/sso-realms.json` 的 `google.cloud.console`（mode=persistent）seeded 之後，
agent 自己驅動 console UI。operator 的參與從「每支 client 貼一次」變成「登入一次」。

三個 load-bearing 的設計決定
--------------------------
1. **專案從 client_id 前綴推導，不查登錄檔。** client_id 的數字前綴就是 GCP project
   number，`?project=<number>` 可直接開。`_registry/fleet-oauth-clients.json` 是「計畫」
   而非量測值，實測 2026-08-12 它把 jci_taipei 記在 `iron-wave-466411-v5`（真值
   `jci-taipei`/576912529343）、eatery 的 prefix 也對不上。信 probe 從 live login redirect
   量到的 client_id。
2. **絕不用裸的 `/apis/credentials`。** realm 的 `login_url` 沒帶 project，會開在 operator
   上次用的專案（實測落在 `messages-fracdigi-com` 而目標是 `jci-taipei`）。從那裡點下去
   會改到別的專案而 log 還寫著目標站名。
3. **欄位用區塊標題切分，不用「最後一個空欄位」。** client 頁面有兩個區塊
   （「已授權的 JavaScript 來源」與「已授權的重新導向 URI」），**各有一顆一模一樣的
   「新增 URI」按鈕、placeholder 也相同**（實測 ai-busker）。用 `btn.last` /
   `blanks[-1]` 只在單區塊的 client 上碰巧正確；在有 JS 來源的 client 上會寫進錯的區塊。
   `_locate()` 以 `compareDocumentPosition` 取「重新導向 URI 標題之後、Additional
   information/用戶端密鑰之前」的 input，並回報 JS 來源欄位的 index 以便自我稽核。

ADD-ONLY 紀律
-------------
只寫進本區塊新開的空欄位。既有列一行都不碰——client 是跨站共用的（`433379372607-*`
一支管好幾站），改掉或刪掉任何一行等於把正在運作的站弄下線。寫入後重新載入、比對
`lost_existing == []` 與 `jso_untouched`，兩者任一不成立就以非 0 退出。

退出碼：0 全部已就位/新增成功 · 2 有 row 失敗或 UI 對不上 · 3 realm 沒登入。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HUB = Path(os.environ.get("AI_WORKSPACE") or r"C:\ai_workspace")
REALM = "google.cloud.console"
PROFILE = HUB / "_secrets" / "browser-profiles" / REALM

# State/report/screenshots are anchored to the HUB copy, never to `__file__`.
# `fleet-skill-sync.py deploy` copies this whole skill — scripts included — into 33
# seat roots as a discovery surface. A seat copy resolving paths next to itself would
# write a second `redirect_uri_state.json`, and this skill has already been burned
# three times by exactly one thing: two places that could each be believed.
# `AI_WORKSPACE` is not actually set on this machine (checked Machine/User/Process
# 2026-08-12), so the literal fallback is the path that does the work — keep it.
CANON = HUB / "_skill" / "fleet-skills" / "ztm-oauth-redirect-fleet" / "scripts"
STATE = CANON / "redirect_uri_state.json"  # written by probe_redirect_uri.py, read-only here
# Outputs live OUTSIDE the skill tree: `deploy` copies the tree verbatim, so anything
# generated inside `scripts/` gets mirrored into 33 seats as a frozen snapshot that
# looks exactly like a measurement. Screenshots additionally must never be committed —
# a client page shows 用戶端密鑰.
OUT = HUB / "_logs" / "oauth-redirect-fleet"
SHOTS = OUT / "console_shots"
REPORT = OUT / "console_access_report.json"
STATE_SCHEMA = 2

# 兩個區塊的標題與尾界；zh-TW console 與英文 console 都要認得。
LOCATE_JS = r"""() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const REDIR = ['已授權的重新導向 URI', 'Authorised redirect URIs', 'Authorized redirect URIs'];
  const JSO   = ['已授權的 JavaScript 來源', 'Authorised JavaScript origins', 'Authorized JavaScript origins'];
  const TAIL  = ['Additional information', '用戶端密鑰', '其他資訊', 'Client secrets'];
  const heads = [...document.querySelectorAll('h1,h2,h3,h4,[role="heading"]')];
  const hit = (h, names) => names.some(n => norm(h.textContent) === n || norm(h.textContent).startsWith(n));
  const DENIED = ['您需要額外存取權', '其他存取權', 'You need additional access',
                  'additional access', '需要權限', 'permission'];
  const hR = heads.find(h => hit(h, REDIR));
  const hJ = heads.find(h => hit(h, JSO));
  if (!hR) {
    const seen = heads.map(h => norm(h.textContent)).filter(Boolean).slice(0, 25);
    // 「這個帳號沒有這個專案的權限」與「我的選擇器壞了」是不同的指控，必須分開回報。
    const denied = seen.find(t => DENIED.some(d => t.includes(d)));
    return { error: denied ? 'no-access' : 'redirect-heading-not-found',
             denied_message: denied || null, headings: seen };
  }
  const follows = (el, ref) =>
      !!ref && !!(ref.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING);
  const hT = heads.find(h => hit(h, TAIL) && follows(h, hR));
  const inSection = el => follows(el, hR) && (!hT || follows(hT, el));
  const inputs = [...document.querySelectorAll('input')];
  const buttons = [...document.querySelectorAll('button')];
  const ADD = /新增 URI|Add URI/;
  return {
    redirect_inputs: inputs.map((el, i) => ({ i, value: norm(el.value) })).filter(o => inSection(inputs[o.i])),
    jso_inputs: inputs.map((el, i) => ({ i, value: norm(el.value) }))
        .filter(o => hJ && follows(inputs[o.i], hJ) && follows(hR, inputs[o.i])),
    add_button: buttons.findIndex(b => ADD.test(norm(b.textContent)) && inSection(b)),
    save_button: buttons.findIndex(b => /^(儲存|Save|SAVE)$/.test(norm(b.textContent))),
  };
}"""


def project_of(client_id: str) -> str:
    """client_id 的數字前綴＝GCP project number。console 吃 number 也吃 project_id。"""
    prefix = client_id.split("-", 1)[0]
    if not prefix.isdigit():
        raise ValueError(f"cannot derive project from client_id: {client_id!r}")
    return prefix


def deep_link(client_id: str, project: str | None = None) -> str:
    return (
        "https://console.cloud.google.com/auth/clients/"
        f"{client_id}?project={project or project_of(client_id)}"
    )


def _locate(page) -> dict:
    return page.evaluate(LOCATE_JS)


def signed_in_as(page) -> str | None:
    """哪個帳號在跑。NO_ACCESS 的時候，這是「該授權給誰」唯一有用的資訊。"""
    return page.evaluate(
        r"""() => {
            const re = /[\w.+-]+@[\w-]+\.[\w.]+/;
            for (const el of document.querySelectorAll('[aria-label],[alt],[title]')) {
                for (const a of ['aria-label', 'alt', 'title']) {
                    const m = re.exec(el.getAttribute(a) || '');
                    if (m) return m[0];
                }
            }
            return null;
        }"""
    )


def _open(ctx, client_id: str, project: str | None, timeout: int) -> tuple:
    """→ (page, row). row['access'] ∈ OK|NOT_SIGNED_IN|UI_UNRECOGNISED"""
    url = deep_link(client_id, project)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(timeout)
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(7000)
    row: dict = {"client_id": client_id, "project": project or project_of(client_id),
                 "deep_link": url, "url_loaded": page.url}
    if "accounts.google.com" in page.url:
        row["access"] = "NOT_SIGNED_IN"
        return page, row
    loc = _locate(page)
    if loc.get("error"):
        row["access"] = "NO_ACCESS" if loc["error"] == "no-access" else "UI_UNRECOGNISED"
        row["locate_error"] = loc["error"]
        row["denied_message"] = loc.get("denied_message")
        row["headings_seen"] = loc.get("headings")
        return page, row
    row["access"] = "OK"
    row["redirect_uris"] = [o["value"] for o in loc["redirect_inputs"] if o["value"]]
    row["js_origins"] = [o["value"] for o in loc["jso_inputs"] if o["value"]]
    row["_loc"] = loc
    return page, row


def _shot(page, tag: str) -> str:
    SHOTS.mkdir(parents=True, exist_ok=True)
    p = SHOTS / f"{tag}-{time.strftime('%Y%m%d-%H%M%S')}.png"
    page.screenshot(path=str(p), full_page=True)
    return str(p)


def do_add(ctx, client_id: str, want: str, project: str | None, timeout: int, apply: bool) -> dict:
    page, row = _open(ctx, client_id, project, timeout)
    row["want"] = want
    if row["access"] != "OK":
        return row
    before, jso_before = row["redirect_uris"], row["js_origins"]
    row["screenshot_before"] = _shot(page, f"{row['project']}-{client_id.split('-')[1][:8]}-before")
    if want in before:
        row["outcome"] = "ALREADY_PRESENT"
        return row
    if not apply:
        row["outcome"] = "DRY_RUN"
        return row

    loc = row.pop("_loc")
    if loc["add_button"] < 0:
        row["outcome"] = "ADD_BUTTON_NOT_FOUND"
        return row
    page.locator("button").nth(loc["add_button"]).click()
    page.wait_for_timeout(1500)

    fresh = _locate(page)
    blanks = [o["i"] for o in fresh["redirect_inputs"] if not o["value"]]
    if not blanks:
        row["outcome"] = "NO_BLANK_FIELD_IN_SECTION"
        return row
    page.locator("input").nth(blanks[-1]).fill(want)
    page.wait_for_timeout(600)

    if fresh["save_button"] < 0:
        row["outcome"] = "SAVE_BUTTON_NOT_FOUND"
        return row
    page.locator("button").nth(fresh["save_button"]).click()
    page.wait_for_timeout(9000)

    _, after_row = _open(ctx, client_id, project, timeout)
    after = after_row.get("redirect_uris", [])
    row["redirect_uris_after"] = after
    row["lost_existing"] = [u for u in before if u not in after]
    row["jso_untouched"] = after_row.get("js_origins", []) == jso_before
    row["screenshot_after"] = _shot(page, f"{row['project']}-{client_id.split('-')[1][:8]}-after")
    ok = want in after and not row["lost_existing"] and row["jso_untouched"]
    row["outcome"] = "ADDED" if ok else "SAVE_NOT_REFLECTED_OR_COLLATERAL"
    return row


def targets_from_state(only: list[str] | None) -> list[dict]:
    doc = json.loads(STATE.read_text(encoding="utf-8"))
    if doc.get("schema") != STATE_SCHEMA:
        raise SystemExit(f"redirect_uri_state.json schema {doc.get('schema')} != {STATE_SCHEMA}; re-run probe")
    out = []
    for r in doc["rows"]:
        if only and r["worker"] not in only:
            continue
        if not r.get("client_id") or not r.get("desired_redirect_uri"):
            continue
        out.append({"worker": r["worker"], "client_id": r["client_id"],
                    "want": r["desired_redirect_uri"], "verdict": r["verdict"]})
    return out


def launch(headless: bool):
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    ctx = pw.chromium.launch_persistent_context(
        user_data_dir=str(PROFILE), channel="msedge", headless=headless,
        viewport={"width": 1440, "height": 1000},
        args=["--disable-blink-features=AutomationControlled"],
    )
    return pw, ctx


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mode", choices=["verify", "add", "sync"])
    ap.add_argument("--client")
    ap.add_argument("--project", help="預設由 client_id 數字前綴推導；只有 project 改名時才需要")
    ap.add_argument("--add", dest="want")
    ap.add_argument("--from-state", action="store_true", help="標的取自 redirect_uri_state.json")
    ap.add_argument("--only", action="append", help="限定 worker（可重複）")
    ap.add_argument("--apply", action="store_true", help="sync/add 真的寫入；預設 dry-run")
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--timeout", type=int, default=60_000)
    a = ap.parse_args()

    if a.mode == "add":
        if not (a.client and a.want):
            ap.error("add 需要 --client 與 --add")
        jobs = [{"worker": None, "client_id": a.client, "want": a.want}]
        apply = True  # `add` 是明確指名單一 client 的動作
    elif a.from_state:
        jobs = targets_from_state(a.only)
        apply = a.mode == "sync" and a.apply
    elif a.client:
        jobs = [{"worker": None, "client_id": a.client, "want": a.want or ""}]
        apply = False
    else:
        ap.error("需要 --client 或 --from-state")

    # 同一支 client 管多站時只開一次頁面；標的相同就不重複走。
    seen: set[tuple] = set()
    pw, ctx = launch(a.headless)
    rows: list[dict] = []
    account: str | None = None
    try:
        for j in jobs:
            key = (j["client_id"], j["want"])
            if key in seen:
                continue
            seen.add(key)
            if a.mode == "verify" or not j["want"]:
                page, row = _open(ctx, j["client_id"], a.project, a.timeout)
                row.pop("_loc", None)
                account = account or signed_in_as(page)
            else:
                row = do_add(ctx, j["client_id"], j["want"], a.project, a.timeout, apply)
                row.pop("_loc", None)
            row["worker"] = j.get("worker")
            rows.append(row)
            print(f"  {str(row.get('worker') or row['client_id'][:24]).ljust(20)} "
                  f"project={row['project'].ljust(16)} access={row['access']} "
                  f"{row.get('outcome','')}", file=sys.stderr, flush=True)
    finally:
        ctx.close()
        pw.stop()

    summary = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": a.mode, "applied": apply,
        "signed_in_as": account,
        "projects": sorted({r["project"] for r in rows}),
        "access_ok": sum(r["access"] == "OK" for r in rows),
        "no_access": [r.get("worker") or r["client_id"] for r in rows if r["access"] == "NO_ACCESS"],
        "access_bad": sum(r["access"] != "OK" for r in rows),
        "rows": rows,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, ensure_ascii=False, indent=2))
    print(f"rows -> {REPORT}", file=sys.stderr)

    if any(r["access"] == "NOT_SIGNED_IN" for r in rows):
        print("realm 未登入 — python %AI_WORKSPACE%\\_skill\\engines\\sso_browser.py seed "
              "google.cloud.console", file=sys.stderr)
        return 3
    bad = [r for r in rows if r["access"] != "OK"
           or r.get("outcome") in {"ADD_BUTTON_NOT_FOUND", "NO_BLANK_FIELD_IN_SECTION",
                                   "SAVE_BUTTON_NOT_FOUND", "SAVE_NOT_REFLECTED_OR_COLLATERAL"}]
    return 2 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
