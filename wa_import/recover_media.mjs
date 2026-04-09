/**
 * recover_media.mjs — Recover historical WA images using Baileys.
 *
 * TWO MODES:
 *
 *   node recover_media.mjs
 *     Default: uses existing .baileys_auth/ (no QR needed).
 *     Gets images from whatever recent history WA pushes on reconnect.
 *
 *   node recover_media.mjs --fresh
 *     Full historical recovery: backs up .baileys_auth/, deletes it,
 *     and links as a NEW device (one QR scan required).
 *     WhatsApp sends the complete message history with fresh media keys.
 *     After the QR scan, the new credentials REPLACE the old link — no
 *     additional linked-device slot is consumed.  The nightly pipeline
 *     automatically picks up the new credentials on its next run.
 *     Expect to receive 10–30+ batches covering years of group history.
 *
 * After either mode finishes:
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
import qrcode from "qrcode-terminal";
import pino from "pino";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

const TARGET_GROUP_JID   = "17069686133-1605817204@g.us";
const AUTH_DIR           = path.join(__dirname, ".baileys_auth");
const AUTH_BACKUP_DIR    = path.join(__dirname, ".baileys_auth_backup");
const MEDIA_DIR          = path.join(__dirname, "output", "media");
const LOG_PATH           = path.join(__dirname, "output", "recover_media_log.json");
const MSGS_PATH          = path.join(__dirname, "output", "messages.json");

const POST_SYNC_WAIT_MS      = 60_000;   // wait after last batch (ms)
const IMAGE_DOWNLOAD_TIMEOUT = 20_000;   // per-image timeout

const FRESH_MODE = process.argv.includes("--fresh");

fs.mkdirSync(MEDIA_DIR, { recursive: true });

// ── Load already-downloaded stanza IDs ───────────────────────────────────────
function loadAlreadyHave() {
  const have = new Set();
  for (const f of fs.readdirSync(MEDIA_DIR)) {
    have.add(path.basename(f, path.extname(f)));
  }
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
    const okCount = results.filter(r => r.status === "ok").length;
    process.stdout.write(`\r  ✅ ${okCount} recovered  (${stanzaId.slice(0,12)}…)`);
  } catch (err) {
    const status = err.message === "timeout"         ? "timeout"
                 : err.message.includes("403")       ? "cdn_expired"
                 : err.message.includes("410")       ? "cdn_expired"
                 : "error";
    results.push({ stanzaId, status, error: err.message });
  }
}

function printSummary(results) {
  const ok      = results.filter(r => r.status === "ok").length;
  const expired = results.filter(r => r.status === "cdn_expired").length;
  const timeout = results.filter(r => r.status === "timeout").length;
  const err     = results.filter(r => r.status === "error" || r.status === "empty").length;

  console.log(`\n\n✅ Done.`);
  console.log(`   Recovered:        ${ok}`);
  console.log(`   CDN expired:      ${expired}  (gone from WA servers — can't recover)`);
  console.log(`   Timed out:        ${timeout}`);
  console.log(`   Errors:           ${err}`);
  console.log(`   Output:           ${MEDIA_DIR}`);
  fs.writeFileSync(LOG_PATH, JSON.stringify(results, null, 2));
  if (ok > 0) {
    console.log("\n   Next steps:");
    console.log("     python -m wa_import.convert_to_rentals --save");
    console.log("     python -m dashboard.app.ingest_runner --mode full");
  }
}

// ── Main ─────────────────────────────────────────────────────────────────────
async function main() {
  if (FRESH_MODE) {
    console.log("\n📥 WA Media Recovery — FULL HISTORICAL MODE (--fresh)");
    console.log("────────────────────────────────────────────────────────");
    console.log("\n  This will:");
    console.log("  1. Back up your existing .baileys_auth/ credentials");
    console.log("  2. Unlink the current device (frees the slot, doesn't add one)");
    console.log("  3. Show a QR code — scan it to re-link as the same slot");
    console.log("  4. Download all historical images while WA sends the full sync");
    console.log("  5. Save new credentials — nightly pipeline uses them automatically\n");

    // Back up, then clear auth to force fresh device link
    if (fs.existsSync(AUTH_DIR)) {
      if (fs.existsSync(AUTH_BACKUP_DIR)) {
        fs.rmSync(AUTH_BACKUP_DIR, { recursive: true });
      }
      fs.cpSync(AUTH_DIR, AUTH_BACKUP_DIR, { recursive: true });
      console.log(`  ✅ Backed up .baileys_auth/ → .baileys_auth_backup/`);
      fs.rmSync(AUTH_DIR, { recursive: true });
      console.log(`  🗑️  Cleared .baileys_auth/ to force fresh device link\n`);
    }
    fs.mkdirSync(AUTH_DIR, { recursive: true });

  } else {
    console.log("\n📥 WA Media Recovery (existing auth — no QR needed)");
    console.log("────────────────────────────────────────────────────");
    if (!fs.existsSync(AUTH_DIR) || fs.readdirSync(AUTH_DIR).length === 0) {
      console.error("❌ No .baileys_auth/ found.");
      console.error("   Run the nightly pipeline first, or use --fresh to set up from scratch.");
      process.exit(1);
    }
  }

  const alreadyHave = loadAlreadyHave();
  console.log(`  Already have: ${alreadyHave.size} images on disk`);

  const results = [];
  let historySyncDone = false;
  let exitTimer = null;
  let batchCount = 0;
  let totalGroupImages = 0;

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  console.log(`  Baileys: ${version.join(".")}\n`);

  function scheduleExit() {
    if (exitTimer) clearTimeout(exitTimer);
    exitTimer = setTimeout(() => {
      printSummary(results);
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
      if (FRESH_MODE) {
        console.log("📱 Scan with WhatsApp → Settings → Linked Devices → Link a Device:\n");
        qrcode.generate(qr, { small: true });
        console.log("\n   (Waiting for scan…)");
      } else {
        // In normal mode, QR means auth expired — guide user
        console.log("⚠️  Auth expired. Run with --fresh to re-link:");
        console.log("   node wa_import/recover_media.mjs --fresh");
        process.exit(1);
      }
    }
    if (connection === "open") {
      if (FRESH_MODE) {
        console.log("\n✅ Linked! Waiting for WA to send full history sync…");
        console.log("   (Large groups can take 10–30 minutes)\n");
      } else {
        console.log("  ✅ Connected. Waiting for history…\n");
      }
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        if (FRESH_MODE) {
          console.log("❌ Logged out during re-link. Restoring backup auth…");
          if (fs.existsSync(AUTH_BACKUP_DIR)) {
            fs.rmSync(AUTH_DIR, { recursive: true, force: true });
            fs.cpSync(AUTH_BACKUP_DIR, AUTH_DIR, { recursive: true });
            console.log("   Restored. Nightly pipeline will continue working.");
          }
        }
        process.exit(1);
      }
      // Other disconnect — save and exit cleanly
      fs.writeFileSync(LOG_PATH, JSON.stringify(results, null, 2));
      if (historySyncDone) printSummary(results);
      process.exit(0);
    }
  });

  // ── History sync batches ─────────────────────────────────────────────────
  sock.ev.on("messaging-history.set", async ({ messages, isLatest }) => {
    batchCount++;
    const groupMsgs = messages.filter(m => m.key?.remoteJid === TARGET_GROUP_JID);
    const imgMsgs   = groupMsgs.filter(m => getContentType(m.message || {}) === "imageMessage");
    totalGroupImages += imgMsgs.length;

    process.stdout.write(
      `\r  📦 Batch #${batchCount} (+${imgMsgs.length} images, ${totalGroupImages} total)   `
    );

    for (const msg of groupMsgs) {
      await tryDownload(msg, alreadyHave, results);
    }

    if (isLatest) {
      historySyncDone = true;
      console.log(`\n\n  ✅ History sync complete — ${batchCount} batches, ${totalGroupImages} group images seen.`);
      scheduleExit();
    } else {
      // Reset timer on each batch — don't exit mid-sync
      if (exitTimer) { clearTimeout(exitTimer); exitTimer = null; }
    }
  });

  // ── Live messages ────────────────────────────────────────────────────────
  sock.ev.on("messages.upsert", async ({ messages }) => {
    for (const msg of messages) {
      if (msg.key?.remoteJid !== TARGET_GROUP_JID) continue;
      await tryDownload(msg, alreadyHave, results);
    }
    if (historySyncDone) scheduleExit();
  });

  // Safety timeout: 45 minutes
  setTimeout(() => {
    console.log("\n⏰ 45-minute safety timeout.");
    printSummary(results);
    process.exit(0);
  }, 45 * 60 * 1000);
}

main().catch(err => {
  console.error("Fatal:", err);
  process.exit(1);
});
