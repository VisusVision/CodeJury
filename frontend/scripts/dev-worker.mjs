/**
 * Analysis worker'i dev modda baslatir.
 * `npm run dev:full` icinde Vite ve FastAPI ile birlikte calisir.
 */
import { execFileSync, spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import net from "node:net";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRootAbs = path.resolve(path.join(__dirname, "..", ".."));
const workerPath = path.join(repoRootAbs, "backend", "workers", "analysis_worker.py");

function loadEnvFiles() {
  const envPaths = [
    path.join(repoRootAbs, ".env"),
    path.join(repoRootAbs, "frontend", ".env"),
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
        if (!process.env[key]) process.env[key] = val;
      }
    } catch {
      /* ignore */
    }
  }
}

function tryPython(exe, args = []) {
  try {
    const out = execFileSync(exe, [...args, "-c", "import sys; print(sys.executable)"], {
      encoding: "utf-8",
      windowsHide: true,
    }).trim();
    return out && existsSync(out) ? out : "";
  } catch {
    return "";
  }
}

function resolvePythonExe() {
  const custom = process.env.VITE_PYTHON?.trim();
  if (custom && existsSync(custom) && tryPython(custom)) return custom;

  const repoVenvWin = path.join(repoRootAbs, ".venv", "Scripts", "python.exe");
  const repoVenvUnix = path.join(repoRootAbs, ".venv", "bin", "python");
  for (const exe of [repoVenvWin, repoVenvUnix]) {
    if (existsSync(exe) && tryPython(exe)) return exe;
  }

  if (process.platform === "win32") {
    const py314 = tryPython("py", ["-3.14"]);
    if (py314) return py314;
    const py3 = tryPython("py", ["-3"]);
    if (py3) return py3;
  }

  return tryPython("python3") || tryPython("python");
}

function canConnect(host, port, timeoutMs = 700) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    const done = (ok) => {
      socket.removeAllListeners();
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
  });
}

function getRedisTarget(redisUrl = process.env.REDIS_URL || "redis://localhost:6379/0") {
  try {
    const parsed = new URL(redisUrl);
    if (!["redis:", "rediss:"].includes(parsed.protocol)) return null;
    return {
      host: parsed.hostname || "localhost",
      port: Number(parsed.port || 6379),
    };
  } catch {
    return null;
  }
}

async function waitForConnection(host, port) {
  for (let attempt = 0; attempt < 20; attempt++) {
    if (await canConnect(host, port, 700)) return true;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

async function ensureRedis() {
  const target = getRedisTarget();
  if (!target || (await canConnect(target.host, target.port))) return;
  if (!existsSync(path.join(repoRootAbs, "docker-compose.yml"))) return;

  console.error("[dev-worker] Redis kapali gorunuyor; docker compose ile baslatiliyor...");
  try {
    execFileSync("docker", ["compose", "up", "-d", "redis"], {
      cwd: repoRootAbs,
      encoding: "utf-8",
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
  } catch {
    console.error("[dev-worker] Redis otomatik baslatilamadi. Docker Desktop acik mi?");
    return;
  }

  if (await waitForConnection(target.host, target.port)) {
    console.error("[dev-worker] Redis hazir.");
  } else {
    console.error("[dev-worker] Redis baslatildi ama port henuz cevap vermiyor.");
  }
}

async function start() {
  loadEnvFiles();
  const pythonExe = resolvePythonExe();
  if (!pythonExe) {
    console.error("[dev-worker] Calisan Python bulunamadi. VITE_PYTHON ile exe yolu verebilirsiniz.");
    process.exit(1);
  }

  await ensureRedis();
  console.error("[dev-worker] analysis worker baslatiliyor:", workerPath);

  const child = spawn(pythonExe, [workerPath], {
    cwd: repoRootAbs,
    stdio: "inherit",
    env: {
      ...process.env,
      PYTHONPATH: [repoRootAbs, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter),
    },
  });

  child.on("exit", (code, signal) => {
    if (signal) process.kill(process.pid, signal);
    process.exit(code ?? 1);
  });
}

start().catch((error) => {
  console.error("[dev-worker]", error);
  process.exit(1);
});
