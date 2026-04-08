/**
 * Smoke test for Baileys media download — exits after first 3 download attempts.
 * Run BEFORE committing to a full re-link + hour-long sync.
 *
 * What it does:
 *  1. Connects with EXISTING auth (no QR needed if already linked)
 *  2. Waits for any incoming message with media from the target group
 *  3. Attempts downloadMediaMessage on first 3 such messages
 *  4. Prints PASS/FAIL and exits
 *
 * Usage: node 3_smoke_test.mjs
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

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const AUTH_DIR = path.join(__dirname, ".baileys_auth");
const OUTPUT_DIR = path.join(__dirname, "output", "media");
const GROUP_JID = "17069686133-1605817204@g.us";
const MAX_TRIES = 3;
const TIMEOUT_MS = 90_000;   // give up after 90s if no media messages arrive

fs.mkdirSync(OUTPUT_DIR, { recursive: true });
fs.mkdirSync(AUTH_DIR, { recursive: true });

let tries = 0;
let passed = 0;

async function main() {
  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version } = await fetchLatestBaileysVersion();

  console.log(`\n🧪 Baileys media smoke test`);
  console.log(`   Will attempt ${MAX_TRIES} downloads then exit.\n`);

  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
    browser: Browsers.macOS('Desktop'),
    getMessage: async () => undefined,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", ({ connection, qr }) => {
    if (qr) {
      console.log("📱 Scan QR (or delete .baileys_auth first):\n");
      qrcode.generate(qr, { small: true });
    }
    if (connection === "open") {
      console.log("✅ Connected. Waiting for media messages from the group…");
      console.log(`   (Timeout in ${TIMEOUT_MS / 1000}s)\n`);
    }
  });

  async function tryDownload(msg, source) {
    if (tries >= MAX_TRIES) return;
    if (!msg.message) return;

    // Accept media from any chat (during history sync it arrives from all chats)
    const hasMedia = msg.message.imageMessage || msg.message.videoMessage ||
      msg.message.audioMessage || msg.message.documentMessage ||
      msg.message.stickerMessage;
    if (!hasMedia) return;

    tries++;
    const stanzaId = msg.key.id;
    console.log(`\n[${tries}/${MAX_TRIES}] Trying download — stanzaId=${stanzaId} source=${source}`);
    const type = Object.keys(msg.message).find(k => k.endsWith("Message"));
    console.log(`  Message type: ${type}`);

    const t0 = Date.now();
    try {
      const buffer = await downloadMediaMessage(msg, "buffer", {});
      const ms = Date.now() - t0;
      const outPath = path.join(OUTPUT_DIR, `smoke_test_${tries}.bin`);
      fs.writeFileSync(outPath, buffer);
      console.log(`  ✅ PASS — ${buffer.length.toLocaleString()} bytes in ${ms}ms → ${outPath}`);
      passed++;
    } catch (err) {
      const ms = Date.now() - t0;
      console.log(`  ❌ FAIL — ${err.message} (${ms}ms)`);
    }

    if (tries >= MAX_TRIES) finish();
  }

  sock.ev.on("messages.upsert", async ({ messages }) => {
    for (const msg of messages) await tryDownload(msg, "upsert");
  });

  sock.ev.on("messaging-history.set", async ({ messages }) => {
    console.log(`  📦 History batch: ${messages.length} messages received`);
    for (const msg of messages) await tryDownload(msg, "history");
  });

  // Timeout fallback
  setTimeout(() => {
    if (tries === 0) {
      console.log(`\n⏰ Timeout — no media messages received in ${TIMEOUT_MS / 1000}s.`);
      console.log("   Possible reasons:");
      console.log("   • Auth is stale → run: rm -rf .baileys_auth  then re-link");
      console.log("   • Group has no recent activity (no live messages arriving)");
      console.log("   • History sync hasn't reached this group yet (wait longer)");
    }
    finish();
  }, TIMEOUT_MS);

  function finish() {
    console.log(`\n── Smoke test result ─────────────────────────`);
    console.log(`   Attempts: ${tries}`);
    console.log(`   Passed:   ${passed}`);
    console.log(`   Failed:   ${tries - passed}`);
    if (passed > 0) {
      console.log(`\n   ✅ Download works — safe to run 3_fetch_expired.mjs`);
    } else if (tries > 0) {
      console.log(`\n   ❌ All downloads failed — check errors above before full run`);
    }
    process.exit(0);
  }
}

main().catch(err => { console.error("Fatal:", err); process.exit(1); });
