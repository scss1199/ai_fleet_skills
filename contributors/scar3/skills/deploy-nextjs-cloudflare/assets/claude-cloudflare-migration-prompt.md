# 給 Claude 的 Cloudflare 全站搬遷提示詞

你現在要把 `C:\ai_workspace` 內其餘可上線的網站／線上服務，從 Vercel、Fly.io、Firebase Hosting 或本機部署，逐一搬到我的 Cloudflare Workers 帳號。不要只做示範頁、靜態佔位頁或代理頁；每個完成項目都必須是原專案的真實網站，而且公開 URL 要能正常開啟。

## 固定條件

- Cloudflare account ID：`3024c6a374db2b7e605510f8da5f159e`
- 帳號 workers.dev 子網域：`kyloren.workers.dev`
- Worker 命名規則：專案資料夾名轉小寫、底線改連字號；若原名不是 `ai_` 開頭則補 `ai-`。
  - `ai_busker` → `ai-busker` → `https://ai-busker.kyloren.workers.dev/`
  - `jci_taipei` → `ai-jci-taipei` → `https://ai-jci-taipei.kyloren.workers.dev/`
- `ai_eatery` 已完成，跳過：`https://ai-eatery.kyloren.workers.dev/`
- `fracdigi` 為 T1 凍結、本座位不承辦，完全跳過，不可部署、改 DNS、改 webhook 或改 OAuth。
- 優先順序：先 `C:\ai_workspace\jci_taipei`，再處理其餘最小、相依最少的網站。

## 必須採用的流程

1. 先完整閱讀並使用共享 SSOT `C:\ai_workspace\_skill\fleet-skills\deploy-nextjs-cloudflare\SKILL.md`；同時遵守每個專案根目錄的 `AGENTS.md`、`CLAUDE.md` 與該專案點名的 skills。所有隔離副本、建置產物與證據也只能放在 `C:\ai_workspace` 內。
2. 掃描 `C:\ai_workspace`，只挑出真正含網站或線上 HTTP 服務的專案。先產生清單，標記框架、現有正式網域、webhook、OAuth callback、cron、資料庫、物件儲存、長連線／背景工作與必要環境變數；不是網站的專案不要硬部署。
3. 原始工作樹若有任何未提交變更，一律建立隔離副本部署；不得覆蓋、刪除、還原或混入使用者現有變更。隔離副本不得包含 `.git`、`.env*`、`.secrets`、憑證、token、cache、測試截圖、建置產物。
4. 採「本機建置優先」。所有 dependency install、Next.js/SWC、OpenNext、壓縮、workerd 與 dry-run 都在 darkhero 執行；Cloudflare 只接收已建好的成品並提供 Worker runtime、edge assets、DNS／custom domain 與 `kyloren.workers.dev`。不得啟用 Cloudflare Workers Builds、Git integration 或 Deploy Hooks，除非本機明確無法產生成品且先停下說明原因。這樣不消耗 Cloudflare hosted build minutes。
5. Next.js 專案使用 OpenNext for Cloudflare Workers；其他框架選 Cloudflare 官方相容方式。先原生 production build，再 Cloudflare build，再 `wrangler deploy --dry-run --outdir .wrangler-dry-run`。記錄各階段耗時與 gzip 成品大小。darkhero 的 fracdigi 實測基準是 `cf:build` 59.67 秒、dry-run 3.52 秒、增量 upload/deploy 21.31 秒；一般專案從已安裝依賴到公開上線可先用約 1–2 分鐘估算，首次下載依賴另計。
6. 不要混淆「Cloudflare hosted build minutes」與「Worker 壓縮後成品大小」。本機建置可以把 hosted build minutes 降為 0，但不能繞過免費方案的 Worker gzip 上限、startup、runtime CPU／RAM、request 或 static asset 限制。超限時要移除無用依賴、tree-shake/minify、把靜態／二進位資料移到 Static Assets/R2/KV/D1，或拆成多個 Worker＋service bindings；不可假稱換成本機編譯就能上傳超限成品。
7. darkhero 的 i9-14900K、約 96 GiB RAM 與 Samsung 990 Pro NVMe 是主要建置資源。A770/A310 對一般 Next.js、SWC、esbuild、OpenNext 編譯沒有可預期加速；除非專案有明確 GPU asset pipeline，不要安裝 GPU 工具或用 GPU 當部署必要條件。
8. Cloudflare 已登入；直接用現有 Wrangler/OAuth 狀態執行，不要叫我重登，不要聲稱「開啟的分頁已登入」卻沒有完成。若真的遇到 OAuth 或 console-only 設定，使用可持續的瀏覽器自動化完成。
9. 所有 secret 只可從既有安全來源讀取後，用 stdin／secret bulk 上傳；禁止把值印到終端、對話、報告、Git 或一般設定檔。公開 Firebase web config 可作 build-time public env，但仍不得把伺服器私鑰打進前端 bundle。
10. 每個站先在本機 workerd 驗證，再部署到固定 workers.dev URL。公開驗證至少包含：首頁、登入頁、主要 API health/config、靜態資源、404／權限邊界；有 webhook 的站另測正確 HTTP method、壞簽章拒絕、provider challenge 與真實事件收件。
11. 每個專案搜尋全部外部 URL 與 provider 設定。若 workers.dev 是正式入口，要同步更新 Meta、LINE、Google、GitHub、Stripe 等 webhook／OAuth callback／allowed origin／authorized domain；若專案有自己的付費公司網域，保留公司網域為 canonical，只將 Worker 當 origin／備援，並在驗證完成後才切 DNS。
12. Vercel cron、scheduled function、queue、Durable Object、WebSocket、檔案系統寫入或超過 Worker 限制的功能，必須逐項遷移或提供可驗證的等價架構。不能把「首頁 200」當作整站完成。
13. 遇到新型部署失敗，立即把「症狀、根因、安全修復、重試規則」回寫 `deploy-nextjs-cloudflare` skill 的 `references/known-failures.md`，必要時同步修改 skill/script，並執行 skill quick validation。這是 MTM 必要產物。
14. 不要一直回報步驟或要求我確認一般操作。只有下列情況才停下討論：需要付費、會造成不可逆資料／DNS 中斷、缺少無法取得的帳密、provider 明確要求真人驗證、或架構確實無法在 Cloudflare 等價運行。

## 完成標準

每一個標成完成的專案都要同時滿足：

- 固定 `https://ai-<name>.kyloren.workers.dev/` 可公開開啟，且不是 placeholder。
- 原網站的核心頁面與線上服務可用。
- secret、資料庫、OAuth、webhook、cron／背景工作均已驗證或清楚標示為不適用。
- 使用無 cookie 與一般瀏覽器各做一次公開 smoke test；回應沒有 5xx、資源沒有整批 404。
- 產出可重跑的部署設定與 MTM/PFKT 證據。

最後只交付一張結果表：`專案 | 原始路徑 | Cloudflare URL | 核心功能驗證 | webhook/OAuth/cron | 狀態 | 唯一剩餘阻礙`。URL 必須是可點擊且當下實測可通。失敗或未完整遷移的項目不可寫「完成」。
