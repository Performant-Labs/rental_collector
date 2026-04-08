/**
 * Step 3 (revised): Fetch media via WhatsApp Web history sync.
 *
 * HOW IT WORKS:
 *  When a new device links to WA, WhatsApp sends the full message history of
 *  all chats as a "history sync" (messaging-history.set events). Each message
 *  arrives with its complete proto — including the fileEncSha256, directPath,
 *  and mediaKey needed to download media. We listen for those events, match
 *  against our failed list, and download media immediately.
 *
 * NOTES:
 *  - If .baileys_auth already exists (from the broken first run), delete it
 *    first: rm -rf .baileys_auth   — then re-run and scan the QR again.
 *  - WA sends history in batches; large groups can take 10–30 min to fully
 *    sync. Leave the script running until you see "History sync complete".
 *  - A checkpoint is saved every 10 downloads so you can safely Ctrl+C and
 *    resume (without clearing auth again).
 */

import makeWASocket, {
  useMultiFileAuthState,
  downloadMediaMessage,
  DisconnectReason,
  fetchLatestBaileysVersion,
  Browsers,
} from "@whiskeysockets/baileys";
import qrcode from "qrcode-terminal";
import pino from "pino";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import Database from "better-sqlite3";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// ── Config ───────────────────────────────────────────────────────────────────
const DB_PATH = path.join(__dirname, "ChatStorage.sqlite");
const OUTPUT_DIR = path.join(__dirname, "output", "media");
const AUTH_DIR = path.join(__dirname, ".baileys_auth");
const CHECKPOINT = path.join(__dirname, "output", "baileys_checkpoint.json");
const LOG_MAIN = path.join(__dirname, "output", "media_download_log.json");
const LOG_RETRY = path.join(__dirname, "output", "retry_decrypt_log.json");
const BAILEYS_LOG = path.join(__dirname, "output", "baileys_log.json");
const SESSION_ID = 189;

const TYPE_EXT = {
  1: ".jpg", 2: ".mp4", 3: ".ogg", 4: "", 7: ".mp4", 14: ".webp", 15: ".webp",
};

// ── Load the set of media IDs we still need ───────────────────────────────────
function loadNeededIds() {
  const WANT = new Set([
    "expired_url_403", "expired_url_404",
    "decrypt_failed", "skipped_no_key", "skipped_no_appinfo",
  ]);
  const ids = new Set();
  for (const logPath of [LOG_MAIN, LOG_RETRY]) {
    if (!fs.existsSync(logPath)) continue;
    for (const r of JSON.parse(fs.readFileSync(logPath, "utf8"))) {
      if (WANT.has(r.status)) ids.add(r.media_id);
    }
  }
  return ids;
}

// ── Checkpoint ────────────────────────────────────────────────────────────────
function loadCheckpoint() {
  return fs.existsSync(CHECKPOINT)
    ? new Set(JSON.parse(fs.readFileSync(CHECKPOINT, "utf8")).done)
    : new Set();
}
function saveCheckpoint(done) {
  fs.writeFileSync(CHECKPOINT, JSON.stringify({ done: [...done] }, null, 2));
}

// ── Build stanzaId → mediaId index from DB ────────────────────────────────────
function buildIndex(neededIds) {
  const db = new Database(DB_PATH, { readonly: true });
  const rows = db.prepare(`
    SELECT m.ZSTANZAID as stanza_id,
           mi.Z_PK     as media_id,
           m.ZMESSAGETYPE as msg_type,
           mi.ZTITLE   as title
    FROM ZWAMEDIAITEM mi
    JOIN ZWAMESSAGE m ON m.ZMEDIAITEM = mi.Z_PK
    WHERE mi.Z_PK IN (${[...neededIds].map(() => "?").join(",")})
  `).all(...neededIds);
  db.close();

  const map = new Map(); // stanza_id → { media_id, msg_type, title }
  for (const r of rows) {
    if (r.stanza_id) map.set(r.stanza_id, r);
  }
  return map;
}

function safeFilename(mediaId, msgType, title) {
  const ext = TYPE_EXT[msgType] ?? ".bin";
  if (msgType === 4 && title) {
    const safe = title.replace(/[^a-zA-Z0-9._\- ]/g, "").slice(0, 80);
    const name = `${mediaId}_${safe}`;
    return name.includes(".") ? name : name + ".bin";
  }
  return `${mediaId}${ext}`;
}

// ── Process a single incoming WA message ─────────────────────────────────────
async function handleMessage(msg, index, done, bailLog) {
  const stanzaId = msg.key?.id;
  if (!stanzaId || !index.has(stanzaId)) return;

  const item = index.get(stanzaId);
  if (done.has(item.media_id)) return;

  if (!msg.message) {
    bailLog.push({ media_id: item.media_id, status: "no_message_content" });
    done.add(item.media_id);
    return;
  }

  const outFile = path.join(OUTPUT_DIR, safeFilename(item.media_id, item.msg_type, item.title));
  if (fs.existsSync(outFile)) {
    done.add(item.media_id);
    return;
  }

  try {
    const buffer = await downloadMediaMessage(msg, "buffer", {});
    fs.writeFileSync(outFile, buffer);
    bailLog.push({ media_id: item.media_id, status: "downloaded", path: outFile });
    console.log(`  ✅ [${done.size + 1}] media_id=${item.media_id} → ${path.basename(outFile)}`);
  } catch (err) {
    // Silently count errors — most are CDN-purged (permanently gone from WA servers)
    const errType = err.message.includes("fetch stream") ? "cdn_purged"
      : err.message.includes("empty media key") ? "no_key"
        : "error";
    bailLog.push({ media_id: item.media_id, status: errType, error: err.message });
  }

  done.add(item.media_id);
}

// ── Main ──────────────────────────────────────────────────────────────────────
async function main() {
  // Check if old auth exists from the broken first run
  if (fs.existsSync(AUTH_DIR) && fs.readdirSync(AUTH_DIR).length > 0) {
    console.log("\n⚠️  Found existing .baileys_auth from a previous session.");
    console.log("   WA history sync only runs when linking as a FRESH device.");
    console.log("   If you haven't cleared it yet, run:");
    console.log("   rm -rf .baileys_auth   (then re-run this script)\n");
  }

  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  fs.mkdirSync(AUTH_DIR, { recursive: true });

  const neededIds = loadNeededIds();
  const done = loadCheckpoint();
  const remaining = new Set([...neededIds].filter(id => !done.has(id)));

  console.log(`📋 Total media to recover:          ${neededIds.size.toLocaleString()}`);
  console.log(`✅ Already done (checkpoint):       ${done.size.toLocaleString()}`);
  console.log(`⏳ Remaining this run:              ${remaining.size.toLocaleString()}\n`);

  if (remaining.size === 0) {
    console.log("Nothing left — all items recovered!"); return;
  }

  const index = buildIndex(remaining);
  const bailLog = [];
  let saveCounter = 0;

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();
  console.log(`Baileys WA version: ${version.join(".")}\n`);

  let sock;

  function connect() {
    sock = makeWASocket({
      version,
      auth: state,
      logger: pino({ level: "silent" }),
      printQRInTerminal: false,
      browser: Browsers.macOS("Desktop"),
      getMessage: async () => undefined,
    });

    sock.ev.on("creds.update", saveCreds);

    sock.ev.on("connection.update", ({ connection, lastDisconnect, qr }) => {
      if (qr) {
        console.log("📱 Scan with WhatsApp → Settings → Linked Devices → Link a Device:\n");
        qrcode.generate(qr, { small: true });
      }
      if (connection === "open") {
        console.log("✅ Connected! Waiting for WA to send history sync…");
        console.log("   (This can take several minutes for large groups)\n");
      }
      if (connection === "close") {
        const shouldRetry = lastDisconnect?.error?.output?.statusCode !== DisconnectReason.loggedOut;
        if (shouldRetry) { console.log("Reconnecting…"); connect(); }
        else { console.log("Logged out."); process.exit(1); }
      }
    });

    // ── New messages (live + history batches) ─────────────────────────────
    sock.ev.on("messages.upsert", async ({ messages }) => {
      for (const msg of messages) {
        await handleMessage(msg, index, done, bailLog);
        saveCounter++;
        if (saveCounter % 10 === 0) {
          saveCheckpoint(done);
          fs.writeFileSync(BAILEYS_LOG, JSON.stringify(bailLog, null, 2));
          const pct = ((done.size / neededIds.size) * 100).toFixed(1);
          process.stdout.write(`\r  Progress: ${done.size}/${neededIds.size} (${pct}%) recovered`);
        }
      }
    });

    // ── History sync blocks ────────────────────────────────────────────────
    sock.ev.on("messaging-history.set", async ({ messages, isLatest }) => {
      console.log(`\n  📦 History batch received: ${messages.length} messages (isLatest=${isLatest})`);
      for (const msg of messages) {
        await handleMessage(msg, index, done, bailLog);
      }
      saveCheckpoint(done);
      fs.writeFileSync(BAILEYS_LOG, JSON.stringify(bailLog, null, 2));

      if (isLatest) {
        console.log("\n  ✅ History sync complete.");
        printSummary(bailLog, done, neededIds);
      }
    });
  }

  connect();
}

function printSummary(bailLog, done, neededIds) {
  const byStatus = bailLog.reduce((a, r) => {
    a[r.status] = (a[r.status] || 0) + 1; return a;
  }, {});
  console.log("\n── Baileys result summary ───────────────────────────");
  for (const [s, c] of Object.entries(byStatus).sort((a, b) => b[1] - a[1])) {
    console.log(`  ${s.padEnd(30)} ${c.toLocaleString()}`);
  }
  console.log(`\n  Done: ${done.size}/${neededIds.size} recovered`);
  console.log(`  Output: ${path.join(path.dirname(BAILEYS_LOG), "media")}`);
}

main().catch(err => { console.error("Fatal:", err); process.exit(1); });
