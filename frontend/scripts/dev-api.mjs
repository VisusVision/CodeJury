/**
 * FastAPI'yi backend/ dizininden baslatir.
 * Python: VITE_PYTHON > (calisan) py/python > son care backend/venv
 */
import { execFileSync, spawn } from "node:child_process";
import { existsSync, readFileSync, watch } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { freePort8000 } from "./free-port-8000.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/** Kok .env ve frontend .env dosyalarindan ortam degiskenlerini yukler */
function loadEnvFiles() {
  const envPaths = [
    path.join(__dirname, "..", "..", ".env"),
    path.join(__dirname, "..", ".env"),
  ];
  for (const envPath of envPaths) {
    if (!existsSync(envPath)) continue;
    try {
      const text = readFileSync(envPath, "utf8");
      for (const line of text.split(/\r?\n/)) {
        const m = /^\s*([A-Za-z_]\w*)\s*=\s*(.*)$/.exec(line);
        if (!m || line.trimStart().startsWith("#")) continue;
        const key = m[1];
        const val = m[2].trim().replace(/^["']|["']$/g, "");
        if (!process.env[key]) {
          process.env[key] = val;
        }
      }
    } catch {
      /* ignore */
    }
  }
}
loadEnvFiles();
const backendDir = path.join(__dirname, "..", "backend");
const backendDirAbs = path.resolve(backendDir);
/** CodeJury kok (frontend'in ust dizini) — backend.agents her zaman buradan yuklensin */
const repoRoot = path.join(__dirname, "..", "..");
const repoRootAbs = path.resolve(repoRoot);
/** PYTHONPATH'teki gercek backend (ajanlar burada); uvicorn --reload bunu izlemezse security.py vb. hep ESKI kalir */
const sharedBackendAbs = path.join(repoRootAbs, "backend");

const repoVenvWin = path.join(repoRootAbs, ".venv", "Scripts", "python.exe");
const repoVenvUnix = path.join(repoRootAbs, ".venv", "bin", "python");
const winVenv = path.join(backendDir, "venv", "Scripts", "python.exe");
const unixVenv = path.join(backendDir, "venv", "bin", "python");

/** 8000'de eski API takili kaldiysa 2.0.0 gorursun; varsayilan 8001. Istersen: DEV_API_PORT=8000 */
const apiPort = process.env.DEV_API_PORT || "8001";

/** --app-dir: baska klasordeki main.py yuklenmesini engeller (Windows'ta kritik) */
const uvicornArgs = [
  "-m",
  "uvicorn",
  "main:app",
  "--app-dir",
  backendDirAbs,
  "--host",
  "127.0.0.1",
  "--port",
  apiPort,
];

function tryRun(exe, extraArgs = []) {
  try {
    return execFileSync(exe, ["-c", "import sys; print(sys.executable)", ...extraArgs], {
      encoding: "utf-8",
      windowsHide: true,
    }).trim();
  } catch {
    return "";
  }
}

function resolvePythonExe() {
  const custom = process.env.VITE_PYTHON?.trim();
  if (custom && existsSync(custom) && tryRun(custom)) return custom;

  for (const v of [repoVenvWin, repoVenvUnix]) {
    if (existsSync(v) && tryRun(v)) return v;
  }

  const candidates = [];
  if (process.platform === "win32") {
    candidates.push({ exe: "py", args: ["-3.14"] });
    candidates.push({ exe: "py", args: ["-3"] });
  }
  candidates.push({ exe: "python3", args: [] });
  candidates.push({ exe: "python", args: [] });

  for (const { exe, args: pyPre } of candidates) {
    try {
      const out = execFileSync(
        exe,
        [...pyPre, "-c", "import sys; print(sys.executable)"],
        { encoding: "utf-8", windowsHide: true },
      ).trim();
      if (out && existsSync(out)) return out;
    } catch {
      /* next */
    }
  }

  for (const v of [winVenv, unixVenv]) {
    if (existsSync(v) && tryRun(v)) return v;
  }

  return "";
}

const pythonExe = resolvePythonExe();
const mainPy = path.join(backendDirAbs, "main.py");
let healthVersionHint = "?";
try {
  const src = readFileSync(mainPy, "utf8");
  if (src.includes('"analysis_engine"') && src.includes('"version": "2.1.0"')) {
    healthVersionHint = "disk: health 2.1.0 + analysis_engine (beklenen)";
  } else if (src.includes('"version": "2.0.0"')) {
    healthVersionHint = "UYARI: diskteki main.py hala 2.0.0 — bu klasoru guncelle";
  } else {
    healthVersionHint = "main.py health alani taninamadi";
  }
} catch {
  healthVersionHint = "main.py okunamadi";
}

if (!pythonExe) {
  console.error(
    "[dev-api] Calisan Python bulunamadi. Cozum: `py -3.14 -m pip install -r backend/requirements.txt` " +
    "veya bozuk backend/venv klasorunu silip yeniden olusturun. Isterseniz VITE_PYTHON ile exe yolu verin.",
  );
  process.exit(1);
}

console.error("[dev-api] PYTHONPATH =", repoRootAbs);
console.error("[dev-api] watcher = Node fs.watch (ignores venv/.venv/__pycache__/node_modules)");
console.error("[dev-api] --app-dir   =", backendDirAbs);
console.error("[dev-api] main.py     =", mainPy);
console.error("[dev-api] port        =", apiPort, "(DEV_API_PORT ile degistir; varsayilan 8001)");
console.error("[dev-api]", healthVersionHint);
console.error(
  "[dev-api] Health kontrol: http://127.0.0.1:" + apiPort + "/api/health — SKIP_FREE_PORT=1 otomatik port temizligini kapatir.",
);

async function start() {
  if (process.env.SKIP_FREE_PORT !== "1") {
    const killed = freePort8000(apiPort);
    if (killed.length) {
      console.error(`[dev-api] Eski API surecleri kapatildi (${killed.join(", ")}), socket bosalmasi bekleniyor...`);
      await new Promise((r) => setTimeout(r, 800));
    }
  }

  const sourceDirs = [backendDirAbs];
  if (existsSync(sharedBackendAbs) && sharedBackendAbs !== backendDirAbs) {
    sourceDirs.push(sharedBackendAbs);
  }

  let child = null;
  let restartTimer = null;
  let isRestarting = false;

  const shouldIgnorePath = (changedPath) => {
    if (!changedPath) return true;
    const normalized = changedPath.replace(/\\/g, "/").toLowerCase();
    return (
      normalized.includes("/venv/") ||
      normalized.includes("/.venv/") ||
      normalized.includes("__pycache__") ||
      normalized.includes("/node_modules/")
    );
  };

  const startChild = () => {
    isRestarting = false;
    child = spawn(pythonExe, uvicornArgs, {
      cwd: backendDirAbs,
      stdio: "inherit",
      env: {
        ...process.env,
        PYTHONPATH: [repoRootAbs, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
      },
    });

    child.on("exit", (code, signal) => {
      if (isRestarting) return;  // intentional restart — don't exit
      if (restartTimer) {
        clearTimeout(restartTimer);
        restartTimer = null;
      }
      if (signal) process.kill(process.pid, signal);
      process.exit(code ?? 1);
    });
  };

  const scheduleRestart = (changedPath) => {
    if (shouldIgnorePath(changedPath)) return;
    if (restartTimer) clearTimeout(restartTimer);
    restartTimer = setTimeout(() => {
      restartTimer = null;
      if (!child || child.killed) {
        startChild();
        return;
      }
      console.error(`[dev-api] Degisim algilandi, yeniden baslatiliyor: ${changedPath}`);
      isRestarting = true;
      child.once("exit", () => startChild());
      child.kill();
    }, 250);
  };

  for (const dir of sourceDirs) {
    watch(
      dir,
      { recursive: true },
      (_eventType, filename) => {
        if (!filename) return;
        scheduleRestart(path.join(dir, filename.toString()));
      },
    );
  }

  startChild();
}

start().catch((e) => {
  console.error("[dev-api]", e);
  process.exit(1);
});
