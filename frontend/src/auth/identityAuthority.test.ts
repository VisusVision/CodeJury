import { describe, expect, test } from "vitest";
import fs from "node:fs";
import path from "node:path";

const SRC_ROOT = path.resolve(__dirname, "..");

const SESSION_IDENTITY_PATTERN =
  /sessionStorage\.(getItem|setItem|removeItem)\(\s*["'](student|teacher)["']/;

function collectSourceFiles(dir: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  const files: string[] = [];
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectSourceFiles(full));
    } else if (
      /\.(tsx?|jsx?)$/.test(entry.name) &&
      !/\.test\.(tsx?|jsx?)$/.test(entry.name)
    ) {
      files.push(full);
    }
  }
  return files;
}

describe("identity authority regression", () => {
  test("no sessionStorage reads/writes for student/teacher identity in src", () => {
    const files = collectSourceFiles(SRC_ROOT);
    const violations: string[] = [];

    for (const file of files) {
      const content = fs.readFileSync(file, "utf8");
      const lines = content.split("\n");
      lines.forEach((line, index) => {
        if (SESSION_IDENTITY_PATTERN.test(line)) {
          violations.push(`${path.relative(SRC_ROOT, file)}:${index + 1}: ${line.trim()}`);
        }
      });
    }

    expect(violations).toEqual([]);
  });
});
