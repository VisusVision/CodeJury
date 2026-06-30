import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import RightPanel from "./RightPanel";
import type { ReportData } from "./AnalysisReport";
import { Activity } from "lucide-react";

vi.mock("@/i18n/LanguageContext", () => ({
  useTranslation: () => ({
    language: "tr",
    t: (key: string) => key,
  }),
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }: React.ComponentProps<"div">) => <div {...props}>{children}</div>,
    circle: ({ children, ...props }: React.ComponentProps<"circle">) => <circle {...props}>{children}</circle>,
  },
}));

const baseReport: ReportData = {
  totalScore: 80,
  maxScore: 100,
  rubric: [],
  agents: [],
  evidence: [],
  fileName: "main.py",
  fileContent: "print('ok')",
  executionTimeMs: 1200,
  memoryUsageMb: 10,
  peakMemoryMb: 12,
  agentDiagnostics: {
    agents: [{ id: "testing", llm_status: "ok", guardrail_flags: [] }],
    runtime: {
      llm: { general_model: "llama3", coder_model: "qwen2.5-coder" },
      sandbox: {
        mode: "pool",
        execution_backend: "pool",
        pool_ready: true,
        container_count: 3,
        available_count: 2,
      },
      pipeline_ms: 4500,
    },
  },
};

describe("RightPanel runtime diagnostics", () => {
  test("shows runtime block on process tab when agentDiagnostics.runtime is present", () => {
    render(
      <RightPanel
        agents={[{ id: "testing", name: "Testing", description: "", icon: Activity }]}
        agentStatuses={{ testing: "done" }}
        agentActions={{ testing: "done" }}
        findings={[]}
        report={baseReport}
        isRunning={false}
        exporting={false}
        onExportPdf={() => undefined}
        onFindingClick={() => undefined}
      />
    );

    expect(screen.getByText("rightPanel.runtimeTitle")).toBeInTheDocument();
    expect(screen.getByText(/llama3 \/ qwen2\.5-coder/)).toBeInTheDocument();
    expect(screen.getByText(/pool \(2\/3\)/)).toBeInTheDocument();
    expect(screen.getByText(/4500 ms/)).toBeInTheDocument();
    expect(screen.getByText("testing")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });
});
