#!/usr/bin/env node
/**
 * AgentGrade - Platforma gore install scriptini secen wrapper.
 * Windows -> powershell scripts/install.ps1
 * Linux/macOS -> bash scripts/install.sh
 *
 * Kullanim:
 *   node scripts/run-installer.mjs [--demo] [--no-sandbox] [--no-postgres] [--no-ollama] [--skip-checks]
 */

import { spawn } from "node:child_process";
import { platform } from "node:os";

const args = process.argv.slice(2);

function toPosixArgs(args) {
  return args; // bash bekliyor
}

function toPwshArgs(args) {
  // --demo  -> -DemoMode
  // --no-sandbox -> -NoSandbox vb.
  return args.map((a) => {
    switch (a) {
      case "--demo":         return "-DemoMode";
      case "--no-sandbox":   return "-NoSandbox";
      case "--no-postgres":  return "-NoPostgres";
      case "--no-ollama":    return "-NoOllamaPull";
      case "--skip-checks":  return "-SkipPrereqCheck";
      default:               return a;
    }
  });
}

const isWin = platform() === "win32";

let cmd, cmdArgs;
if (isWin) {
  cmd = "powershell";
  cmdArgs = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/install.ps1", ...toPwshArgs(args)];
} else {
  cmd = "bash";
  cmdArgs = ["scripts/install.sh", ...toPosixArgs(args)];
}

console.log(`> ${cmd} ${cmdArgs.join(" ")}\n`);

const child = spawn(cmd, cmdArgs, { stdio: "inherit" });
child.on("exit", (code) => process.exit(code ?? 1));
child.on("error", (err) => {
  console.error(`Installer baslatilamadi: ${err.message}`);
  process.exit(1);
});
