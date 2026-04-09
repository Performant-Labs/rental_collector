/**
 * recover_media.mjs — Recover historical WA images using existing Baileys auth.
 *
 * No QR scan required — uses the existing .baileys_auth/ from the nightly
 * pipeline.
 *
 * STRATEGY:
 *   When Baileys reconnects with saved credentials, WhatsApp pushes a recent-
 *   history sync (messaging-history.set) covering roughly the last 90 days of
 *   messages, each with fresh mediaKey included in the proto. This script:
 *     1. Connects with saved auth (no QR needed)
 *     2. Listens for messaging-history.set events
 *     3. For each image message in the target group, calls downloadMediaMessage()
 *        while the media key is fresh in memory
 *     4. Saves as {stanza_id}.jpg  (auto-linked by convert_to_rentals.py)
 *     5. Exits after history sync completes + 30s wait for stragglers
 *
 * USAGE:
 *   node wa_import/recover_media.mjs
 *
 * After it finishes:
 *   python -m wa_import.convert_to_rentals --save
 *   python -m dashboard.app.ingest_runner --mode full
 */

import makeWASocket, {
  useMultiFileAuthState,
  downloadMediaMessage,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
  getContentType,
} from "@whiskeysockets/baileys";
import pino from "pino";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const TARGET_GROUP_JID = "17069686133-1605817204@g.us";
const AUTH_DIR    = path.join(__dirname, ".baileys_auth");
const MEDIA_DIR   = path.join(__dirname, "output", "media");
const LOG_PATH    = path.join(__dirname, "output", "recover_media_log.json");
const MSGS_PATH   = path.join(__dirname, "output", "messages.json");

const POST_SYNC_WAIT_MS      = 30_000;  // wait after sync for stragglers
const IMAGE_DOWNLOAD_TIMEOUT = 15_000;  // per-image timeout

fs.mkdirSync(MEDIA_DIR, { recursive: true });

// ── Load already-downloaded stanza IDs (avoid re-downloading) ────────────────
function loadAlreadyHave() {
  const have = new Set();
  // Files from Baileys nightly: {stanza_id}.jpg (hex strings)
  for (const f of fs.readdirSync(MEDIA_DIR)) {
    have.add(path.basename(f, path.extname(f)));
  }
  // Also check messages.json for media_local_path already set
  if (fs.existsSync(MSGS_PATH)) {
    const msgs = JSON.parse(fs.readFileSync(MSGS_PATH, "utf8"));
    for (const m of msgs) {
      if (m.stanza_id && m.media_local_path) have.add(m.stanza_id);
    }
  }
  return have;
}

// ── Download a single image message ─────────────────────────────────────────
async function tryDownload(msg, alreadyHave, results) {
  const stanzaId = msg.key?.id;
  if (!stanzaId) return;
  if (alreadyHave.has(stanzaId)) return;

  const contentType = msg.message ? getContentType(msg.message) : null;
  if (contentType !== "imageMessage") return;

  const outPath = path.join(MEDIA_DIR, `${stanzaId}.jpg`);
  if (fs.existsSync(outPath)) { alreadyHave.add(stanzaId); return; }

  try {
    const download = downloadMediaMessage(msg, "buffer", {});
    const timeout  = new Promise((_, rej) =>
      setTimeout(() => rej(new Error("timeout")), IMAGE_DOWNLOAD_TIMEOUT)
    );
    const buf = await Promise.race([download, timeout]);
    if (!buf || buf.length < 1024) {
      results.push({ stanzaId, status: "empty" });
      return;
    }
    fs.writeFileSync(outPath, buf);
    alreadyHave.add(stanzaId);
    results.push({ stanzaId, status: "ok", bytes: buf.length });
    process.stdout.write(`\r  ✅ ${results.filter(r => r.status === "ok").length} recovered  (${stanzaId.slice(0,12)}…)`);
  } catch (err) {
    const status = err.message === "timeout" ? "timeout"
      : err.message.includes("403") ? "cdn_expired"
      : "error";
    results.push({ stanzaId, status, error: err.message });
  }
}

// ── Main ─────────────────────────────────────────────────────────────────────
async function main() {
  console.log("\n📥 WA Media Recovery (no QR scan needed)");
  console.log("─────────────────────────────────────────\n");

  if (!fs.existsSync(AUTH_DIR) || fs.readdirSync(AUTH_DIR).length === 0) {
    console.error("❌ No .baileys_auth/ found. Run the nightly pipeline first to set up auth.");
    process.exit(1);
  }

  const alreadyHave = loadAlreadyHave();
  console.log(`  Already have: ${alreadyHave.size} stanza IDs on disk or in messages.json`);

  const results = [];
  let historySyncDone = false;
  let exitTimer = null;
  let batchCount = 0;

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  console.log(`  Baileys version: ${version.join(".")}`);
  console.log(`  Connecting with saved auth (no QR needed)…\n`);

  function scheduleExit() {
    if (exitTimer) clearTimeout(exitTimer);
    exitTimer = setTimeout(() => {
      const ok    = results.filter(r => r.status === "ok").length;
      const skip  = results.filter(r => r.status === "timeout" || r.status === "cdn_expired").length;
      const err   = results.filter(r => r.status === "error" || r.status === "empty").length;
      console.log(`\n\n✅ Done.`);
      console.log(`   Recovered:   ${ok}`);
      console.log(`   CDN expired: ${skip}  (permanently gone from WA servers)`);
      console.log(`   Errors:      ${err}`);
      console.log(`   Output dir:  ${MEDIA_DIR}`);
      fs.writeFileSync(LOG_PATH, JSON.stringify(results, null, 2));
      if (ok > 0) {
        console.log("\n   Next steps:");
        console.log("     python -m wa_import.convert_to_rentals --save");
        console.log("     python -m dashboard.app.ingest_runner --mode full");
      }
      process.exit(0);
    }, POST_SYNC_WAIT_MS);
  }

  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
    browser: Browsers.macOS("Desktop"),
    syncFullHistory: true,
    markOnlineOnConnect: false,
    getMessage: async () => undefined,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
    if (qr) {
      // Shouldn't happen with saved auth, but surface it clearly if it does
      console.log("⚠️  QR code requested — your saved auth may have expired.");
      console.log("   Re-run the nightly pipeline (docker compose up wa-exporter) to refresh auth.");
      process.exit(1);
    }
    if (connection === "open") {
      console.log("  ✅ Connected. Waiting for WA history sync…\n");
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        console.log("❌ Logged out. Run nightly pipeline to re-link.");
        process.exit(1);
      }
      // Other disconnects — don't retry, just exit cleanly
      console.log("  ℹ️  Disconnected. Saving results…");
      fs.writeFileSync(LOG_PATH, JSON.stringify(results, null, 2));
      process.exit(0);
    }
  });

  // ── History sync (bulk) ──────────────────────────────────────────────────
  sock.ev.on("messaging-history.set", async ({ messages, isLatest }) => {
    batchCount++;
    const groupMsgs = messages.filter(m => m.key?.remoteJid === TARGET_GROUP_JID);
    console.log(`  📦 Batch #${batchCount}: ${messages.length} total, ${groupMsgs.length} in group`);

    for (const msg of groupMsgs) {
      await tryDownload(msg, alreadyHave, results);
    }

    if (isLatest) {
      historySyncDone = true;
      console.log(`\n  ✅ History sync complete (${batchCount} batches).`);
      scheduleExit();
    }
  });

  // ── Live messages that arrive while connected ────────────────────────────
  sock.ev.on("messages.upsert", async ({ messages }) => {
    for (const msg of messages) {
      if (msg.key?.remoteJid !== TARGET_GROUP_JID) continue;
      await tryDownload(msg, alreadyHave, results);
    }
    if (historySyncDone) scheduleExit();
  });

  // Safety timeout: 30 minutes
  setTimeout(() => {
    console.log("\n⏰ 30-minute safety timeout. Saving and exiting…");
    fs.writeFileSync(LOG_PATH, JSON.stringify(results, null, 2));
    process.exit(0);
  }, 30 * 60 * 1000);
}

main().catch(err => {
  console.error("Fatal:", err);
  process.exit(1);
});
