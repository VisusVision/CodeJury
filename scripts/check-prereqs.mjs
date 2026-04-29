#!/usr/bin/env node
/**
 * AgentGrade - Onkosul dogrulama scripti (cross-platform).
 *
 * Hicbir sey kurmaz, sadece sistemde gerekli araclarin var olup
 * olmadigini ve versiyonlarini kontrol eder.
 *
 * Kullanim:
 *   node scripts/check-prereqs.mjs
 *   npm run check:prereqs
 *
 * Cikis kodu:
 *   0 = tum zorunlu onkosullar tamam (uyarilar olabilir)
 *   1 = en az bir zorunlu onkosul eksik
 */

import { execSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { request } from "node:http";

const C = {
  cyan:    (s) => `\x1b[36m${s}\x1b[0m`,
  green:   (s) => `\x1b[32m${s}\x1b[0m`,
  yellow:  (s) => `\x1b[33m${s}\x1b[0m`,
  red:     (s) => `\x1b[31m${s}\x1b[0m`,
  gray:    (s) => `\x1b[90m${s}\x1b[0m`,
  magenta: (s) => `\x1b[35m${s}\x1b[0m`,
};

const results = []; // { name, status: 'ok'|'warn'|'err', detail, required }

function record(name, status, detail, required = false) {
  results.push({ name, status, detail, required });
  const tag = {
    ok:   C.green("[OK]   "),
    warn: C.yellow("[WARN] "),
    err:  C.red("[ERROR]"),
  }[status];
  console.log(`${tag} ${name.padEnd(18)} ${detail}`);
}

function tryExec(cmd) {
  try {
    return execSync(cmd, { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return null;
  }
}

function cmpVersion(a, b) {
  const pa = a.split(".").map((n) => parseInt(n, 10) || 0);
  const pb = b.split(".").map((n) => parseInt(n, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0;
    const y = pb[i] || 0;
    if (x !== y) return x - y;
  }
  return 0;
}

function checkPython() {
  for (const cmd of ["python", "python3", "py"]) {
    const out = tryExec(`${cmd} --version`);
    if (!out) continue;
    const m = out.match(/Python (\d+\.\d+\.\d+)/);
    if (!m) continue;
    const ver = m[1];
    if (cmpVersion(ver, "3.11.0") >= 0) {
      record("Python", "ok", `${cmd} ${ver}`, true);
      return true;
    }
    record("Python", "err", `${cmd} ${ver} bulundu, 3.11+ gerekli.`, true);
    return false;
  }
  record("Python", "err", "Python 3.11+ bulunamadi. https://www.python.org/downloads/", true);
  return false;
}

function checkNode() {
  const ver = process.versions.node;
  if (cmpVersion(ver, "18.0.0") >= 0) {
    record("Node.js", "ok", `v${ver}`, true);
    return true;
  }
  record("Node.js", "err", `v${ver} bulundu, 18+ gerekli.`, true);
  return false;
}

function checkNpm() {
  const ver = tryExec("npm --version");
  if (ver) {
    record("npm", "ok", ver, true);
    return true;
  }
  record("npm", "err", "npm bulunamadi (Node.js ile birlikte kurulmali).", true);
  return false;
}

function checkDocker() {
  const ver = tryExec("docker --version");
  if (!ver) {
    record("Docker", "warn", "Bulunamadi. Sandbox/PostgreSQL icin gerekli. https://www.docker.com/products/docker-desktop/");
    return false;
  }
  const info = tryExec("docker info");
  if (!info) {
    record("Docker", "warn", `${ver} (daemon calismiyor; Docker Desktop'i baslatin)`);
    return false;
  }
  record("Docker", "ok", ver);
  return true;
}

function checkDockerCompose() {
  const ver = tryExec("docker compose version");
  if (ver) {
    record("docker compose", "ok", ver.split("\n")[0]);
    return true;
  }
  record("docker compose", "warn", "docker compose v2 bulunamadi.");
  return false;
}

function checkOllamaCmd() {
  const ver = tryExec("ollama --version");
  if (!ver) {
    record("Ollama", "warn", "Bulunamadi. LLM destegi icin: https://ollama.com/download");
    return false;
  }
  return ver;
}

async function pingOllama() {
  return new Promise((res) => {
    const req = request(
      { host: "localhost", port: 11434, path: "/api/tags", method: "GET", timeout: 2000 },
      (r) => { r.resume(); res(r.statusCode === 200); }
    );
    req.on("timeout", () => { req.destroy(); res(false); });
    req.on("error", () => res(false));
    req.end();
  });
}

async function checkOllama() {
  const cliVer = checkOllamaCmd();
  if (!cliVer) return;
  const up = await pingOllama();
  if (up) record("Ollama servis", "ok", `${cliVer} - http://localhost:11434 calisiyor`);
  else    record("Ollama servis", "warn", `${cliVer} - servis cevap vermiyor. 'ollama serve' calistirin.`);
}

function checkRepoFiles() {
  const root = resolve(process.cwd());
  const files = ["requirements.txt", "package.json", "frontend/package.json", "docker-compose.yml", "sandbox-images/agentgrade/Dockerfile"];
  let allOk = true;
  for (const f of files) {
    if (!existsSync(resolve(root, f))) {
      record("Repo", "err", `Beklenen dosya yok: ${f} (yanlis dizinde misiniz?)`, true);
      allOk = false;
    }
  }
  if (allOk) record("Repo", "ok", "Beklenen tum dosyalar mevcut.");
  return allOk;
}

function checkEnvFile() {
  if (existsSync(".env")) record("Env", "ok", ".env mevcut.");
  else if (existsSync(".env.example")) record("Env", "warn", ".env yok, ancak .env.example var. install.ps1/install.sh otomatik kopyalar.");
  else record("Env", "warn", ".env ve .env.example bulunamadi.");
}

// ----------------------------------------------------------------------------

async function main() {
  console.log(C.magenta("============================================"));
  console.log(C.magenta(" AgentGrade - Onkosul Dogrulama"));
  console.log(C.magenta("============================================\n"));

  checkRepoFiles();
  checkEnvFile();
  checkPython();
  checkNode();
  checkNpm();
  checkDocker();
  checkDockerCompose();
  await checkOllama();

  console.log("\n" + C.magenta("--------------------------------------------"));
  const errs  = results.filter((r) => r.status === "err");
  const warns = results.filter((r) => r.status === "warn");
  const reqErrs = errs.filter((r) => r.required);

  if (reqErrs.length === 0 && warns.length === 0) {
    console.log(C.green("Tum onkosullar tamam. Kurulum scriptini calistirabilirsiniz."));
  } else {
    if (reqErrs.length > 0) {
      console.log(C.red(`Zorunlu eksiklikler: ${reqErrs.length}`));
      reqErrs.forEach((r) => console.log(C.red(`  - ${r.name}: ${r.detail}`)));
    }
    if (warns.length > 0) {
      console.log(C.yellow(`Uyarilar: ${warns.length}`));
      warns.forEach((r) => console.log(C.yellow(`  - ${r.name}: ${r.detail}`)));
    }
  }

  console.log("");
  console.log(C.gray("Kurulumu baslatmak icin:"));
  console.log(C.gray("  Windows: powershell -ExecutionPolicy Bypass -File scripts/install.ps1"));
  console.log(C.gray("  Linux/macOS: bash scripts/install.sh"));
  console.log(C.gray("  Demo mode: ... -DemoMode  /  ... --demo"));

  process.exit(reqErrs.length > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error(C.red("Beklenmedik hata: " + e.message));
  process.exit(2);
});
