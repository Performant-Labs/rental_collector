/**
 * Step 3 (Playwright): Capture WA media via real browser session.
 * 
 * USAGE: node 3_playwright_capture.mjs
 * 
 * After QR scan:
 *  1. Manually click "A Community of Todos Santos" in the sidebar
 *  2. The script will start scrolling automatically
 *  3. Ctrl+C to stop — captured files are saved
 */

import { chromium } from "playwright";
import Database from "better-sqlite3";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import readline from "readline";

const __dirname  = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR = path.join(__dirname, "output", "media");
const DB_PATH    = path.join(__dirname, "ChatStorage.sqlite");
const LOG_PATH   = path.join(__dirname, "output", "playwright_capture_log.json");
const SCROLL_PAUSE_MS = 1000;
const SCROLL_PX       = 2500;

fs.mkdirSync(OUTPUT_DIR, { recursive: true });

// ── Build URL file-ID → filename map from DB ─────────────────────────────────
function buildUrlIndex() {
  const db = new Database(DB_PATH, { readonly: true });
  const rows = db.prepare(`
    SELECT mi.Z_PK as media_id, mi.ZMEDIAURL as url,
           m.ZMESSAGETYPE as msg_type, mi.ZTITLE as title
    FROM ZWAMEDIAITEM mi
    JOIN ZWAMESSAGE m ON m.ZMEDIAITEM = mi.Z_PK
    WHERE mi.ZMEDIAURL IS NOT NULL
  `).all();
  db.close();

  const TYPE_EXT = { 1:".jpg", 2:".mp4", 3:".ogg", 4:"", 7:".mp4", 14:".webp", 15:".webp" };
  const index = new Map();
  for (const r of rows) {
    try {
      const fileId = new URL(r.url).pathname.split("/").filter(Boolean).pop();
      const ext = TYPE_EXT[r.msg_type] ?? ".bin";
      const filename = (r.msg_type === 4 && r.title)
        ? `${r.media_id}_${r.title.replace(/[^a-zA-Z0-9._\- ]/g,"").slice(0,60)}`
        : `${r.media_id}${ext}`;
      index.set(fileId, filename);
    } catch (_) {}
  }
  console.log(`  DB index: ${index.size.toLocaleString()} media entries\n`);
  return index;
}

function waitForEnter(prompt) {
  return new Promise(resolve => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    rl.question(prompt, () => { rl.close(); resolve(); });
  });
}

async function main() {
  console.log("\n🎭 WA Media Capture via Playwright");
  console.log("─────────────────────────────────────\n");

  const urlIndex = buildUrlIndex();
  const captureLog = [];
  let captured = 0;
  let skipped  = 0;

  const SESSION_DIR = path.join(__dirname, ".playwright_session");
  const sessionExists = fs.existsSync(SESSION_DIR) && fs.readdirSync(SESSION_DIR).length > 0;
  fs.mkdirSync(SESSION_DIR, { recursive: true });

  if (sessionExists) {
    console.log("🔄 Resuming saved session — no QR scan needed.\n");
  } else {
    console.log("🆕 No saved session found — QR scan required (once only).\n");
  }

  const browser = await chromium.launchPersistentContext(SESSION_DIR, {
    headless: false,
    args: ["--disable-blink-features=AutomationControlled"],
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    viewport: { width: 1280, height: 900 },
  });

  const page = await browser.newPage();

  // ── Capture WA media via response event (works with Service Workers) ────────
  page.on("response", async (response) => {
    const url = response.url();
    // Match all WA CDN variants: mmg.whatsapp.net, media.whatsapp.net, *.cdn.whatsapp.net
    if (!url.includes(".whatsapp.net")) return;
    if (!response.ok()) return;
    try {
      const body = await response.body();
      if (body.length < 5120) return; // skip files < 5KB
      const fileId  = url.split("/").pop().split("?")[0];
      const filename = urlIndex.get(fileId) || `captured_${Date.now()}_${fileId.slice(0, 20)}`;
      const outPath  = path.join(OUTPUT_DIR, filename);
      if (!fs.existsSync(outPath)) {
        fs.writeFileSync(outPath, body);
        captureLog.push({ filename, bytes: body.length });
        captured++;
        console.log(`  ✅ [${captured}] ${filename}  (${(body.length / 1024).toFixed(0)}KB)`);
        if (captured % 20 === 0) fs.writeFileSync(LOG_PATH, JSON.stringify(captureLog, null, 2));
      } else {
        skipped++;
        if (skipped % 50 === 0) console.log(`  ⏭  ${skipped} files already exist`);
      }
    } catch (_) {}
  });

  // ── Open WA Web ──────────────────────────────────────────────────────────────
  console.log("🌐 Opening WhatsApp Web…");
  await page.goto("https://web.whatsapp.com", { waitUntil: "domcontentloaded" });

  // Wait for chats to load (flexible selector)
  console.log("⏳ Waiting for QR scan and chat list to appear…\n");
  await page.waitForFunction(() => {
    // Connected when we see the sidebar with chats
    return document.querySelector('[data-testid="chat-list"]') !== null
        || document.querySelector('div[aria-label="Chat list"]') !== null
        || document.querySelector('#side') !== null;
  }, { timeout: 300_000 }); // 5 min timeout for QR scan

  console.log("✅ Connected!\n");
  console.log("👉 ACTION REQUIRED:");
  console.log("   In the browser window, click on:");
  console.log('   "A Community of Todos Santos"');
  console.log("   (use the search box if needed)\n");

  await waitForEnter("   Press ENTER here once you have the group open and can see messages…\n");

  // ── Diagnose + scroll ────────────────────────────────────────────────────────
  // Move mouse to the conversation panel area (right half of screen)
  await page.mouse.move(800, 450);

  const panelInfo = await page.evaluate(() => {
    const scrollables = Array.from(document.querySelectorAll("*")).filter(el => {
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return (s.overflowY === "scroll" || s.overflowY === "auto")
        && el.scrollHeight > el.clientHeight
        && el.clientHeight > 200
        && r.left > 200;   // RIGHT panel only — ignore left sidebar
    });
    scrollables.sort((a, b) => b.scrollHeight - a.scrollHeight);
    const el = scrollables[0];
    if (!el) return null;
    el.setAttribute("data-wa-scroll-target", "1");
    const r = el.getBoundingClientRect();
    return {
      tag: el.tagName,
      id: el.id,
      cls: el.className.slice(0, 60),
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
      left: Math.round(r.left),
      top: Math.round(r.top),
    };
  });

  if (!panelInfo) {
    console.log("❌ No scrollable panel found in right half of screen.");
    console.log("   Make sure the group chat is open and messages are visible.\n");
  } else {
    console.log("✅ Scroll target found:");
    console.log(`   Tag:          ${panelInfo.tag}${panelInfo.id ? '#'+panelInfo.id : ''}`);
    console.log(`   Class:        ${panelInfo.cls}`);
    console.log(`   Position:     left=${panelInfo.left}px top=${panelInfo.top}px`);
    console.log(`   scrollTop:    ${panelInfo.scrollTop}`);
    console.log(`   scrollHeight: ${panelInfo.scrollHeight}`);
    console.log(`   clientHeight: ${panelInfo.clientHeight}\n`);
  }

  let scrollCount = 0;

  while (true) {
    // Primary: JS scrollTop on the tagged element
    const result = await page.evaluate(() => {
      const panel = document.querySelector("[data-wa-scroll-target]");
      if (!panel) return { ok: false, before: 0, after: 0 };
      const before = panel.scrollTop;
      panel.scrollTop -= 2500;
      // Also dispatch scroll event to trigger React handlers
      panel.dispatchEvent(new Event("scroll", { bubbles: true }));
      return { ok: true, before, after: panel.scrollTop };
    });

    // Backup: native mouse wheel at conversation panel position
    await page.mouse.wheel(0, -800);

    scrollCount++;

    // Log every 5 steps so we can see if scroll is working
    if (scrollCount <= 20 || scrollCount % 50 === 0) {
      const status = result.ok
        ? `scrollTop ${result.before} → ${result.after}`
        : `⚠️ panel not found`;
      console.log(`  [${scrollCount}] ${status} | captured=${captured}`);
    }

    await page.waitForTimeout(SCROLL_PAUSE_MS);
  }
}

main().catch(err => {
  console.error("\nError:", err.message);
  process.exit(1);
});

