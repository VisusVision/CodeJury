/**
 * Calisan API'nin /api/health cevabini yazdirir.
 * Kullanim: `npm run dev` sonrasi `npm run verify:health`
 * Varsayilan port 8001 (dev-api ile ayni). Eski 8000: HEALTH_URL=http://127.0.0.1:8000/api/health
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
if (!process.env.DEV_API_PORT) {
  const envPath = path.join(__dirname, "..", ".env");
  if (existsSync(envPath)) {
    try {
      for (const line of readFileSync(envPath, "utf8").split(/\r?\n/)) {
        const m = /^\s*DEV_API_PORT\s*=\s*(\S+)/.exec(line);
        if (m) {
          process.env.DEV_API_PORT = m[1].trim().replace(/^["']|["']$/g, "");
          break;
        }
      }
    } catch {
      /* ignore */
    }
  }
}

const port = process.env.DEV_API_PORT || "8001";
const url = process.env.HEALTH_URL || `http://127.0.0.1:${port}/api/health`;
try {
  console.error("[verify-health] URL:", url);
  const r = await fetch(url, { cache: "no-store" });
  const j = await r.json();
  console.log(JSON.stringify(j, null, 2));
  if (j.version === "2.1.0" && j.analysis_engine != null) {
    console.error("\n[OK] Guncel panel API (2.1.0 + analysis_engine).");
    process.exit(0);
  }
  if (j.version === "2.0.0" && j.agents === 8 && j.analysis_engine == null) {
    console.error(
      "\n[HATA] Eski API yaniti (2.0.0). Yanlis porta bakiyor olabilirsin: `npm run verify:health` artik " +
        port +
        " kullanir. Eski 8000'i deniyorsan HEALTH_URL=http://127.0.0.1:8001/api/health dene veya `npm run dev` ile panel API'yi 8001'de baslat.",
    );
    process.exit(1);
  }
  console.error("\n[BILINMIYOR] Beklenmeyen health govdesi.");
  process.exit(2);
} catch (e) {
  console.error("[HATA] Istek basarisiz:", e.message);
  process.exit(3);
}
