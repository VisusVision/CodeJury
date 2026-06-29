import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  ListChecks,
  FileText,
  Download,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  CheckCircle2,
  Info,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import AgentCard, { type AgentStatus } from "./AgentCard";
import type { ReportData, TestResult } from "./AnalysisReport";
import type { CodeAnnotation } from "./CodeEditor";
import { useTranslation } from "@/i18n/LanguageContext";

/* ─── Types ─── */

interface AgentDef {
  id: string;
  name: string;
  description: string;
  icon: LucideIcon;
}

interface RightPanelProps {
  agents: AgentDef[];
  agentStatuses: Record<string, AgentStatus>;
  agentActions: Record<string, string>;
  findings: CodeAnnotation[];
  report: ReportData | null;
  isRunning: boolean;
  exporting: boolean;
  onExportPdf: () => void;
  onFindingClick: (line: number) => void;
}

/* ─── Severity helpers ─── */

const severityOrder = { error: 0, warning: 1, info: 2, success: 3 };

const severityIcon: Record<string, LucideIcon> = {
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
  success: CheckCircle2,
};

const severityColor: Record<string, string> = {
  error: "text-destructive",
  warning: "text-warning",
  info: "text-primary",
  success: "text-success",
};

const severityBg: Record<string, string> = {
  error: "bg-destructive/10",
  warning: "bg-warning/10",
  info: "bg-primary/10",
  success: "bg-success/10",
};

const severityLabel: Record<string, string> = {
  error: "Hata",
  warning: "Uyarı",
  info: "Bilgi",
  success: "Başarılı",
};

/* ─── Tab definitions ─── */

type TabId = "process" | "findings" | "report";

const tabs: { id: TabId; label: string; icon: LucideIcon }[] = [
  { id: "process", label: "Süreç", icon: Activity },
  { id: "findings", label: "Bulgular", icon: ListChecks },
  { id: "report", label: "Rapor", icon: FileText },
];

/* ─── Score Ring (compact) ─── */

function ScoreRingSmall({ score, max }: { score: number; max: number }) {
  const pct = Math.round((score / max) * 100);
  const r = 40;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;
  const color = pct >= 80 ? "hsl(var(--success))" : pct >= 60 ? "hsl(var(--warning))" : "hsl(var(--destructive))";

  return (
    <div className="relative w-24 h-24 shrink-0">
      <svg viewBox="0 0 90 90" className="w-full h-full -rotate-90">
        <circle cx="45" cy="45" r={r} fill="none" stroke="hsl(var(--border))" strokeWidth="6" />
        <motion.circle
          cx="45" cy="45" r={r} fill="none" stroke={color} strokeWidth="6" strokeLinecap="round"
          strokeDasharray={circ} initial={{ strokeDashoffset: circ }} animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1, ease: "easeOut" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-lg font-bold text-foreground">{pct}</span>
        <span className="text-[9px] text-muted-foreground font-medium">/ 100</span>
      </div>
    </div>
  );
}

/* ─── Rubric bar (compact) ─── */

function RubricBarSmall({ name, score, maxScore }: { name: string; score: number; maxScore: number }) {
  const pct = Math.round((score / maxScore) * 100);
  const barColor = pct >= 80 ? "bg-success" : pct >= 60 ? "bg-warning" : "bg-destructive";

  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-foreground font-medium truncate">{name}</span>
        <span className="text-muted-foreground tabular-nums shrink-0">{score}/{maxScore}</span>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <motion.div className={`h-full rounded-full ${barColor}`} initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.8, ease: "easeOut" }} />
      </div>
    </div>
  );
}

function RubricDetailRow({ name, score, maxScore }: { name: string; score: number; maxScore: number }) {
  const pct = maxScore > 0 ? Math.round((score / maxScore) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[11px] font-medium leading-snug text-foreground">{name}</span>
        <span className="shrink-0 text-[11px] font-semibold tabular-nums text-foreground">
          {score}/{maxScore}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <motion.div
          className="h-full rounded-full bg-primary"
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
    </div>
  );
}

/* ─── Main Component ─── */

function TestCasePreview({ test }: { test: TestResult }) {
  const passed = Boolean(test.passed);
  const Icon = passed ? CheckCircle2 : XCircle;

  return (
    <div className="rounded-lg border border-border bg-background px-3 py-2.5">
      <div className="mb-2 flex items-center gap-2">
        <Icon className={`h-3.5 w-3.5 ${passed ? "text-success" : "text-destructive"}`} />
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-foreground">{test.name}</span>
        {test.visibility === "hidden" ? (
          <span className="rounded-full bg-muted px-1.5 py-0.5 text-[9px] font-semibold text-muted-foreground">
            Gizli
          </span>
        ) : null}
        <span className={`rounded-full px-1.5 py-0.5 text-[9px] font-semibold ${passed ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"}`}>
          {passed ? "Gecti" : "Basarisiz"}
        </span>
      </div>
      <div className="grid gap-2">
        {[
          ["Input", test.input],
          ["Beklenen Output", test.expected],
          ["Senin Output'un", test.actual],
        ].map(([label, value]) => (
          <div key={label}>
            <div className="mb-1 text-[9px] font-semibold uppercase text-muted-foreground">{label}</div>
            <pre className="max-h-24 overflow-auto rounded-md bg-muted/50 px-2 py-1.5 font-mono-code text-[10px] leading-relaxed text-foreground whitespace-pre-wrap break-words">
              {String(value || "").trim() || "(cikti yok)"}
            </pre>
          </div>
        ))}
      </div>
    </div>
  );
}

const RightPanel = ({
  agents,
  agentStatuses,
  agentActions,
  findings,
  report,
  isRunning,
  exporting,
  onExportPdf,
  onFindingClick,
}: RightPanelProps) => {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabId>("process");
  const [rubricOpen, setRubricOpen] = useState(false);
  const [rubricPage, setRubricPage] = useState(0);

  const sortedFindings = [...findings].sort(
    (a, b) => severityOrder[a.severity] - severityOrder[b.severity]
  );

  const errorCount = findings.filter((f) => f.severity === "error").length;
  const warningCount = findings.filter((f) => f.severity === "warning").length;
  const reportIsPreparing = report?.reportStatus === "preparing";
  const rubricPageSize = 5;
  const rubricTotalPages = report ? Math.max(1, Math.ceil(report.rubric.length / rubricPageSize)) : 1;
  const rubricStart = rubricPage * rubricPageSize;
  const rubricEnd = rubricStart + rubricPageSize;
  const rubricItems = report?.rubric.slice(rubricStart, rubricEnd) ?? [];
  const testingAgent = report?.agents.find((agent) => agent.id === "testing");
  const testResults = testingAgent?.testResults ?? [];

  useEffect(() => {
    setRubricPage(0);
    setRubricOpen(false);
  }, [report]);

  useEffect(() => {
    if (rubricPage > rubricTotalPages - 1) {
      setRubricPage(0);
    }
  }, [rubricPage, rubricTotalPages]);

  return (
    <div className="flex h-full min-w-0 flex-col rounded-xl bg-card shadow-card overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-border shrink-0">
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-1.5 px-3 py-2.5 text-xs font-medium transition-colors relative ${
                isActive
                  ? "text-foreground"
                  : "text-muted-foreground hover:text-foreground/70"
              }`}
            >
              <Icon className="h-3.5 w-3.5" />
              {t(`rightPanel.${tab.id}`)}
              {tab.id === "findings" && findings.length > 0 && (
                <span className="ml-1 text-[10px] bg-destructive/10 text-destructive px-1.5 py-0.5 rounded-full tabular-nums">
                  {findings.length}
                </span>
              )}
              {tab.id === "process" && isRunning && (
                <span className="ml-1 h-2 w-2 rounded-full bg-primary animate-pulse" />
              )}
              {isActive && (
                <motion.div
                  layoutId="rightPanelTab"
                  className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full"
                  transition={{ duration: 0.2 }}
                />
              )}
            </button>
          );
        })}
      </div>

      {/* Tab content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {/* Süreç Tab */}
        {activeTab === "process" && (
          <div className="p-3 space-y-2">
            {agents.map((agent) => (
              <AgentCard
                key={agent.id}
                name={agent.name}
                description={agent.description}
                icon={agent.icon}
                status={agentStatuses[agent.id]}
                lastAction={agentActions[agent.id]}
              />
            ))}
          </div>
        )}

        {/* Bulgular Tab */}
        {activeTab === "findings" && (
          <div className="p-3 space-y-2">
            {/* Summary bar */}
            {findings.length > 0 && (
              <div className="flex items-center gap-3 px-3 py-2 rounded-lg bg-muted/50 text-[11px]">
                {errorCount > 0 && (
                  <span className="flex items-center gap-1 text-destructive font-medium">
                    <XCircle className="h-3 w-3" /> {errorCount} {t("rightPanel.error")}
                  </span>
                )}
                {warningCount > 0 && (
                  <span className="flex items-center gap-1 text-warning font-medium">
                    <AlertTriangle className="h-3 w-3" /> {warningCount} {t("rightPanel.warning")}
                  </span>
                )}
                <span className="ml-auto shrink-0 text-muted-foreground">{findings.length} {t("rightPanel.finding")}</span>
              </div>
            )}

            {sortedFindings.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground/50">
                <ListChecks className="h-8 w-8 mb-2" />
                <p className="text-xs">{t("rightPanel.noFindings")}</p>
              </div>
            ) : (
              sortedFindings.map((f, i) => {
                const Icon = severityIcon[f.severity];
                return (
                  <button
                    key={i}
                    onClick={() => onFindingClick(f.line)}
                    className={`w-full min-w-0 flex items-start gap-2 rounded-lg px-3 py-2.5 text-left transition-colors hover:ring-1 hover:ring-primary/30 ${severityBg[f.severity]}`}
                  >
                    <Icon className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${severityColor[f.severity]}`} />
                    <div className="flex-1 min-w-0">
                      <div className="mb-0.5 flex min-w-0 items-center gap-1.5">
                        <span className={`text-[10px] font-semibold uppercase ${severityColor[f.severity]}`}>
                          {t(`rightPanel.${f.severity}`)}
                        </span>
                        {f.agent && (
                          <span className="min-w-0 truncate text-[10px] text-muted-foreground">• {f.agent}</span>
                        )}
                      </div>
                      <p className="break-words text-xs leading-relaxed text-foreground">{f.message}</p>
                    </div>
                    <span className="text-[10px] text-muted-foreground font-mono-code shrink-0 mt-0.5">
                      :{f.line}
                    </span>
                  </button>
                );
              })
            )}
          </div>
        )}

        {/* Rapor Tab */}
        {activeTab === "report" && (
          <div className="p-3 space-y-4">
            {!report ? (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground/50">
                <FileText className="h-8 w-8 mb-2" />
                <p className="text-xs">{t("rightPanel.reportWaiting")}</p>
              </div>
            ) : (
              <>
                <div className={`rounded-xl border px-3 py-3 ${reportIsPreparing ? "border-primary/20 bg-primary/5" : "border-border bg-muted/30"}`}>
                  <div className="flex items-start gap-3">
                    <div className={`mt-0.5 rounded-full p-2 ${reportIsPreparing ? "bg-primary/10 text-primary" : "bg-success/10 text-success"}`}>
                      <FileText className={`h-4 w-4 ${reportIsPreparing ? "animate-pulse" : ""}`} />
                    </div>
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-foreground">
                        {reportIsPreparing ? t("rightPanel.reportPreparingTitle") : t("rightPanel.reportReadyTitle")}
                      </p>
                      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                        {reportIsPreparing ? t("rightPanel.reportPreparingBody") : t("rightPanel.reportReadyBody")}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Download button */}
                <button
                  onClick={onExportPdf}
                  disabled={exporting || reportIsPreparing}
                  className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium shadow-button-primary hover:brightness-110 transition-all disabled:opacity-50"
                >
                  <Download className="h-4 w-4" />
                  {exporting ? t("rightPanel.exporting") : reportIsPreparing ? t("rightPanel.reportPreparingShort") : t("rightPanel.exportPdf")}
                </button>

                {/* Score */}
                <div className="flex flex-col lg:flex-row lg:items-center gap-4">
                  <ScoreRingSmall score={report.totalScore} max={report.maxScore} />

                  <div className="min-w-0 flex-1 overflow-hidden rounded-xl border border-border bg-card">
                    <div className="flex items-stretch justify-between gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/40">
                      <button
                        type="button"
                        onClick={() => setRubricOpen((open) => !open)}
                        className="min-w-0 flex-1 text-left"
                        aria-expanded={rubricOpen}
                        aria-controls="rubric-criteria-panel"
                      >
                        <h3 className="text-xs font-semibold text-foreground">Rubrik Kriterleri</h3>
                        <p className="text-[11px] text-muted-foreground">
                          {report.rubric.length} kriter • {rubricPage + 1}/{rubricTotalPages} sayfa
                        </p>
                      </button>
                      <div className="flex items-center gap-1 self-center">
                        <button
                          type="button"
                          onClick={() => {
                            setRubricPage((page) => Math.max(0, page - 1));
                            setRubricOpen(true);
                          }}
                          disabled={rubricPage === 0}
                          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                          aria-label="Önceki 5 kriter"
                        >
                          <ChevronUp className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setRubricPage((page) => Math.min(rubricTotalPages - 1, page + 1));
                            setRubricOpen(true);
                          }}
                          disabled={rubricPage >= rubricTotalPages - 1}
                          className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-40"
                          aria-label="Sonraki 5 kriter"
                        >
                          <ChevronDown className="h-4 w-4" />
                        </button>
                      </div>
                    </div>
                    {rubricOpen && (
                      <motion.div
                        id="rubric-criteria-panel"
                        initial={{ height: 0, opacity: 0 }}
                        animate={{ height: "auto", opacity: 1 }}
                        exit={{ height: 0, opacity: 0 }}
                        className="space-y-2 border-t border-border bg-muted/20 px-3 py-2.5"
                      >
                        {rubricItems.map((cat) => (
                          <RubricDetailRow
                            key={cat.name}
                            name={cat.name}
                            score={cat.score}
                            maxScore={cat.maxScore}
                          />
                        ))}
                      </motion.div>
                    )}
                  </div>
                </div>

                {/* Agent summaries */}
                <div className="space-y-2">
                  <h3 className="text-xs font-semibold text-foreground">{t("rightPanel.agentSummaries")}</h3>
                  {report.agents.map((agent) => {
                    const pct = Math.round((agent.score / agent.maxScore) * 100);
                    const Icon = agent.icon;
                    return (
                      <div key={agent.id} className="flex items-start gap-2.5 rounded-lg bg-muted/30 px-3 py-2.5">
                        <div className="rounded-md bg-muted p-1.5 shrink-0">
                          <Icon className="h-3 w-3 text-foreground" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-foreground">{agent.name}</span>
                            <span className="text-xs font-bold text-foreground tabular-nums">{pct}%</span>
                          </div>
                          <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">{agent.summary}</p>
                        </div>
                      </div>
                    );
                  })}
                </div>

                {testResults.length > 0 ? (
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-foreground">Test Case Sonuclari</h3>
                    <div className="space-y-2">
                      {testResults.map((test, index) => (
                        <TestCasePreview key={`${test.name}-${index}`} test={test} />
                      ))}
                    </div>
                  </div>
                ) : null}

              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default RightPanel;
