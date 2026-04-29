/**
 * Belirtilen portta LISTENEN tum PID'leri kapatir (Windows: taskkill).
 * Panel API varsayilan 8001; 8000'de takili eski uvicorn icin: node scripts/free-port-8000.mjs 8000
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

/** npm run dev ile uyumlu: DEV_API_PORT yoksa 8001 */
const DEFAULT_PORT = "8001";

/**
 * @param {string} [portStr]
 * @returns {string[]} Sonlandirilan PID'ler
 */
export function freePort8000(portStr = process.env.DEV_API_PORT || DEFAULT_PORT) {
  const port = String(portStr);
  const killed = [];
  if (process.platform !== "win32") {
    try {
      execFileSync("sh", ["-c", `lsof -ti:${port} 2>/dev/null | xargs -r kill -9 2>/dev/null`], {
        stdio: "pipe",
      });
    } catch {
      /* yoksa sorun degil */
    }
    return killed;
  }

  let out = "";
  try {
    out = execFileSync("netstat", ["-ano"], { encoding: "utf-8", windowsHide: true });
  } catch {
    return killed;
  }

  const pids = new Set();
  for (const line of out.split(/\r?\n/)) {
    const u = line.toUpperCase();
    // TR Windows netstat bazen LISTENING yerine DINLEME yazar
    if (!u.includes("LISTENING") && !u.includes("DINLEME")) continue;
    const parts = line.trim().split(/\s+/);
    if (parts.length < 5) continue;
    const local = parts[1];
    if (!local) continue;
    const colon = local.lastIndexOf(":");
    if (colon < 0) continue;
    const localPort = local.slice(colon + 1);
    if (localPort !== port) continue;

    const pid = parts[parts.length - 1];
    if (!/^\d+$/.test(pid)) continue;
    pids.add(pid);
  }

  for (const pid of pids) {
    try {
      console.error(`[free-port-8000] Port ${port} LISTENING PID ${pid} -> taskkill /F`);
      execFileSync("taskkill", ["/PID", pid, "/F"], { stdio: "pipe", windowsHide: true });
      killed.push(pid);
    } catch {
      /* yetki veya zaten kapali */
    }
  }
  return killed;
}

const self = path.normalize(fileURLToPath(import.meta.url));
const invoked = path.normalize(path.resolve(process.argv[1] ?? ""));
const isCli =
  process.platform === "win32"
    ? invoked.toLowerCase() === self.toLowerCase()
    : invoked === self;

if (isCli) {
  const port = process.argv[2] || process.env.DEV_API_PORT || DEFAULT_PORT;
  const k = freePort8000(port);
  console.error(
    k.length
      ? `[free-port-8000] Port ${port} kapatilan PID: ${k.join(", ")}`
      : `[free-port-8000] Port ${port}'de LISTENING yoktu.`,
  );
  process.exit(0);
}
