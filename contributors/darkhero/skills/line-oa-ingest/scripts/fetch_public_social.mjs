#!/usr/bin/env node
/** Fetch public Instagram embed or Threads post text without a model API. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";

function normalizeUrl(url) {
  const match = url.match(/^https?:\/\/(?:www\.)?instagram\.com\/(p|reel|tv)\/([^/?#]+)/i);
  if (match) return [`https://www.instagram.com/${match[1].toLowerCase()}/${match[2]}/embed/captioned/`, "instagram"];
  if (/^https?:\/\/(?:www\.)?threads\.(?:com|net)\//i.test(url)) return [url, "threads"];
  return [url, "generic"];
}

function playwrightModule() {
  const candidates = [
    process.env.CODEX_NODE_MODULES,
    path.join(
      os.homedir(),
      ".cache",
      "codex-runtimes",
      "codex-primary-runtime",
      "dependencies",
      "node",
      "node_modules",
    ),
  ].filter(Boolean);
  for (const root of candidates) {
    if (!fs.existsSync(path.join(root, "playwright"))) continue;
    const fromRoot = createRequire(path.join(root, "line-oa-loader.cjs"));
    return fromRoot("playwright");
  }
  try {
    return createRequire(import.meta.url)("playwright");
  } catch {
    throw new Error("playwright_not_found");
  }
}

function parseArgs(argv) {
  const args = { url: "", includeText: false, out: "", maxChars: 20000, selfTest: false };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--include-text") args.includeText = true;
    else if (arg === "--out") args.out = argv[++i] || "";
    else if (arg === "--max-chars") args.maxChars = Number(argv[++i] || 20000);
    else if (arg === "--self-test") args.selfTest = true;
    else if (!args.url) args.url = arg;
    else throw new Error(`unknown_argument:${arg}`);
  }
  return args;
}

function selfTest() {
  const [ig, igPlatform] = normalizeUrl("https://www.instagram.com/p/AbC123/?x=1");
  if (ig !== "https://www.instagram.com/p/AbC123/embed/captioned/" || igPlatform !== "instagram") {
    throw new Error("instagram_normalize_failed");
  }
  const [threads, threadsPlatform] = normalizeUrl("https://www.threads.com/share/example/");
  if (threads !== "https://www.threads.com/share/example/" || threadsPlatform !== "threads") {
    throw new Error("threads_normalize_failed");
  }
  return { ok: true, checks: 2 };
}

async function launchBrowser(chromium) {
  try {
    return await chromium.launch({ channel: "msedge", headless: true });
  } catch {
    return await chromium.launch({ headless: true });
  }
}

async function fetchPublic(url, maxChars) {
  const [target, platform] = normalizeUrl(url);
  const { chromium } = playwrightModule();
  const browser = await launchBrowser(chromium);
  try {
    const context = await browser.newContext({
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      locale: "zh-TW",
    });
    const page = await context.newPage();
    const response = await page.goto(target, { waitUntil: "domcontentloaded", timeout: 30000 }).catch(() => null);
    await page.waitForTimeout(3000);
    const data = await page.evaluate(() => {
      const meta = (name) =>
        document.querySelector(`meta[property="${name}"],meta[name="${name}"]`)?.getAttribute("content") || "";
      return {
        title: meta("og:title") || document.title || "",
        description: meta("og:description") || meta("description") || "",
        text: document.body?.innerText || "",
      };
    });
    const text = [data.description, data.text]
      .filter(Boolean)
      .join("\n")
      .replace(/\r/g, "")
      .slice(0, maxChars);
    const finalUrl = page.url();
    const browserError =
      finalUrl.startsWith("chrome-error://") ||
      !response ||
      /ERR_[A-Z_]+|network access.*blocked|網際網路存取已封鎖/i.test(text);
    const thin = browserError || text.trim().length < 80 || /^(Instagram|Threads)\s*$/i.test(text.trim());
    return {
      schema: 1,
      source_url: url,
      request_url: target,
      final_url: finalUrl,
      platform,
      status_code: response?.status() || 0,
      status: thin ? "unfetchable" : "ok",
      error: browserError ? "browser_network_error" : undefined,
      title: data.title,
      chars: text.length,
      text,
    };
  } finally {
    await browser.close();
  }
}

const args = parseArgs(process.argv.slice(2));
let result;
let exitCode = 0;
try {
  if (args.selfTest) result = selfTest();
  else if (!args.url) throw new Error("url_required");
  else {
    result = await fetchPublic(args.url, args.maxChars);
    if (result.status !== "ok") exitCode = 2;
  }
} catch (error) {
  result = {
    schema: 1,
    source_url: args.url || null,
    status: "unfetchable",
    error: error instanceof Error ? error.message : String(error),
  };
  exitCode = 2;
}
if (!args.includeText && result && typeof result === "object") delete result.text;
const rendered = `${JSON.stringify(result, null, 2)}\n`;
if (args.out) {
  fs.mkdirSync(path.dirname(path.resolve(args.out)), { recursive: true });
  fs.writeFileSync(args.out, rendered, "utf8");
}
process.stdout.write(rendered);
process.exitCode = exitCode;
