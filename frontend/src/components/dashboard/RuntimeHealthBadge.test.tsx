import { render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import RuntimeHealthBadge from "./RuntimeHealthBadge";

vi.mock("@/i18n/LanguageContext", () => ({
  useTranslation: () => ({
    language: "tr",
    t: (key: string) => key,
  }),
}));

vi.mock("@/hooks/useRuntimeHealth", () => ({
  useRuntimeHealth: () => ({
    loading: false,
    health: {
      status: "ok",
      llm: { enabled: true, general_model: "llama3", coder_model: "qwen2.5-coder" },
      sandbox: { mode: "pool", pool_ready: true, container_count: 3, available_count: 2 },
    },
  }),
}));

describe("RuntimeHealthBadge", () => {
  test("renders llm and sandbox snapshot from health hook", () => {
    render(<RuntimeHealthBadge />);

    expect(screen.getByText("runtimeHealth.title")).toBeInTheDocument();
    expect(screen.getByText("llama3 / qwen2.5-coder")).toBeInTheDocument();
    expect(screen.getByText("pool (2/3)")).toBeInTheDocument();
  });
});
