export interface EvidenceItem {
  line: number;
  agent: string;
  message: string;
  severity: "error" | "warning" | "info" | "success";
  scope?: "file";
}

export interface RejectedClaimItem {
  agent: string;
  agentSource: string;
  claim: string;
  reason: string;
}

export function partitionEvidence(evidence: EvidenceItem[]) {
  const fileEvidence = evidence.filter((item) => item.scope === "file" || item.line === 0);
  const lineEvidence = evidence.filter((item) => item.line > 0);
  return { lineEvidence, fileEvidence };
}
