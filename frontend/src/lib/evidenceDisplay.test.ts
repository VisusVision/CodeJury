import { describe, expect, test } from "vitest";
import { partitionEvidence, type EvidenceItem } from "./evidenceDisplay";

describe("partitionEvidence", () => {
  test("separates file-level claims from line-level claims", () => {
    const items: EvidenceItem[] = [
      { line: 2, agent: "Kod Kalitesi", message: "Satir 2 sorunu", severity: "warning" },
      { line: 0, agent: "Güvenlik", message: "Dosya seviyesi risk", severity: "error", scope: "file" },
    ];

    const { lineEvidence, fileEvidence } = partitionEvidence(items);

    expect(lineEvidence).toHaveLength(1);
    expect(lineEvidence[0].line).toBe(2);
    expect(fileEvidence).toHaveLength(1);
    expect(fileEvidence[0].scope).toBe("file");
  });

  test("treats line zero without scope as file-level", () => {
    const items: EvidenceItem[] = [
      { line: 0, agent: "Test", message: "Runtime log", severity: "info" },
    ];

    const { lineEvidence, fileEvidence } = partitionEvidence(items);

    expect(lineEvidence).toHaveLength(0);
    expect(fileEvidence).toHaveLength(1);
  });
});
