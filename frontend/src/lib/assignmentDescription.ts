export interface SplitAssignmentDescription {
  body: string;
  expectedOutput: string | null;
}

const EXPECTED_OUTPUT_HEADING =
  /^\s*(?:(?:beklenen\s+)?(?:konsol\s+)?(?:[cç][iıİI]kt[iıİI]|[cç][iıİI]kt[iıİI]s[iıİI])|expected\s+output|console\s+output)\s*:\s*/im;

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
