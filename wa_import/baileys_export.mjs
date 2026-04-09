/**
 * baileys_export.mjs — Container-friendly WhatsApp message exporter.
 *
 * Connects to WhatsApp Web via Baileys, receives full history sync for the
 * target group, downloads image media, and writes output/messages.json in
 * the exact schema that 4_find_rentals.py expects.
 *
 * First run:  docker compose run wa-exporter   (interactive, scan QR)
 * Later runs: docker compose up  wa-exporter   (uses saved auth)
 *
 * To force a full re-sync, delete .baileys_auth/ and re-scan QR.
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

// ── Config ───────────────────────────────────────────────────────────────────
const TARGET_GROUP_JID = "17069686133-1605817204@g.us";
const OUTPUT_DIR       = path.join(__dirname, "output");
const MEDIA_DIR        = path.join(OUTPUT_DIR, "media");
const AUTH_DIR         = path.join(__dirname, ".baileys_auth");
const MESSAGES_PATH    = path.join(OUTPUT_DIR, "messages.json");
const CHECKPOINT_PATH  = path.join(OUTPUT_DIR, "baileys_export_checkpoint.json");

// How long to wait after history sync completes to catch stragglers (ms)
const POST_SYNC_WAIT_MS = 30_000;
// Save checkpoint every N messages
const CHECKPOINT_INTERVAL = 200;
// Timeout for individual image downloads (ms)
const IMAGE_DOWNLOAD_TIMEOUT_MS = 15_000;

// Message type mapping (matches 1_export_messages.py schema)
const TYPE_MAP = {
  conversation:           { type_int: 0,  type: "text" },
  extendedTextMessage:    { type_int: 0,  type: "text" },
  imageMessage:           { type_int: 1,  type: "image" },
  videoMessage:           { type_int: 2,  type: "video" },
  audioMessage:           { type_int: 3,  type: "audio" },
  documentMessage:        { type_int: 4,  type: "document" },
  contactMessage:         { type_int: 5,  type: "contact" },
  contactsArrayMessage:   { type_int: 5,  type: "contact" },
  locationMessage:        { type_int: 6,  type: "location" },
  liveLocationMessage:    { type_int: 6,  type: "location" },
  stickerMessage:         { type_int: 14, type: "sticker" },
  reactionMessage:        { type_int: 66, type: "reaction" },
  pollCreationMessage:    { type_int: 26, type: "poll" },
  pollCreationMessageV3:  { type_int: 26, type: "poll" },
  protocolMessage:        { type_int: 8,  type: "group_notification" },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function toIso(epoch) {
  if (!epoch) return null;
  // Baileys gives Unix epoch seconds (or Long objects)
  const ts = typeof epoch === "object" && epoch.low !== undefined
    ? epoch.low + (epoch.high || 0) * 4294967296
    : Number(epoch);
  if (!ts || ts < 0) return null;
  return new Date(ts * 1000).toISOString();
}

function extractText(msg) {
  if (!msg.message) return null;
  const m = msg.message;
  return m.conversation
    || m.extendedTextMessage?.text
    || m.imageMessage?.caption
    || m.videoMessage?.caption
    || m.documentMessage?.title
    || m.contactMessage?.displayName
    || m.locationMessage?.name
    || null;
}

function extractMediaInfo(msg) {
  if (!msg.message) return {};
  const m = msg.message;
  const media = m.imageMessage || m.videoMessage || m.audioMessage
             || m.documentMessage || m.stickerMessage;
  if (!media) return {};
  return {
    media_url:      media.url || media.directPath || null,
    media_file_size: media.fileLength
      ? Number(typeof media.fileLength === "object" ? media.fileLength.low : media.fileLength)
      : null,
    media_duration: media.seconds ? Number(media.seconds) : null,
    media_title:    media.caption || media.title || media.fileName || null,
    has_media_key:  media.mediaKey ? 1 : 0,
    latitude:       null,
    longitude:      null,
  };
}

function extractLocation(msg) {
  if (!msg.message) return {};
  const loc = msg.message.locationMessage || msg.message.liveLocationMessage;
  if (!loc) return {};
  return {
    latitude:  loc.degreesLatitude || null,
    longitude: loc.degreesLongitude || null,
  };
}

function extractContact(msg) {
  if (!msg.message) return {};
  const c = msg.message.contactMessage;
  if (!c) return {};
  return {
    vcard_name:   c.displayName || null,
    vcard_string: c.vcard || null,
  };
}

/**
 * Convert a Baileys WAMessage to the flat schema expected by
 * 4_find_rentals.py / convert_to_rentals.py.
 */
function mapMessage(msg, seqId) {
  const contentType = msg.message ? getContentType(msg.message) : null;
  const typeInfo = TYPE_MAP[contentType] || { type_int: 0, type: contentType || "unknown" };
  const mediaInfo = extractMediaInfo(msg);
  const locInfo = extractLocation(msg);
  const contactInfo = extractContact(msg);

  const senderJid = msg.key?.participant || msg.key?.remoteJid || null;

  return {
    id:                  seqId,
    stanza_id:           msg.key?.id || null,
    type_int:            typeInfo.type_int,
    from_jid:            senderJid,
    sender_name:         msg.pushName || null,
    is_from_me:          msg.key?.fromMe || false,
    text:                extractText(msg),
    status:              msg.status || 0,
    starred:             msg.starred || false,
    flags:               0,
    reply_to_id:         msg.message?.extendedTextMessage?.contextInfo?.stanzaId || null,

    // Media fields
    media_id:            null,   // We use stanza_id-based filenames instead
    media_url:           mediaInfo.media_url || null,
    media_local_path:    null,   // Set after download
    thumbnail_local_path: null,
    media_file_size:     mediaInfo.media_file_size || null,
    media_duration:      mediaInfo.media_duration || null,
    media_title:         mediaInfo.media_title || null,
    media_cloud_status:  null,
    latitude:            locInfo.latitude || null,
    longitude:           locInfo.longitude || null,
    vcard_name:          contactInfo.vcard_name || null,
    vcard_string:        contactInfo.vcard_string || null,
    has_media_key:       mediaInfo.has_media_key || 0,

    // Timestamps
    timestamp:           toIso(msg.messageTimestamp),
    sent_at:             null,
    media_url_date:      null,
    type:                typeInfo.type,
  };
}

// ── Media download (images only) ─────────────────────────────────────────────

async function downloadImage(msg, stanzaId) {
  if (!msg.message?.imageMessage) return null;

  const filename = `${stanzaId}.jpg`;
  const outPath = path.join(MEDIA_DIR, filename);

  if (fs.existsSync(outPath)) return filename;

  try {
    // Race the download against a timeout to prevent hanging on dead CDNs
    const downloadPromise = downloadMediaMessage(msg, "buffer", {});
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error("timeout")), IMAGE_DOWNLOAD_TIMEOUT_MS)
    );
    const buffer = await Promise.race([downloadPromise, timeoutPromise]);
    if (buffer && buffer.length > 500) {
      fs.writeFileSync(outPath, buffer);
      return filename;
    }
  } catch {
    // CDN expired, unavailable, or timed out — skip silently
  }
  return null;
}

// ── Checkpoint / merge ───────────────────────────────────────────────────────

function loadExisting() {
  if (!fs.existsSync(MESSAGES_PATH)) return new Map();
  try {
    const data = JSON.parse(fs.readFileSync(MESSAGES_PATH, "utf8"));
    const map = new Map();
    for (const m of data) {
      if (m.stanza_id) map.set(m.stanza_id, m);
    }
    return map;
  } catch {
    return new Map();
  }
}

function saveMessages(msgMap) {
  const sorted = [...msgMap.values()].sort((a, b) => {
    const ta = a.timestamp || "";
    const tb = b.timestamp || "";
    return ta < tb ? -1 : ta > tb ? 1 : 0;
  });
  // Re-number sequential IDs
  sorted.forEach((m, i) => { m.id = i + 1; });
  fs.writeFileSync(MESSAGES_PATH, JSON.stringify(sorted, null, 2));
  return sorted.length;
}

function loadCheckpoint() {
  if (!fs.existsSync(CHECKPOINT_PATH)) return {};
  try {
    return JSON.parse(fs.readFileSync(CHECKPOINT_PATH, "utf8"));
  } catch {
    return {};
  }
}

function saveCheckpoint(data) {
  fs.writeFileSync(CHECKPOINT_PATH, JSON.stringify(data, null, 2));
}

// ── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  fs.mkdirSync(MEDIA_DIR, { recursive: true });
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const existing = loadExisting();
  const checkpoint = loadCheckpoint();
  let newCount = 0;
  let imageCount = 0;
  let batchCount = 0;
  let historySyncDone = false;
  let exitTimer = null;
  let exitLogShown = false;
  let reconnectCount = 0;
  let lastOpenTime = 0;
  const MAX_RECONNECTS = 5;

  console.log(`📋 Existing messages: ${existing.size.toLocaleString()}`);
  console.log(`🎯 Target group: ${TARGET_GROUP_JID}\n`);

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  console.log(`Baileys WA version: ${version.join(".")}\n`);

  let sock;

  function scheduleExit() {
    if (exitTimer) return;
    if (!exitLogShown) {
      console.log(`\n⏳ History sync complete. Waiting ${POST_SYNC_WAIT_MS / 1000}s for stragglers…`);
      exitLogShown = true;
    }
    exitTimer = setTimeout(() => {
      const total = saveMessages(existing);
      console.log(`\n✅ Done.`);
      console.log(`   Total messages: ${total.toLocaleString()}`);
      console.log(`   New this run:   ${newCount.toLocaleString()}`);
      console.log(`   Images saved:   ${imageCount.toLocaleString()}`);
      console.log(`   Output: ${MESSAGES_PATH}`);
      process.exit(0);
    }, POST_SYNC_WAIT_MS);
  }

  async function processMessages(messages, source) {
    for (const msg of messages) {
      // Filter: only target group
      const jid = msg.key?.remoteJid;
      if (jid !== TARGET_GROUP_JID) continue;

      const stanzaId = msg.key?.id;
      if (!stanzaId) continue;

      // Skip if already have this message (idempotent)
      if (existing.has(stanzaId)) continue;

      const mapped = mapMessage(msg, existing.size + 1);

      // Download image media
      if (msg.message?.imageMessage) {
        const filename = await downloadImage(msg, stanzaId);
        if (filename) {
          mapped.media_local_path = `media/${filename}`;
          imageCount++;
        }
      }

      existing.set(stanzaId, mapped);
      newCount++;

      // Periodic checkpoint
      if (newCount % CHECKPOINT_INTERVAL === 0) {
        saveMessages(existing);
        saveCheckpoint({ lastRun: new Date().toISOString(), count: existing.size });
        process.stdout.write(`\r  📥 ${existing.size.toLocaleString()} messages (${newCount} new, ${imageCount} images)`);
      }
    }
  }

  function connect() {
    sock = makeWASocket({
      version,
      auth: state,
      logger: pino({ level: "silent" }),
      printQRInTerminal: false,
      browser: Browsers.macOS("Desktop"),
      syncFullHistory: true,
      getMessage: async () => undefined,
      // Don't mark as online (reduces phone battery drain)
      markOnlineOnConnect: false,
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
      if (qr) {
        console.log("📱 Scan with WhatsApp → Settings → Linked Devices → Link a Device:\n");
        qrcode.generate(qr, { small: true });
      }
      if (connection === "open") {
        console.log("✅ Connected! Waiting for history sync…");
        console.log("   (Large groups can take 10–30 minutes)\n");
        lastOpenTime = Date.now();
      }
      if (connection === "close") {
        const code = lastDisconnect?.error?.output?.statusCode;
        if (code !== DisconnectReason.loggedOut) {
          // Only reset counter if last connection lasted > 30s (real session, not throttle bounce)
          const uptime = lastOpenTime ? Date.now() - lastOpenTime : 0;
          if (uptime > 30_000) {
            reconnectCount = 0;
          }
          reconnectCount++;
          if (reconnectCount > MAX_RECONNECTS) {
            console.log(`❌ Too many rapid reconnects (${MAX_RECONNECTS}). WhatsApp may be throttling.`);
            console.log(`   Wait 10-15 minutes and try again, or the 3am cron will retry.`);
            const total = saveMessages(existing);
            console.log(`   Saved ${total.toLocaleString()} messages (${newCount} new).`);
            process.exit(1);
          }
          const delay = Math.min(2000 * Math.pow(2, reconnectCount - 1), 30000);
          console.log(`Reconnecting in ${delay / 1000}s… (attempt ${reconnectCount}/${MAX_RECONNECTS})`);
          setTimeout(() => connect(), delay);
        } else {
          console.log("❌ Logged out. Delete .baileys_auth/ and re-run to re-link.");
          process.exit(1);
        }
      }
    });

    // History sync batches (bulk, on first link)
    sock.ev.on("messaging-history.set", async ({ messages, isLatest }) => {
      batchCount++;
      const groupMsgs = messages.filter(m => m.key?.remoteJid === TARGET_GROUP_JID);
      console.log(`  📦 Batch #${batchCount}: ${messages.length} messages (${groupMsgs.length} in target group)`);

      await processMessages(groupMsgs, "history");

      if (isLatest) {
        historySyncDone = true;
        saveMessages(existing);
        saveCheckpoint({ lastRun: new Date().toISOString(), count: existing.size, syncComplete: true });
      }

      // Reset exit timer after every batch (not just isLatest) so we
      // wait for more batches rather than exiting mid-stream.
      if (historySyncDone) {
        if (exitTimer) clearTimeout(exitTimer);
        exitTimer = null;
        scheduleExit();
      }
    });

    // Live messages (arrive while connected)
    sock.ev.on("messages.upsert", async ({ messages }) => {
      await processMessages(messages, "live");

      // If history sync already done, reset exit timer on new messages
      if (historySyncDone && exitTimer) {
        clearTimeout(exitTimer);
        scheduleExit();
      }
    });
  }

  connect();

  // Safety timeout: exit after 45 minutes regardless
  setTimeout(() => {
    console.log("\n⏰ Safety timeout (45 min). Saving and exiting…");
    const total = saveMessages(existing);
    console.log(`   Saved ${total.toLocaleString()} messages (${newCount} new).`);
    process.exit(0);
  }, 45 * 60 * 1000);
}

main().catch(err => {
  console.error("Fatal:", err);
  process.exit(1);
});
