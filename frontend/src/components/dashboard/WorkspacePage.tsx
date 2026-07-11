import { useState, useCallback, useRef, useEffect, useMemo } from "react";
import { Play, StopCircle, ArrowLeft, LogOut, BookOpen } from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import html2canvas from "html2canvas-pro";
import jsPDF from "jspdf";
import {
  FlaskConical,
  Code2,
  GraduationCap,
  BookCheck,
  Search,
  Brain,
  ShieldAlert,
  FileCode,
  FolderOpen,
  X,
  Star,
  Sparkles,
  CheckCircle2,
  BarChart3,
  Fingerprint,
} from "lucide-react";
import { toast } from "sonner";
import FileUploadZone from "@/components/dashboard/FileUploadZone";
import { type AgentStatus } from "@/components/dashboard/AgentCard";
import LogPanel, { type LogEntry } from "@/components/dashboard/LogPanel";
import CodeEditor, { type CodeAnnotation } from "@/components/dashboard/CodeEditor";
import { type ReportData } from "@/components/dashboard/AnalysisReport";
import { buildPdfReportSectionsHtml } from "@/components/dashboard/reportPdfSections";
import { analyzeCode, createUploadHistoryRecord, getUploadHistoryRecords, getAssignmentQuestions, getCurrentEvaluation, submitEvaluation, fetchHealth, type ApiAnalysisResult, type QuestionItem, type EvaluationRecord } from "@/services/api";
import UploadHistory, { type UploadRecord } from "@/components/dashboard/UploadHistory";
import ExecutionStats from "@/components/dashboard/ExecutionStats";
import RightPanel from "@/components/dashboard/RightPanel";
import RuntimeHealthBadge from "@/components/dashboard/RuntimeHealthBadge";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { splitAssignmentDescription } from "@/lib/assignmentDescription";
import { checkAnalysisPreflight } from "@/lib/analysisPreflight";
import { useAuth } from "../../auth/AuthContext";

interface UploadedFile {
  name: string;
  size: number;
  type: string;
  content: string;
}

interface AgentDef {
  id: string;
  name: string;
  description: string;
  icon: typeof FlaskConical;
}

const agentKeys = [
  { id: "testing", nameKey: "agents.testAgent", descKey: "agents.testAgentDesc", icon: FlaskConical },
  { id: "quality", nameKey: "agents.codeQuality", descKey: "agents.codeQualityDesc", icon: Code2 },
  { id: "algorithm", nameKey: "agents.algorithm", descKey: "agents.algorithmDesc", icon: BarChart3 },
  { id: "seniority", nameKey: "agents.seniority", descKey: "agents.seniorityDesc", icon: GraduationCap },
  { id: "guideline", nameKey: "agents.guideline", descKey: "agents.guidelineDesc", icon: BookCheck },
  { id: "security", nameKey: "agents.security", descKey: "agents.securityDesc", icon: ShieldAlert },
  { id: "ai_authorship", nameKey: "agents.aiAuthorship", descKey: "agents.aiAuthorshipDesc", icon: Fingerprint },
  { id: "evidence", nameKey: "agents.evidence", descKey: "agents.evidenceDesc", icon: Search },
  { id: "orchestrator", nameKey: "agents.rubric", descKey: "agents.rubricDesc", icon: Brain },
];

// Map agent IDs to their icons for restoring from sessionStorage
const agentIconMap: Record<string, typeof FlaskConical> = {
  testing: FlaskConical,
  quality: Code2,
  algorithm: BarChart3,
  seniority: GraduationCap,
  guideline: BookCheck,
  security: ShieldAlert,
  ai_authorship: Fingerprint,
  evidence: Search,
  orchestrator: Brain,
};

interface WorkspacePageProps {
  sidebarTitle: string;
  sidebarSubtitle: string;
  headerTitle: string;
  assignmentDescription?: string | null;
  assignmentId: string;
  studentNo: string;
  assignmentDueDate?: string | null;
  onBack: () => void;
}

interface RatingRowProps {
  value: number;
  onChange: (value: number) => void;
  label: string;
  scale: string[];
}

const RatingRow = ({ value, onChange, label, scale }: RatingRowProps) => {
  const [hover, setHover] = useState(0);
  const display = hover || value;

  return (
    <div className="space-y-2">
      <p className="text-sm font-medium text-foreground">{label}</p>
      <div className="flex items-center gap-1.5">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            onMouseEnter={() => setHover(n)}
            onMouseLeave={() => setHover(0)}
            onClick={() => onChange(n)}
            className="rounded-md p-1 hover:bg-muted transition-colors"
            aria-label={`${n} ${scale[n - 1]}`}
          >
            <Star
              className={cn(
                "h-7 w-7 transition-all",
                n <= display
                  ? "fill-yellow-400 text-yellow-400 drop-shadow-[0_0_6px_rgba(250,204,21,0.4)]"
                  : "text-muted-foreground/40"
              )}
            />
          </button>
        ))}
        <span className="ml-2 min-w-[88px] text-xs text-muted-foreground tabular-nums">{display ? scale[display - 1] : ""}</span>
      </div>
    </div>
  );
};

interface EvaluationModalProps {
  open: boolean;
  blocking?: boolean;
  language: string;
  contextLabel: string;
  onClose: () => void;
  onSubmit: (data: { usefulness: number; accuracy: number; clarity: number; comment: string }) => Promise<void>;
}

const EvaluationModal = ({ open, blocking, language, contextLabel, onClose, onSubmit }: EvaluationModalProps) => {
  const labelsTr = {
    title: "Raporu Değerlendir",
    context: "Değerlendirilecek Rapor",
    usefulness: "Bu rapor sizin için ne kadar faydalıydı?",
    accuracy: "Değerlendirme ne kadar doğruydu?",
    clarity: "Açıklamalar ne kadar anlaşılırdı?",
    comment: "Eklemek istediğiniz bir şey var mı? (isteğe bağlı)",
    commentPh: "Düşüncelerinizi paylaşın...",
    submit: "Değerlendirmeyi Gönder",
    sending: "Gönderiliyor...",
    required: "Lütfen üç kriteri de puanlayın.",
    blockedHint: "Yeni bir analiz başlatmak için önce bu raporu değerlendirin.",
    scale: ["Çok kötü", "Kötü", "Orta", "İyi", "Mükemmel"],
  };
  const labelsEn = {
    title: "Rate this report",
    context: "Report to review",
    usefulness: "How useful was this report for you?",
    accuracy: "How accurate was the evaluation?",
    clarity: "How clear were the explanations?",
    comment: "Anything to add? (optional)",
    commentPh: "Share your thoughts...",
    submit: "Submit feedback",
    sending: "Sending...",
    required: "Please rate all three criteria.",
    blockedHint: "Rate this report before starting a new analysis.",
    scale: ["Very poor", "Poor", "Average", "Good", "Excellent"],
  };

  const L = language === "en" ? labelsEn : labelsTr;
  const [usefulness, setUsefulness] = useState(0);
  const [accuracy, setAccuracy] = useState(0);
  const [clarity, setClarity] = useState(0);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setUsefulness(0);
      setAccuracy(0);
      setClarity(0);
      setComment("");
      setError(null);
      setSubmitting(false);
    }
  }, [open]);

  const handleSubmit = async () => {
    if (!usefulness || !accuracy || !clarity) {
      setError(L.required);
      return;
    }
    setError(null);
    setSubmitting(true);
    try {
      await onSubmit({ usefulness, accuracy, clarity, comment: comment.trim() });
      onClose();
    } catch (submissionError) {
      setError(submissionError instanceof Error ? submissionError.message : "Error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4"
          onClick={() => { if (!blocking && !submitting) onClose(); }}
        >
          <motion.div
            initial={{ scale: 0.94, opacity: 0, y: 18 }}
            animate={{ scale: 1, opacity: 1, y: 0 }}
            exit={{ scale: 0.96, opacity: 0 }}
            transition={{ type: "spring", stiffness: 280, damping: 24 }}
            onClick={(e) => e.stopPropagation()}
            className="relative w-full max-w-lg overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
          >
            <div className="relative bg-gradient-to-br from-primary/15 via-primary/5 to-transparent px-4 pb-3 pt-4">
              {!blocking && (
                <button
                  type="button"
                  onClick={onClose}
                  disabled={submitting}
                  className="absolute right-3 top-3 rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
              <div className="flex items-center gap-2">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/15">
                  <Sparkles className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <h2 className="text-lg font-bold text-foreground">{L.title}</h2>
                </div>
              </div>
              <div className="mt-2 text-xs text-muted-foreground">
                <span className="font-semibold">{L.context}:</span> {contextLabel}
              </div>
              {blocking && (
                <div className="mt-2 rounded-lg border border-warning/30 bg-warning/10 px-2 py-1 text-xs text-warning">
                  {L.blockedHint}
                </div>
              )}
            </div>

            <div className="space-y-4 px-4 py-4">
              <RatingRow value={usefulness} onChange={setUsefulness} label={L.usefulness} scale={L.scale} />
              <RatingRow value={accuracy} onChange={setAccuracy} label={L.accuracy} scale={L.scale} />
              <RatingRow value={clarity} onChange={setClarity} label={L.clarity} scale={L.scale} />

              <div className="space-y-1.5">
                <p className="text-sm font-medium text-foreground">{L.comment}</p>
                <textarea
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder={L.commentPh}
                  rows={3}
                  className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              </div>

              {error && (
                <p className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
                  {error}
                </p>
              )}
            </div>

            <div className="px-6 pb-6">
              <button
                type="button"
                onClick={handleSubmit}
                disabled={submitting}
                className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-button-primary transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {submitting ? L.sending : L.submit}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
};

const WORKSPACE_CACHE_VERSION = 5;
const getStorageKey = (assignmentId: string, studentNo: string) =>
  `workspace_${studentNo}_${assignmentId}_cv${WORKSPACE_CACHE_VERSION}`;

interface PersistedState {
  files: UploadedFile[];
  activeFile: string | null;
  logs: LogEntry[];
  report: ReportData | null;
  uploadRecords: UploadRecord[];
  findings: CodeAnnotation[];
  hasEverRun: boolean;
}

const loadPersistedState = (assignmentId: string, studentNo: string): PersistedState | null => {
  try {
    const raw = localStorage.getItem(getStorageKey(assignmentId, studentNo));
    if (!raw) return null;
    const state = JSON.parse(raw) as PersistedState;
    // Restore icon functions lost during JSON serialization
    if (state.report?.agents) {
      state.report.agents = state.report.agents.map((a) => ({
        ...a,
        icon: agentIconMap[a.id] || FlaskConical,
      }));
    }
    return state;
  } catch {
    return null;
  }
};

const savePersistedState = (assignmentId: string, studentNo: string, state: PersistedState) => {
  try {
    localStorage.setItem(getStorageKey(assignmentId, studentNo), JSON.stringify(state));
  } catch {
    // storage full, ignore
  }
};

function mapFormalTestResult(raw: import("@/services/api").ApiTestResult): import("./AnalysisReport").TestResult {
  return {
    name: raw.name,
    input: raw.input,
    expected: raw.expected,
    actual: raw.actual,
    passed: raw.passed,
    visibility: raw.visibility,
    status: raw.status,
    source: raw.source,
    matchPct: raw.matchPct,
    diffDetail: raw.diffDetail,
    errorType: raw.errorType,
    errorMessageTr: raw.errorMessageTr,
    actualStderr: raw.actualStderr,
    files: raw.files,
    oracleValidation: raw.oracleValidation,
    id: raw.id,
  };
}

function buildReportData(result: ApiAnalysisResult, fileContent: string): ReportData {
  return {
    totalScore: result.totalScore,
    maxScore: result.maxScore,
    rubric: result.rubric,
    agents: result.agents.map((agent) => ({
      ...agent,
      icon: agentIconMap[agent.id] || FlaskConical,
      testResults: agent.testResults?.map(mapFormalTestResult),
    })),
    evidence: result.evidence,
    rejectedClaims: result.rejectedClaims ?? [],
    fileName: result.fileName,
    fileContent,
    executionTimeMs: result.executionTimeMs,
    memoryUsageMb: result.memoryUsageMb,
    peakMemoryMb: result.peakMemoryMb,
    summary: result.summary ?? "",
    strengths: result.strengths ?? [],
    weaknesses: result.weaknesses ?? [],
    recommendations: result.recommendations ?? [],
    resourceRecommendations: result.resourceRecommendations ?? [],
    relevanceScoreWarning: result.relevanceScoreWarning ?? undefined,
    taskAlignment: result.taskAlignment,
    reportStatus: result.reportStatus ?? "ready",
    agentDiagnostics: result.agentDiagnostics,
    testSource: result.testSource,
    testEvidenceStatus: result.testEvidenceStatus,
    formalPassed: result.formalPassed,
    formalTotal: result.formalTotal,
    hiddenTestSummary: result.hiddenTestSummary,
    testSetId: result.testSetId,
    testSetHash: result.testSetHash,
    cacheVersion: result.cacheVersion,
    audience: "student",
  };
}

function buildCodeAnnotations(result: ApiAnalysisResult): CodeAnnotation[] {
  return result.evidence
    .filter((e) => e.line > 0)
    .map((e) => ({
      line: e.line,
      severity: e.severity,
      message: e.message,
      agent: e.agent,
    }));
}

const WorkspacePage = ({ sidebarTitle, sidebarSubtitle, headerTitle, assignmentDescription, assignmentId, studentNo, assignmentDueDate, onBack }: WorkspacePageProps) => {
  const { user, logout } = useAuth();
  const { t, language } = useTranslation();
  const agentDefs: AgentDef[] = useMemo(() =>
    agentKeys.map((a) => ({ id: a.id, name: t(a.nameKey), description: t(a.descKey), icon: a.icon })),
    [t],
  );

  const persisted = useRef(loadPersistedState(assignmentId, studentNo));
  const studentInitial = (sidebarTitle?.trim().charAt(0) || "A").toUpperCase();
  const isPastDue = Boolean(assignmentDueDate && new Date(assignmentDueDate) < new Date());

  const [files, setFiles] = useState<UploadedFile[]>(persisted.current?.files || []);
  const [activeFile, setActiveFile] = useState<string | null>(persisted.current?.activeFile || null);
  const [agentStatuses, setAgentStatuses] = useState<Record<string, AgentStatus>>(
    Object.fromEntries(agentKeys.map((a) => [a.id, (persisted.current?.hasEverRun ? "done" : "idle") as AgentStatus]))
  );
  const [agentActions, setAgentActions] = useState<Record<string, string>>({});
  const [logs, setLogs] = useState<LogEntry[]>(persisted.current?.logs || []);
  const [isRunning, setIsRunning] = useState(false);
  const [report, setReport] = useState<ReportData | null>(persisted.current?.report || null);
  const [uploadRecords, setUploadRecords] = useState<UploadRecord[]>(persisted.current?.uploadRecords || []);
  const [findings, setFindings] = useState<CodeAnnotation[]>(persisted.current?.findings || []);
  const [highlightedLine, setHighlightedLine] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [hasEverRun, setHasEverRun] = useState(persisted.current?.hasEverRun || false);
  const [assignmentQuestions, setAssignmentQuestions] = useState<Record<string, QuestionItem[]>>({});
  const [loadingQuestions, setLoadingQuestions] = useState<Record<string, boolean>>({});
  const [hoveredAssignmentId, setHoveredAssignmentId] = useState<string | null>(null);
  const hoverTimeoutRef = useRef<Record<string, number | null>>({});
  const analysisAbortRef = useRef<AbortController | null>(null);
  const analysisInFlightRef = useRef(false);
  const [currentEvaluation, setCurrentEvaluation] = useState<EvaluationRecord | null>(null);
  const [evaluationOpen, setEvaluationOpen] = useState(false);

  useEffect(() => {
    const loadUploadHistory = async () => {
      try {
        if (!studentNo) return;
        const rows = await getUploadHistoryRecords(studentNo, assignmentId);
        const mapped: UploadRecord[] = rows.map((r) => ({
          id: r.id,
          fileName: r.uploaded_file_name,
          timestamp: new Date(r.uploaded_at),
          hasError: Boolean(r.has_error),
          score: r.score ?? undefined,
        }));
        setUploadRecords(mapped);
      } catch (error) {
        console.error("Yükleme geçmişi getirilemedi:", error);
      }
    };
    void loadUploadHistory();
  }, [assignmentId, studentNo]);

  useEffect(() => {
    const loadEvaluation = async () => {
      try {
        if (!studentNo) return;
        const record = await getCurrentEvaluation(studentNo, assignmentId);
        setCurrentEvaluation(record);
        if (record?.status === "pending") {
          setEvaluationOpen(true);
        }
      } catch (error) {
        console.error("Değerlendirme durumu alınamadı:", error);
      }
    };
    void loadEvaluation();
  }, [assignmentId, studentNo]);

  // Persist state on changes
  useEffect(() => {
    savePersistedState(assignmentId, studentNo, {
      files, activeFile, logs, report, uploadRecords, findings, hasEverRun,
    });
  }, [assignmentId, studentNo, files, activeFile, logs, report, uploadRecords, findings, hasEverRun]);

  const handleFilesUploaded = useCallback((newFiles: UploadedFile[]) => {
    setFiles((prev) => {
      const existing = new Set(prev.map((f) => f.name));
      const unique = newFiles.filter((f) => !existing.has(f.name));

      return [...prev, ...unique];
    });
    if (newFiles.length > 0 && !activeFile) {
      setActiveFile(newFiles[0].name);
    }
  }, [activeFile]);

  const handleRemoveFile = useCallback((name: string) => {
    if (isPastDue) return;
    setFiles((prev) => {
      const remaining = prev.filter((f) => f.name !== name);
      if (remaining.length === 0 && hasEverRun) {
        setLogs([]);
        setAgentStatuses(Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus])));
        setAgentActions({});
        setReport(null);
        setFindings([]);
        setHighlightedLine(null);
        setIsRunning(false);
        setHasEverRun(false);
      }
      return remaining;
    });
    if (activeFile === name) setActiveFile(null);
  }, [activeFile, agentDefs, hasEverRun, isPastDue]);

  const addLog = useCallback((agent: string, message: string, type: LogEntry["type"] = "info") => {
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
    setLogs((prev) => [...prev, { id: `${Date.now()}-${Math.random()}`, timestamp: ts, agent, message, type }]);
  }, []);

  const loadAssignmentQuestions = async () => {
    if (assignmentQuestions[assignmentId]) return;
    setLoadingQuestions((prev) => ({ ...prev, [assignmentId]: true }));
    try {
      const questions = await getAssignmentQuestions(assignmentId);
      setAssignmentQuestions((prev) => ({ ...prev, [assignmentId]: questions }));
    } catch (error) {
      console.error("Sorular yüklenemedi:", error);
      setAssignmentQuestions((prev) => ({ ...prev, [assignmentId]: [] }));
    } finally {
      setLoadingQuestions((prev) => ({ ...prev, [assignmentId]: false }));
    }
  };

  const handleBadgeMouseEnter = () => {
    const t = hoverTimeoutRef.current[assignmentId];
    if (t) {
      window.clearTimeout(t);
      hoverTimeoutRef.current[assignmentId] = null;
    }
    setHoveredAssignmentId(assignmentId);
    void loadAssignmentQuestions();
  };

  const handleBadgeMouseLeave = () => {
    hoverTimeoutRef.current[assignmentId] = window.setTimeout(() => {
      if (hoveredAssignmentId === assignmentId) setHoveredAssignmentId(null);
      hoverTimeoutRef.current[assignmentId] = null;
    }, 150) as unknown as number;
  };

  const runAnalysis = useCallback(async () => {
    if (analysisInFlightRef.current) return;
    if (currentEvaluation?.status === "pending") {
      toast.error(language === "tr" ? "Önce açık değerlendirmeyi tamamlayın." : "Complete the active evaluation first.");
      setEvaluationOpen(true);
      return;
    }
    if (isPastDue) {
      addLog("System", t("workspace.analysisError"), "error");
      return;
    }
    if (files.length === 0) return;

    const health = await fetchHealth();
    const preflight = checkAnalysisPreflight(health, {
      healthUnavailable: t("workspace.preflight.healthUnavailable"),
      llmDisabled: t("workspace.preflight.llmDisabled"),
      sandboxUnavailable: t("workspace.preflight.sandboxUnavailable"),
      durationHint: t("workspace.preflight.durationHint"),
    });
    if (!preflight.ok) {
      toast.error(preflight.reason);
      return;
    }
    if (preflight.warnings.length > 0) {
      toast.info(preflight.warnings.join(" "));
    }

    analysisInFlightRef.current = true;
    analysisAbortRef.current?.abort();
    const abortController = new AbortController();
    analysisAbortRef.current = abortController;
    setHasEverRun(true);
    setIsRunning(true);
    setLogs([]);
    setFindings([]);
    setHighlightedLine(null);
    setReport(null);
    setAgentStatuses(Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus])));
    setAgentActions({});

    const firstFile = files[0];
    if (!firstFile) { setIsRunning(false); return; }

    const newRecord = {
      id: `${Date.now()}-${Math.random()}`,
      fileName: firstFile.name,
      timestamp: new Date(),
      hasError: false,
    };
    setUploadRecords((prev) => [...prev, newRecord]);

    addLog("System", t("workspace.analyzing") + `... (${files.length})`, "info");

    // Set all agents to thinking
    agentDefs.forEach((a) => {
      setAgentStatuses((p) => ({ ...p, [a.id]: "thinking" }));
    });
    addLog("System", t("workspace.running"), "info");

    try {
      const loggedAgentIds = new Set<string>();
      let loggedFinalScore = false;
      let loggedReportPreparing = false;

      const applyAnalysisResult = (result: ApiAnalysisResult) => {
        result.agents.forEach((agent) => {
          setAgentStatuses((p) => ({ ...p, [agent.id]: "done" }));
          const pct = Math.round((agent.score / agent.maxScore) * 100);
          setAgentActions((p) => ({ ...p, [agent.id]: `${agent.summary} (${pct}%)` }));
          if (!loggedAgentIds.has(agent.id)) {
            addLog(agent.name, agent.summary, "success");
            loggedAgentIds.add(agent.id);
          }
        });

        const totalPct = Math.round((result.totalScore / result.maxScore) * 100);
        setAgentStatuses((p) => ({ ...p, orchestrator: "done" }));
        setAgentActions((p) => ({
          ...p,
          orchestrator: `${language === "tr" ? "Nihai puan" : "Final score"}: ${result.totalScore}/${result.maxScore}`,
        }));
        if (!loggedFinalScore) {
          addLog(
            t("agents.rubric"),
            `${language === "tr" ? "Nihai puan" : "Final score"}: ${result.totalScore}/${result.maxScore} (${totalPct}%)`,
            "success",
          );
          loggedFinalScore = true;
        }

        if (result.reportStatus === "preparing" && !loggedReportPreparing) {
          addLog(
            "System",
            language === "tr"
              ? "Ajan analizleri tamamlandı, rapor ve PDF hazırlanıyor."
              : "Agent analysis is complete, the report and PDF are being prepared.",
            "info",
          );
          loggedReportPreparing = true;
        }

        setReport(buildReportData(result, firstFile.content));
        setFindings(buildCodeAnnotations(result));
      };

      // Call the FastAPI backend
      const result: ApiAnalysisResult = await analyzeCode(
        firstFile.name,
        firstFile.content,
        assignmentId,
        language,
        studentNo,
        abortController.signal,
        (partialResult) => {
          applyAnalysisResult(partialResult);
        },
      );

      applyAnalysisResult(result);
      const totalPct = Math.round((result.totalScore / result.maxScore) * 100);

      // Update upload records with score
      setUploadRecords((prev) => {
        const updated = [...prev];
        let lastIdx = -1;
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].fileName === firstFile.name) { lastIdx = i; break; }
        }
        if (lastIdx >= 0) updated[lastIdx] = { ...updated[lastIdx], score: totalPct };
        return updated;
      });

      try {
        if (user) {
          await createUploadHistoryRecord({
            student_first_name: String(user.first_name ?? ""),
            student_last_name: String(user.last_name ?? ""),
            student_no: studentNo,
            uploaded_file_name: firstFile.name,
            assignment_id: assignmentId,
            score: totalPct,
            has_error: false,
          });
          const record = await getCurrentEvaluation(studentNo, assignmentId);
          setCurrentEvaluation(record);
          if (record?.status === "pending") {
            toast.info(language === "tr" ? "Rapor oluştu. Lütfen önce değerlendirin." : "Report is ready. Please rate it first.");
          }
        }
      } catch (error) {
        console.error("Yükleme geçmişi kaydedilemedi:", error);
      }

    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        addLog("System", language === "tr" ? "Analiz iptal edildi." : "Analysis cancelled.", "info");
        setAgentStatuses(Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus])));
        setAgentActions({});
        return;
      }
      const errorMsg = err instanceof Error ? err.message : t("common.error");
      addLog("System", `${t("workspace.analysisError")}: ${errorMsg}`, "error");
      agentDefs.forEach((a) => {
        setAgentStatuses((p) => ({ ...p, [a.id]: "error" }));
      });

      // Update upload records to show error
      setUploadRecords((prev) => {
        const updated = [...prev];
        let lastIdx = -1;
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].fileName === firstFile.name) { lastIdx = i; break; }
        }
        if (lastIdx >= 0) updated[lastIdx] = { ...updated[lastIdx], hasError: true };
        return updated;
      });

      try {
        if (user) {
          await createUploadHistoryRecord({
            student_first_name: String(user.first_name ?? ""),
            student_last_name: String(user.last_name ?? ""),
            student_no: studentNo,
            uploaded_file_name: firstFile.name,
            assignment_id: assignmentId,
            has_error: true,
          });
        }
      } catch (error) {
        console.error("Yükleme geçmişi kaydedilemedi:", error);
      }
    } finally {
      if (analysisAbortRef.current === abortController) {
        analysisAbortRef.current = null;
      }
      analysisInFlightRef.current = false;
      setIsRunning(false);
    }
  }, [agentDefs, currentEvaluation?.status, files, addLog, assignmentId, isPastDue, language, studentNo, t, user]);

  const handleEvaluationSubmit = useCallback(async (data: { usefulness: number; accuracy: number; clarity: number; comment: string }) => {
    if (!studentNo) {
      throw new Error(language === "tr" ? "Öğrenci oturumu bulunamadı." : "Student session not found.");
    }
    if (!currentEvaluation?.assignment_id) {
      throw new Error(language === "tr" ? "Değerlendirilecek aktif rapor bulunamadı." : "No active report found.");
    }
    const record = await submitEvaluation({
      student_no: studentNo,
      assignment_id: currentEvaluation.assignment_id,
      usefulness: data.usefulness,
      accuracy: data.accuracy,
      clarity: data.clarity,
      comment: data.comment,
    });
    setCurrentEvaluation(record);
    toast.success(language === "tr" ? "Değerlendirme gönderildi." : "Feedback submitted.");
    setEvaluationOpen(false);
  }, [currentEvaluation?.assignment_id, language, studentNo]);

  const handleRunAgentsClick = useCallback(() => {
    if (currentEvaluation?.status === "pending") {
      toast.error(language === "tr" ? "Önce mevcut raporu değerlendirin." : "Please rate the current report first.");
      setEvaluationOpen(true);
      return;
    }
    void runAnalysis();
  }, [currentEvaluation?.status, language, runAnalysis]);

  const handleFindingClick = useCallback((line: number) => {
    setHighlightedLine(line);
  }, []);

  const handleExportPdf = useCallback(async () => {
    if (!report) return;
    if (report.reportStatus === "preparing") {
      toast.info(language === "tr" ? "PDF rapor hala hazırlanıyor." : "The PDF report is still being prepared.");
      return;
    }
    setExporting(true);
    try {
      const tempDiv = document.createElement("div");
      tempDiv.style.position = "absolute";
      tempDiv.style.left = "-9999px";
      tempDiv.style.width = "800px";
      tempDiv.style.padding = "20px";
      tempDiv.style.background = "#ffffff";

      const escapeHtml = (value: string) =>
        value
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#39;");

      const now = new Date();
      const dateStr = now.toLocaleString("tr-TR", {
        day: "2-digit",
        month: "long",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });

      const studentName = `${String(user?.first_name ?? "")} ${String(user?.last_name ?? "")}`.trim() || sidebarTitle || "-";
      const departmentName = user?.department_name != null ? String(user.department_name).trim() || "-" : "-";
      const scorePct = Math.round((report.totalScore / report.maxScore) * 100);
      const scoreColor = scorePct >= 80 ? "#059669" : scorePct >= 60 ? "#d97706" : "#dc2626";
      const scoreBg = "#f9fafb";

      const rubricCards = report.rubric
        .map((category) => {
          const pct = Math.round((category.score / category.maxScore) * 100);
          return `
            <div style="padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;background:#ffffff;font-size:11px;display:flex;justify-content:space-between;gap:8px;align-items:center;min-height:38px;height:100%;box-sizing:border-box;">
              <span style="font-weight:600;color:#111827;line-height:1.2;min-width:0;overflow-wrap:anywhere;">${escapeHtml(category.name)}</span>
              <span style="font-weight:700;color:#111827;white-space:nowrap;">${pct}/100</span>
            </div>
          `;
        })
        .join("");

      const agentCards = report.agents
        .map((agent) => {
          const pct = Math.round((agent.score / agent.maxScore) * 100);
          return `
            <div style="padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px;background:#f9fafb;font-size:11px;min-height:58px;height:100%;box-sizing:border-box;display:flex;flex-direction:column;">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="font-weight:700;color:#111827;line-height:1.2;min-width:0;overflow-wrap:anywhere;">${escapeHtml(agent.name)}</span>
                <span style="font-weight:700;color:#111827;white-space:nowrap;">${pct}%</span>
              </div>
              <div style="color:#4b5563;line-height:1.3;flex:1;overflow-wrap:anywhere;">${escapeHtml(agent.summary)}</div>
            </div>
          `;
        })
        .join("");

      const testingAgent = report.agents.find((agent) => agent.id === "testing");
      const testCaseCards = (testingAgent?.testResults ?? [])
        .map((test, index) => {
          const statusColor = test.passed ? "#047857" : "#dc2626";
          const statusBg = test.passed ? "#ecfdf5" : "#fef2f2";
          const visibility = test.visibility === "hidden" ? "Gizli test" : `Test ${index + 1}`;
          const empty = "(cikti yok)";
          return `
            <div style="border:1px solid #e5e7eb;border-radius:8px;background:#ffffff;padding:8px 10px;break-inside:avoid;">
              <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;margin-bottom:6px;">
                <div style="font-size:11px;font-weight:800;color:#111827;line-height:1.2;min-width:0;overflow-wrap:anywhere;">${escapeHtml(test.name)}</div>
                <div style="display:flex;gap:4px;align-items:center;white-space:nowrap;">
                  <span style="font-size:9px;font-weight:700;color:#6b7280;background:#f3f4f6;border-radius:999px;padding:2px 6px;">${visibility}</span>
                  <span style="font-size:9px;font-weight:800;color:${statusColor};background:${statusBg};border-radius:999px;padding:2px 6px;">${test.passed ? "Gecti" : "Basarisiz"}</span>
                </div>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;">
                ${[
                  ["Input", test.input],
                  ["Beklenen Output", test.expected],
                  ["Senin Output'un", test.actual],
                ].map(([label, value]) => `
                  <div>
                    <div style="font-size:9px;font-weight:800;color:#6b7280;text-transform:uppercase;margin-bottom:3px;">${escapeHtml(label)}</div>
                    <div style="min-height:34px;max-height:78px;overflow:hidden;border:1px solid #e5e7eb;border-radius:6px;background:#f9fafb;padding:6px;font-family:monospace;font-size:9.5px;line-height:1.35;color:#111827;white-space:pre-wrap;overflow-wrap:anywhere;">${escapeHtml(String(value || "").trim() || empty)}</div>
                  </div>
                `).join("")}
              </div>
            </div>
          `;
        })
        .join("");

      const suggestionRows = findings
        .filter((item) => item.severity === "error" || item.severity === "warning")
        .map((item) => {
          const rowBg = item.severity === "error" ? "#fef2f2" : "#fffbeb";
          return `
            <tr style="background:${rowBg};">
              <td style="padding:7px 8px;border-bottom:1px solid #e5e7eb;width:70px;text-align:center;font-weight:700;color:#1f2937;">${item.line || "-"}</td>
              <td style="padding:7px 8px;border-bottom:1px solid #e5e7eb;color:#374151;line-height:1.3;">${escapeHtml(item.message)}</td>
            </tr>
          `;
        })
        .join("");

      const suggestionTableBody = suggestionRows || `
        <tr style="background:#f9fafb;">
          <td style="padding:7px 8px;border-bottom:1px solid #e5e7eb;text-align:center;font-weight:700;color:#6b7280;">-</td>
          <td style="padding:7px 8px;border-bottom:1px solid #e5e7eb;color:#6b7280;">Hata veya uyarı bulunmadı.</td>
        </tr>
      `;

      const narrativeSections = buildPdfReportSectionsHtml({
        summary: report.summary ?? "",
        strengths: report.strengths ?? [],
        weaknesses: report.weaknesses ?? [],
        recommendations: report.recommendations ?? [],
        resourceRecommendations: report.resourceRecommendations ?? [],
        language,
      });

      tempDiv.innerHTML = `
        <div style="margin-bottom:10px;padding:10px 12px;border-radius:10px;background:${scoreBg};">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div style="flex:1;display:flex;flex-direction:column;gap:3px;color:#111827;min-width:0;padding-right:8px;">
              <div style="font-size:15px;font-weight:800;line-height:1.15;">${escapeHtml(studentName)} - ${escapeHtml(String(user?.student_no ?? "") || studentNo || "")}</div>
              <div style="font-size:11px;line-height:1.2;font-weight:500;"><span style="font-weight:800;">Bölüm:</span> ${escapeHtml(departmentName)}</div>
              <div style="font-size:11px;line-height:1.2;font-weight:500;"><span style="font-weight:800;">Ders:</span> ${escapeHtml(sidebarSubtitle || "-")}</div>
              <div style="font-size:11px;line-height:1.2;font-weight:500;"><span style="font-weight:800;">Ödev:</span> ${escapeHtml(headerTitle || "-")}</div>
              <div style="font-size:11px;line-height:1.2;font-weight:500;"><span style="font-weight:800;">Tarih:</span> ${escapeHtml(dateStr)}</div>
            </div>
            <div style="min-width:190px;text-align:right;display:flex;flex-direction:column;align-items:flex-end;gap:5px;justify-content:flex-start;padding-top:1px;">
              <div style="font-size:12px;font-weight:700;color:#111827;line-height:1.1;">${escapeHtml(report.fileName)}</div>
              <div style="font-size:18px;font-weight:900;line-height:1;color:${scoreColor};">Puan: ${scorePct}%</div>
            </div>
          </div>
        </div>

        <div style="margin-bottom:8px;">
          <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">Değerlendirme Kriterleri</h2>
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;align-items:stretch;">
            ${rubricCards}
          </div>
        </div>

        <div style="margin-bottom:8px;">
          <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">Ajan Özetleri</h2>
          <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;align-items:stretch;">
            ${agentCards}
          </div>
        </div>

        ${testCaseCards ? `
          <div style="margin-bottom:8px;">
            <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">Test Case Sonuclari</h2>
            <div style="display:grid;gap:6px;">
              ${testCaseCards}
            </div>
          </div>
        ` : ""}

        ${narrativeSections}

        <div>
          <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">Satır Bazlı İyileştirme Önerileri</h2>
          <table style="width:100%;border-collapse:separate;border-spacing:0;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;font-size:11px;">
            <thead>
              <tr style="background:#e5e7eb;">
                <th style="padding:7px 8px;text-align:center;width:70px;color:#111827;font-weight:700;border-bottom:1px solid #d1d5db;">Satır</th>
                <th style="padding:7px 8px;text-align:left;color:#111827;font-weight:700;border-bottom:1px solid #d1d5db;">İyileştirme Önerisi</th>
              </tr>
            </thead>
            <tbody>
              ${suggestionTableBody}
            </tbody>
          </table>
        </div>
      `;
      document.body.appendChild(tempDiv);
      const canvas = await html2canvas(tempDiv, { scale: 2, backgroundColor: "#ffffff", logging: false });
      document.body.removeChild(tempDiv);

      const imgData = canvas.toDataURL("image/png");
      const pdf = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });
      const pageWidth = pdf.internal.pageSize.getWidth();
      const pageHeight = pdf.internal.pageSize.getHeight();
      const margin = 10;
      const contentWidth = pageWidth - margin * 2;
      const imgHeight = (canvas.height * contentWidth) / canvas.width;

      let yOffset = 0;
      while (yOffset < imgHeight) {
        if (yOffset > 0) pdf.addPage();
        pdf.addImage(imgData, "PNG", margin, margin - yOffset, contentWidth, imgHeight);
        yOffset += pageHeight - margin * 2;
      }
      pdf.save(`${report.fileName.replace(/\.[^.]+$/, "")}-analiz-raporu.pdf`);
    } catch (err) {
      console.error("PDF export failed:", err);
    } finally {
      setExporting(false);
    }
  }, [findings, headerTitle, language, report, sidebarSubtitle, sidebarTitle, studentNo]);

  const activeFileData = files.find((f) => f.name === activeFile);
  const hasFiles = files.length > 0;
  const hasScoredUploadForCurrentAssignment = uploadRecords.some((record) => typeof record.score === "number" && !record.hasError);
  const hasEvaluationForCurrentAssignment = Boolean(currentEvaluation?.assignment_id && currentEvaluation.assignment_id === assignmentId);
  const evaluationButtonVisible = hasScoredUploadForCurrentAssignment || hasEvaluationForCurrentAssignment;
  const description = splitAssignmentDescription(assignmentDescription);
  const statusText = !hasFiles
    ? t("workspace.uploadFirst")
    : `${files.length} ${language === "tr" ? "dosya yüklendi" : "files uploaded"}${
        report?.reportStatus === "preparing"
          ? " — " + t("workspace.reportPreparing")
          : isRunning
            ? " — " + t("workspace.running")
            : report
              ? " — " + t("workspace.analysisComplete")
              : ""
      }`;
  const evaluationButtonLabel = currentEvaluation?.status === "submitted"
    ? (language === "tr" ? "Değerlendirildi" : "Rated")
    : (language === "tr" ? "Değerlendir" : "Rate");
  const evaluationContextLabel = useMemo(() => {
    const fileName = currentEvaluation?.uploaded_file_name || report?.fileName || headerTitle;
    if (!fileName) return "";
    if (!currentEvaluation?.uploaded_at) return fileName;

    const uploadedAt = new Date(currentEvaluation.uploaded_at);
    const formattedAt = new Intl.DateTimeFormat(language === "tr" ? "tr-TR" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(uploadedAt);

    return `${fileName} • ${formattedAt}`;
  }, [currentEvaluation?.uploaded_at, currentEvaluation?.uploaded_file_name, headerTitle, language, report?.fileName]);

  return (
    <div className="grid grid-cols-[260px_1fr] h-screen bg-background overflow-hidden">
      {/* Sidebar */}
      <aside className="flex flex-col h-full bg-sidebar overflow-hidden">
        <div className="p-5 pb-4">
          <div className="flex items-center gap-2 mb-1">
            <div className="h-6 w-6 rounded-md bg-primary flex items-center justify-center">
              <span className="text-xs font-bold text-primary-foreground">{studentInitial}</span>
            </div>
            <h1 className="text-sm font-bold text-foreground tracking-tight">{sidebarTitle}</h1>
          </div>
          <p className="text-xs text-muted-foreground mt-1">{sidebarSubtitle}</p>
        </div>

        <nav className="flex-1 px-3 space-y-0.5 overflow-auto">
          <div className="px-2 py-2">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">{t("workspace.projectFiles")}</span>
          </div>

          {files.length === 0 ? (
            <div className="px-2 py-6 text-center">
              <FolderOpen className="h-5 w-5 text-muted-foreground/40 mx-auto mb-2" />
              <p className="text-xs text-muted-foreground/60">{t("workspace.noFiles")}</p>
            </div>
          ) : (
            files.map((file) => (
              <div
                key={file.name}
                className={`group flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm transition-colors duration-150 ease-smooth ${
                  activeFile === file.name
                    ? "bg-card shadow-card text-foreground font-medium"
                    : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
                }`}
              >
                <button
                  onClick={() => setActiveFile(file.name)}
                  className="flex items-center gap-2 flex-1 min-w-0"
                >
                  <FileCode className="h-4 w-4 text-primary shrink-0" />
                  <span className="truncate">{file.name}</span>
                </button>
                <button
                  onClick={(e) => { e.stopPropagation(); handleRemoveFile(file.name); }}
                  disabled={isPastDue}
                  className={`rounded-md p-0.5 transition-all duration-150 ${
                    isPastDue
                      ? "opacity-50 cursor-not-allowed text-muted-foreground/40"
                      : "opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                  }`}
                  title={isPastDue ? "Teslim tarihi geçtiği için dosya kaldırılamaz" : t("workspace.removeFile")}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </nav>

        <div className="p-3 border-t border-border/50">
          <button
            onClick={async () => {
              await logout();
              window.location.href = "/login";
            }}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors duration-150"
          >
            <LogOut className="h-4 w-4" />
            <span>{t("common.logout")}</span>
          </button>
        </div>
      </aside>

      <main className="flex min-w-0 flex-col h-screen overflow-hidden">
        <header className="flex items-start justify-between gap-4 px-6 py-3 border-b border-border bg-card shrink-0">
          <div className="flex min-w-0 items-start gap-4">
            <button
              onClick={onBack}
              className={cn(
                "flex shrink-0 items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors",
                description.body || description.expectedOutput ? "mt-28" : "mt-1"
              )}
            >
              <ArrowLeft className="h-4 w-4" /> {t("workspace.backToAssignments")}
            </button>
            <div className="min-w-0">
              <div className="flex items-center gap-2 relative">
                <h1 className="text-lg font-bold tracking-tight text-foreground">{headerTitle}</h1>
                <button
                  onMouseEnter={handleBadgeMouseEnter}
                  onMouseLeave={handleBadgeMouseLeave}
                  className="p-1 text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded transition-colors"
                  title={t("assignments.showTasks")}
                >
                  <BookOpen className="h-4 w-4" />
                </button>
                {hoveredAssignmentId === assignmentId && (
                  <div
                    className="absolute top-full left-0 mt-2 w-64 bg-card border border-border rounded-lg shadow-lg z-40 overflow-hidden animate-in fade-in slide-in-from-top-2 duration-200"
                    onMouseEnter={handleBadgeMouseEnter}
                    onMouseLeave={handleBadgeMouseLeave}
                  >
                    <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border">
                      <span className="text-xs font-semibold text-muted-foreground">{t("assignments.tasks").toUpperCase()}</span>
                      <button
                        onClick={(e) => {
                          e.preventDefault();
                          setHoveredAssignmentId(null);
                        }}
                        className="text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <X className="h-3 w-3" />
                      </button>
                    </div>
                    <div className="max-h-80 overflow-y-auto">
                      {loadingQuestions[assignmentId] ? (
                        <div className="p-3 text-xs text-muted-foreground text-center">{t("assignments.tasksLoading")}</div>
                      ) : (assignmentQuestions[assignmentId] || []).length === 0 ? (
                        <div className="p-3 text-xs text-muted-foreground text-center">{t("assignments.noTasks")}</div>
                      ) : (
                        <div className="divide-y divide-border">
                          {(assignmentQuestions[assignmentId] || []).map((q) => (
                            <div
                              key={q.id}
                              className={cn(
                                "px-3 py-2 text-xs border-l-4 border-l-border",
                                q.color === "blue"
                                  ? "bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400"
                                  : q.color === "green"
                                    ? "bg-green-50 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                                    : q.color === "pink"
                                      ? "bg-pink-50 text-pink-700 dark:bg-pink-900/20 dark:text-pink-400"
                                      : "bg-yellow-50 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-400"
                              )}
                            >
                              {q.content}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <p className="text-xs text-muted-foreground">{statusText}</p>
              <p className="hidden">
                  {!hasFiles
                   ? t("workspace.uploadFirst")
                   : `${files.length} ${language === "tr" ? "dosya yüklendi" : "files uploaded"}${isRunning ? " — " + t("workspace.running") : report ? " — " + t("workspace.analysisComplete") : ""}`}
              </p>
              {(description.body || description.expectedOutput) && (
                <div className="mt-2 max-w-[770px] space-y-2">
                  {description.body && (
                    <p className="text-xs leading-relaxed text-muted-foreground">{description.body}</p>
                  )}
                  {description.expectedOutput && (
                    <div className="rounded-lg border border-primary/15 bg-primary/5 px-3 py-2">
                      <p className="text-[11px] font-semibold text-primary">Örnek çıktı</p>
                      <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-foreground">{description.expectedOutput}</pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          <div
            className={cn(
              "flex shrink-0 items-center gap-2",
              description.body || description.expectedOutput ? "pt-32" : "pt-0"
            )}
          >
              <RuntimeHealthBadge compact className="hidden md:inline-flex" />
              {evaluationButtonVisible && (
                <button
                  type="button"
                  onClick={() => {
                    if (currentEvaluation?.status === "submitted") {
                      toast.success(language === "tr" ? "Bu rapor değerlendirildi." : "This report has already been rated.");
                      return;
                    }
                    setEvaluationOpen(true);
                  }}
                  className={cn(
                    "relative flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-md transition-all hover:brightness-110",
                    currentEvaluation?.status === "submitted"
                      ? "cursor-default border border-border bg-muted/50 text-muted-foreground shadow-none hover:brightness-100"
                      : "bg-gradient-to-r from-yellow-400 to-amber-500"
                  )}
                >
                  {currentEvaluation?.status === "submitted" ? (
                    <CheckCircle2 className="h-4 w-4" />
                  ) : (
                    <Star className="h-4 w-4 fill-white" />
                  )}
                  {evaluationButtonLabel}
                  {currentEvaluation?.status !== "submitted" && (
                    <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-destructive ring-2 ring-background animate-pulse" />
                  )}
                </button>
              )}
            {isRunning ? (
              <button
                onClick={() => {
                  analysisAbortRef.current?.abort();
                  analysisInFlightRef.current = false;
                  setIsRunning(false);
                  addLog("System", language === "tr" ? "Analiz iptal edildi." : "Analysis cancelled.", "info");
                  setAgentStatuses(Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus])));
                  setAgentActions({});
                }}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive text-destructive-foreground text-sm font-medium transition-all active:scale-95"
              >
                <StopCircle className="h-4 w-4" /> {language === "tr" ? "Durdur" : "Stop"}
              </button>
            ) : isPastDue ? (
              <button
                disabled
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/15 text-destructive text-sm font-medium cursor-not-allowed"
              >
                <StopCircle className="h-4 w-4" /> {language === "tr" ? "Teslim tarihi geçmiştir" : "Past due"}
              </button>
            ) : (
              <motion.button
                whileTap={{ scale: hasFiles ? 0.95 : 1 }}
                onClick={handleRunAgentsClick}
                disabled={!hasFiles}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium shadow-button-primary transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100"
              >
                <Play className="h-4 w-4" /> {t("workspace.runAgents")}
              </motion.button>
            )}
          </div>
        </header>

        <div className="grid flex-1 grid-cols-[minmax(0,1fr)_360px] overflow-hidden">
          {!hasFiles ? (
            <div className="flex flex-col p-6 lg:p-8 pt-6 overflow-auto border-r border-border">
              <div className="w-full max-w-2xl">
                <FileUploadZone
                  onFilesUploaded={handleFilesUploaded}
                  uploadedFiles={files}
                  onRemoveFile={handleRemoveFile}
                  disableRemove={isPastDue}
                />
              </div>
            </div>
          ) : (
            <div className="flex min-w-0 flex-col overflow-hidden border-r border-border">
              <div className="flex-1 min-h-0 overflow-hidden">
                {activeFileData ? (
                  <CodeEditor
                    fileName={activeFileData.name}
                    content={activeFileData.content}
                    annotations={findings}
                    highlightedLine={highlightedLine}
                  />
                ) : (
                  <div className="flex items-center justify-center h-full text-muted-foreground/50 text-sm">
                    {language === "tr" ? "Bir dosya seçin" : "Select a file"}
                  </div>
                )}
              </div>

              <div className="h-[min(34vh,300px)] min-h-[240px] shrink-0 border-t border-border overflow-hidden">
                <div className="grid h-full min-h-0 grid-cols-1 gap-0 xl:grid-cols-[minmax(0,1fr)_320px]">
                  <LogPanel logs={logs} />
                  <div className="min-h-0 overflow-auto border-l border-border space-y-0">
                    <UploadHistory records={uploadRecords} />
                    {report && (
                      <div className="border-t border-border">
                        <ExecutionStats
                          executionTimeMs={report.executionTimeMs}
                          memoryUsageMb={report.memoryUsageMb}
                          peakMemoryMb={report.peakMemoryMb}
                        />
                      </div>
                    )}
                  </div>
                </div>
              </div>

            </div>
          )}

          <RightPanel
            agents={agentDefs}
            agentStatuses={agentStatuses}
            agentActions={agentActions}
            findings={findings}
            report={report}
            isRunning={isRunning}
            exporting={exporting}
            onExportPdf={handleExportPdf}
            onFindingClick={handleFindingClick}
          />
        </div>
        <EvaluationModal
          open={evaluationOpen}
          blocking={currentEvaluation?.status === "pending"}
          language={language}
          contextLabel={evaluationContextLabel}
          onClose={() => {
            if (currentEvaluation?.status !== "pending") {
              setEvaluationOpen(false);
            }
          }}
          onSubmit={handleEvaluationSubmit}
        />
      </main>
    </div>
  );
};

export default WorkspacePage;
