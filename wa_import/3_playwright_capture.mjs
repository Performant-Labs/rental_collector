/**
 * Step 3 (Playwright): Capture WA media via real browser session.
 *
 * Scrolls back through "A Community of Todos Santos" in WhatsApp Web,
 * intercepts every CDN image response, and saves it as {stanza_id}.jpg
 * so it is automatically linked to listings by convert_to_rentals.py.
 *
 * NO SQLite database required — uses messages.json for the URL→stanza_id
 * index.  All captured files use the same naming convention as Baileys:
 *   output/media/{stanza_id}.jpg
 *
 * USAGE:
 *   node 3_playwright_capture.mjs
 *
 * First run: a browser window opens → scan the QR code once.
 *   (.playwright_session/ is saved so subsequent runs skip the QR scan)
 *
 * Once connected:
 *   1. Click "A Community of Todos Santos" in the sidebar
 *   2. Press ENTER in this terminal → auto-scroll begins
 *   3. Ctrl+C to stop safely (checkpoint is saved)
 *
 * After capturing, run:
 *   python -m wa_import.convert_to_rentals --save
 *   python -m dashboard.app.ingest_runner --mode full
 */

import { chromium } from "playwright";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import readline from "readline";

const __dirname   = path.dirname(fileURLToPath(import.meta.url));
const OUTPUT_DIR  = path.join(__dirname, "output", "media");
const MSGS_PATH   = path.join(__dirname, "output", "messages.json");
const LOG_PATH    = path.join(__dirname, "output", "playwright_capture_log.json");
const SESSION_DIR = path.join(__dirname, ".playwright_session");

const SCROLL_PAUSE_MS = 1200;   // pause between scroll steps (ms)
const SCROLL_PX       = 2500;   // pixels to scroll up per step

fs.mkdirSync(OUTPUT_DIR,  { recursive: true });
fs.mkdirSync(SESSION_DIR, { recursive: true });

// ── Build URL path-segment → {stanza_id, filename} index from messages.json ──
//
// WA CDN URLs look like:
//   https://mmg.whatsapp.net/v/t62.7118-24/{filePathId}?ccb=…&oh=…&oe=…
//
// The path segment (filePathId) is stable — it doesn't change when the URL
// is refreshed.  We match the fresh URL intercepted from WA Web against the
// expired URL stored in messages.json using just that path segment.
//
function buildUrlIndex() {
  if (!fs.existsSync(MSGS_PATH)) {
    console.warn(`  ⚠️  ${MSGS_PATH} not found — running without URL index.`);
    console.warn(`     Files will be saved as captured_TIMESTAMP_fileId.`);
    return new Map();
  }

  const msgs = JSON.parse(fs.readFileSync(MSGS_PATH, "utf8"));
  const index = new Map(); // pathSegment → stanza_id

  for (const m of msgs) {
    const stanzaId = m.stanza_id;
    const url = m.media_url;
    if (!stanzaId || !url || m.type_int !== 1) continue; // images only
    try {
      // Extract the last path segment before the query string
      const pathSeg = new URL(url).pathname.split("/").filter(Boolean).pop();
      if (pathSeg) index.set(pathSeg, stanzaId);
    } catch (_) {}
  }

  console.log(`  messages.json index: ${index.size.toLocaleString()} image URL entries`);
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
  console.log("───────────────────────────────────\n");

  const urlIndex   = buildUrlIndex();
  const captureLog = [];
  let captured = 0;
  let skipped  = 0;

  const sessionExists = fs.readdirSync(SESSION_DIR).length > 0;
  if (sessionExists) {
    console.log("🔄 Resuming saved browser session — no QR scan needed.\n");
  } else {
    console.log("🆕 No saved session — one-time QR scan required.\n");
  }

  const browser = await chromium.launchPersistentContext(SESSION_DIR, {
    headless: false,
    args: ["--disable-blink-features=AutomationControlled"],
    userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    viewport: { width: 1280, height: 900 },
  });

  const page = await browser.newPage();

  // ── Intercept WA CDN responses ───────────────────────────────────────────────
  page.on("response", async (response) => {
    const url = response.url();
    if (!url.includes(".whatsapp.net")) return;
    if (!response.ok()) return;

    try {
      const body = await response.body();
      if (body.length < 5120) return;   // skip < 5 KB (thumbnails, etc.)

      // Extract stable path segment from the URL
      const pathSeg = new URL(url).pathname.split("/").filter(Boolean).pop();

      let filename;
      if (pathSeg && urlIndex.has(pathSeg)) {
        // Known message → save as {stanza_id}.jpg (links automatically to listing)
        filename = `${urlIndex.get(pathSeg)}.jpg`;
      } else {
        // Unknown URL (e.g. profile photos, status) → save with timestamp prefix
        filename = `captured_${Date.now()}_${(pathSeg || "unknown").slice(0, 24)}`;
      }

      const outPath = path.join(OUTPUT_DIR, filename);
      if (!fs.existsSync(outPath)) {
        fs.writeFileSync(outPath, body);
        captureLog.push({ filename, url, bytes: body.length });
        captured++;
        const kb = (body.length / 1024).toFixed(0);
        const linked = urlIndex.has(pathSeg) ? "✅" : "💾";
        console.log(`  ${linked} [${captured}] ${filename}  (${kb} KB)`);
        if (captured % 20 === 0) {
          fs.writeFileSync(LOG_PATH, JSON.stringify(captureLog, null, 2));
          console.log(`  ── checkpoint: ${captured} captured so far ──`);
        }
      } else {
        skipped++;
        if (skipped % 50 === 0) console.log(`  ⏭  ${skipped} already exist`);
      }
    } catch (_) {}
  });

  // ── Open WA Web ──────────────────────────────────────────────────────────────
  console.log("🌐 Opening WhatsApp Web…");
  await page.goto("https://web.whatsapp.com", { waitUntil: "domcontentloaded" });

  console.log("⏳ Waiting for chat list (scan QR if needed)…\n");
  await page.waitForFunction(() =>
    document.querySelector('[data-testid="chat-list"]') !== null
    || document.querySelector('div[aria-label="Chat list"]') !== null
    || document.querySelector("#side") !== null
  , { timeout: 300_000 });

  console.log("✅ Connected!\n");
  console.log("👉 ACTION REQUIRED:");
  console.log('   Click "A Community of Todos Santos" in the sidebar.');
  console.log("   (use the search box if needed)\n");

  await waitForEnter("   Press ENTER once you can see the chat messages…\n");

  // ── Find the scrollable message panel ────────────────────────────────────────
  await page.mouse.move(800, 450);
  const panelInfo = await page.evaluate(() => {
    const scrollables = Array.from(document.querySelectorAll("*")).filter(el => {
      const s = getComputedStyle(el);
      const r = el.getBoundingClientRect();
      return (s.overflowY === "scroll" || s.overflowY === "auto")
        && el.scrollHeight > el.clientHeight
        && el.clientHeight > 200
        && r.left > 200;   // right panel only
    });
    scrollables.sort((a, b) => b.scrollHeight - a.scrollHeight);
    const el = scrollables[0];
    if (!el) return null;
    el.setAttribute("data-wa-scroll-target", "1");
    return {
      scrollTop: el.scrollTop, scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    };
  });

  if (!panelInfo) {
    console.log("❌ No scrollable panel found — make sure the group chat is open.");
  } else {
    console.log(`✅ Scroll target found (scrollHeight=${panelInfo.scrollHeight})\n`);
    console.log(`   Scrolling up through history — Ctrl+C to stop.\n`);
  }

  // ── Auto-scroll loop ─────────────────────────────────────────────────────────
  let scrollCount = 0;
  process.on("SIGINT", () => {
    fs.writeFileSync(LOG_PATH, JSON.stringify(captureLog, null, 2));
    console.log(`\n\n✅ Stopped.  ${captured} images captured, ${skipped} already existed.`);
    console.log(`   Log: ${LOG_PATH}`);
    console.log("\n   Next steps:");
    console.log("     python -m wa_import.convert_to_rentals --save");
    console.log("     python -m dashboard.app.ingest_runner --mode full\n");
    process.exit(0);
  });

  while (true) {
    await page.evaluate(() => {
      const panel = document.querySelector("[data-wa-scroll-target]");
      if (!panel) return;
      panel.scrollTop -= 2500;
      panel.dispatchEvent(new Event("scroll", { bubbles: true }));
    });
    await page.mouse.wheel(0, -800);   // backup — triggers WA lazy-load

    scrollCount++;
    if (scrollCount <= 10 || scrollCount % 100 === 0) {
      console.log(`  [scroll #${scrollCount}] captured=${captured} skipped=${skipped}`);
    }

    await page.waitForTimeout(SCROLL_PAUSE_MS);
  }
}

main().catch(err => {
  console.error("\nError:", err.message);
  process.exit(1);
});
