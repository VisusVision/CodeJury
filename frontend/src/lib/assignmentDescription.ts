export interface SplitAssignmentDescription {
  body: string;
  expectedOutput: string | null;
}

const OUTPUT_WORD = "(?:cikti|ciktisi|çıktı|çıktısı|ÇIKTI|ÇIKTISI|Ã§Ä±ktÄ±|Ã§Ä±ktÄ±sÄ±)";
const OUTPUT_HEADING_PREFIX = "(?:(?:beklenen|ornek|örnek|Ã¶rnek)\\s+)?(?:konsol\\s+)?";
const EXPECTED_OUTPUT_HEADING = new RegExp(
  `^\\s*(?:${OUTPUT_HEADING_PREFIX}${OUTPUT_WORD}|expected\\s+output|console\\s+output|example\\s+output)\\s*:\\s*`,
  "im",
);

export function splitAssignmentDescription(description?: string | null): SplitAssignmentDescription {
  const raw = (description || "").trim();
  if (!raw) {
    return { body: "", expectedOutput: null };
  }

  const match = raw.match(EXPECTED_OUTPUT_HEADING);
  if (!match || typeof match.index !== "number") {
    return { body: raw, expectedOutput: null };
  }

  const body = raw.slice(0, match.index).trim();
  const expectedOutput = raw.slice(match.index + match[0].length).trim();

  return {
    body,
    expectedOutput: expectedOutput || null,
  };
}
