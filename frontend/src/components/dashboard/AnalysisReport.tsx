import { motion } from "framer-motion";
import { useRef, useState, useCallback } from "react";
import html2canvas from "html2canvas-pro";
import jsPDF from "jspdf";
import {
  FlaskConical,
  Code2,
  GraduationCap,
  BookCheck,
  Search,
  Brain,
  ChevronDown,
  AlertTriangle,
  CheckCircle2,
  Info,
  XCircle,
  FileCode,
  Download,
  type LucideIcon,
} from "lucide-react";

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import ExecutionStats from "./ExecutionStats";
import {
  partitionEvidence,
  type EvidenceItem,
  type RejectedClaimItem,
} from "@/lib/evidenceDisplay";

/* ─── Types ─── */

interface RubricCategory {
  name: string;
  weight: number;
  score: number;
  maxScore: number;
}

interface Finding {
  severity: "error" | "warning" | "info" | "success";
  message: string;
  line?: number;
  code?: string;
}

export interface TestResult {
  name: string;
  input: string;
  expected: string;
  actual: string;
  passed: boolean;
  visibility?: "public" | "hidden";
  matchPct?: number;
  diffDetail?: string;
}

interface AgentReport {
  id: string;
  name: string;
  icon: LucideIcon;
  summary: string;
  score: number;
  maxScore: number;
  findings: Finding[];
  testResults?: TestResult[];
}

type LineEvidence = EvidenceItem;

export interface ResourceRecommendation {
  title: string;
  url: string;
  reason: string;
  resourceType: "docs" | "tutorial" | "video" | "practice";
  priority: "high" | "medium";
}

export interface TaskAlignment {
  factor: number;
  programmatic_factor?: number;
  llm_factor?: number | null;
  llm_off_topic: boolean;
  reasons: string[];
  capability_match?: number;
}

export interface ReportData {
  totalScore: number;
  maxScore: number;
  rubric: RubricCategory[];
  agents: AgentReport[];
  evidence: LineEvidence[];
  rejectedClaims?: RejectedClaimItem[];
  fileName: string;
  fileContent: string;
  executionTimeMs: number;
  memoryUsageMb: number;
  peakMemoryMb: number;
  summary?: string;
  strengths?: string[];
  weaknesses?: string[];
  recommendations?: string[];
  resourceRecommendations?: ResourceRecommendation[];
  /** Düşük not + zayıf görev uyumu uyarısı (API) */
  relevanceScoreWarning?: string | null;
  taskAlignment?: TaskAlignment;
  reportStatus?: "preparing" | "ready";
  agentDiagnostics?: import("@/services/api").ApiAgentDiagnostics;
}

/* ─── Mock report generator ─── */

export function generateMockReport(fileName: string, fileContent: string): ReportData {
  const lines = fileContent.split("\n");
  const lineCount = lines.length;

  const rubric: RubricCategory[] = [
    { name: "Doğruluk & Çalışabilirlik", weight: 25, score: 22, maxScore: 25 },
    { name: "Kod Kalitesi & Yapı", weight: 20, score: 16, maxScore: 20 },
    { name: "Kıdem Seviyesi", weight: 15, score: 11, maxScore: 15 },
    { name: "Standartlara Uyum", weight: 20, score: 17, maxScore: 20 },
    { name: "Test Edilebilirlik", weight: 10, score: 8, maxScore: 10 },
    { name: "Belgeleme", weight: 10, score: 8, maxScore: 10 },
  ];

  const totalScore = rubric.reduce((s, r) => s + r.score, 0);
  const maxScore = rubric.reduce((s, r) => s + r.maxScore, 0);

  const evidenceLines: LineEvidence[] = [];
  const addEvidence = (line: number, agent: string, message: string, severity: LineEvidence["severity"]) => {
    if (line > 0 && line <= lineCount) evidenceLines.push({ line, agent, message, severity });
  };

  // Generate realistic-looking evidence
  const sampleLine1 = Math.min(3, lineCount);
  const sampleLine2 = Math.min(8, lineCount);
  const sampleLine3 = Math.min(15, lineCount);
  const sampleLine4 = Math.min(22, lineCount);
  const sampleLine5 = Math.min(30, lineCount);
  const sampleLine6 = Math.min(12, lineCount);

  addEvidence(sampleLine1, "Kod Kalitesi", "Değişken adlandırma PEP 8 / camelCase kuralına uygun.", "success");
  addEvidence(sampleLine2, "Standartlar", "Fonksiyon uzunluğu 20 satırı aşıyor — parçalanması önerilir.", "warning");
  addEvidence(sampleLine3, "Kıdem", "List comprehension yerine döngü kullanılmış.", "info");
  addEvidence(sampleLine4, "Test Ajanı", "Bu satırdaki koşul dalı test kapsamı dışında.", "warning");
  addEvidence(sampleLine5, "Kod Kalitesi", "Magic number kullanımı tespit edildi — sabit tanımlayın.", "error");
  addEvidence(sampleLine6, "Standartlar", "Docstring formatı doğru ve eksiksiz.", "success");

  const agents: AgentReport[] = [
    {
      id: "testing",
      name: "Test Ajanı",
      icon: FlaskConical,
      summary: "Kod başarıyla derlendi ve çalıştırıldı. 3 test senaryosundan 3'ü geçti. Çalışma zamanı hatası tespit edilmedi.",
      score: 22,
      maxScore: 25,
      findings: [
        { severity: "success", message: "Derleme başarılı — hata yok.", line: 1 },
        { severity: "success", message: "Çalışma zamanı hatası tespit edilmedi." },
        { severity: "warning", message: "Koşullu dal test kapsamı dışında.", line: sampleLine4, code: lines[sampleLine4 - 1]?.trim() },
      ],
    },
    {
      id: "quality",
      name: "Kod Kalitesi Ajanı",
      icon: Code2,
      summary: "Genel yapı iyi; ancak bazı fonksiyonlar uzun ve magic number kullanımı tespit edildi.",
      score: 16,
      maxScore: 20,
      findings: [
        { severity: "success", message: "Değişken adlandırma kurallarına uygun.", line: sampleLine1 },
        { severity: "error", message: "Magic number kullanımı — sabit olarak tanımlayın.", line: sampleLine5, code: lines[sampleLine5 - 1]?.trim() },
        { severity: "warning", message: "Fonksiyon karmaşıklığı yüksek (cyclomatic complexity: 8).", line: sampleLine2 },
        { severity: "info", message: "Algoritma verimliliği O(n) — kabul edilebilir düzeyde." },
      ],
    },
    {
      id: "seniority",
      name: "Kıdem Ajanı",
      icon: GraduationCap,
      summary: "Kod orta-seviye (Mid-Level) olgunluğa sahip. Modern dil özellikleri kısmen kullanılmış.",
      score: 11,
      maxScore: 15,
      findings: [
        { severity: "info", message: "List comprehension yerine klasik döngü kullanılmış.", line: sampleLine3, code: lines[sampleLine3 - 1]?.trim() },
        { severity: "success", message: "Hata yönetimi (try-catch) doğru uygulanmış." },
        { severity: "warning", message: "Type hint / TypeScript tipi eksik — tip güvenliği artırılabilir." },
      ],
    },
    {
      id: "guideline",
      name: "Standartlar Ajanı",
      icon: BookCheck,
      summary: "Temiz kod prensiplerine büyük ölçüde uyuluyor. Belgeleme kalitesi iyi.",
      score: 17,
      maxScore: 20,
      findings: [
        { severity: "success", message: "Docstring formatı doğru ve eksiksiz.", line: sampleLine6, code: lines[sampleLine6 - 1]?.trim() },
        { severity: "warning", message: "Fonksiyon uzunluğu 20 satırı aşıyor — SRP ihlali.", line: sampleLine2 },
        { severity: "success", message: "İsimlendirme kuralları tutarlı." },
      ],
    },
    {
      id: "evidence",
      name: "Kanıtlandırma Ajanı",
      icon: Search,
      summary: `${evidenceLines.length} bulgu satır numaralarıyla eşleştirildi.`,
      score: 8,
      maxScore: 10,
      findings: evidenceLines.map((e) => ({
        severity: e.severity,
        message: `Satır ${e.line}: ${e.message}`,
        line: e.line,
      })),
    },
    {
      id: "orchestrator",
      name: "Rubrik Ajanı",
      icon: Brain,
      summary: `Nihai değerlendirme tamamlandı. Toplam puan: ${totalScore}/${maxScore}.`,
      score: totalScore,
      maxScore,
      findings: [
        { severity: "success", message: `Toplam puan: ${totalScore}/${maxScore} (${Math.round((totalScore / maxScore) * 100)}%)` },
        { severity: "info", message: `En güçlü alan: Doğruluk & Çalışabilirlik (${rubric[0].score}/${rubric[0].maxScore})` },
        { severity: "warning", message: `Geliştirilmesi gereken alan: Kıdem Seviyesi (${rubric[2].score}/${rubric[2].maxScore})` },
      ],
    },
  ];

  const executionTimeMs = Math.floor(Math.random() * 2500) + 300;
  const memoryUsageMb = Math.round((Math.random() * 80 + 20) * 10) / 10;
  const peakMemoryMb = Math.round((memoryUsageMb + Math.random() * 40) * 10) / 10;

  return {
    totalScore,
    maxScore,
    rubric,
    agents,
    evidence: evidenceLines,
    fileName,
    fileContent,
    executionTimeMs,
    memoryUsageMb,
    peakMemoryMb,
    summary: "Genel olarak odev beklentisini karsilayan bir cozum var; yine de bazi alanlarda gelistirme firsati bulunuyor.",
    strengths: ["Temel is akisinin ana hatlari kurulmus."],
    weaknesses: ["Bazi bolumlerde daha acik hata yonetimi ve test kapsami gerekli."],
    recommendations: ["Kenar durumlari icin ilave test ekleyin."],
    resourceRecommendations: [],
  };
}

/* ─── Sub-components ─── */

const severityIcon: Record<Finding["severity"], LucideIcon> = {
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
  success: CheckCircle2,
};

const severityColor: Record<Finding["severity"], string> = {
  error: "text-destructive",
  warning: "text-warning",
  info: "text-primary",
  success: "text-success",
};

const severityBg: Record<Finding["severity"], string> = {
  error: "bg-destructive/10",
  warning: "bg-warning/10",
  info: "bg-primary/10",
  success: "bg-success/10",
};

function ScoreRing({ score, max }: { score: number; max: number }) {
  const pct = Math.round((score / max) * 100);
  const r = 54;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;
  const color = pct >= 80 ? "hsl(var(--success))" : pct >= 60 ? "hsl(var(--warning))" : "hsl(var(--destructive))";

  return (
    <div className="relative w-32 h-32 shrink-0">
      <svg viewBox="0 0 120 120" className="w-full h-full -rotate-90">
        <circle cx="60" cy="60" r={r} fill="none" stroke="hsl(var(--border))" strokeWidth="8" />
        <motion.circle
          cx="60" cy="60" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
          strokeDasharray={circ} initial={{ strokeDashoffset: circ }} animate={{ strokeDashoffset: offset }}
          transition={{ duration: 1, ease: "easeOut" }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-bold text-foreground">{pct}</span>
        <span className="text-[10px] text-muted-foreground font-medium">/ 100</span>
      </div>
    </div>
  );
}

function RubricBar({ cat }: { cat: RubricCategory }) {
  const pct = Math.round((cat.score / cat.maxScore) * 100);
  const barColor = pct >= 80 ? "bg-success" : pct >= 60 ? "bg-warning" : "bg-destructive";

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-foreground font-medium">{cat.name}</span>
        <span className="text-muted-foreground tabular-nums">{cat.score}/{cat.maxScore} <span className="text-muted-foreground/50">(%{cat.weight})</span></span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <motion.div className={`h-full rounded-full ${barColor}`} initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.8, ease: "easeOut" }} />
      </div>
    </div>
  );
}

function FindingRow({ f }: { f: Finding }) {
  const Icon = severityIcon[f.severity];
  return (
    <div className={`flex items-start gap-2.5 rounded-lg px-3 py-2.5 ${severityBg[f.severity]}`}>
      <Icon className={`h-4 w-4 mt-0.5 shrink-0 ${severityColor[f.severity]}`} />
      <div className="min-w-0 flex-1">
        <p className="text-xs text-foreground leading-relaxed">{f.message}</p>
        {f.code && (
          <code className="block mt-1.5 text-[11px] font-mono-code text-muted-foreground bg-muted rounded px-2 py-1 truncate">{f.code}</code>
        )}
      </div>
      {f.line && <span className="text-[10px] text-muted-foreground font-mono-code shrink-0">:{f.line}</span>}
    </div>
  );
}

function outputText(value: string) {
  return value.trim() || "(cikti yok)";
}

function TestOutputBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">{label}</div>
      <pre className="max-h-32 overflow-auto rounded-md border border-border bg-background px-3 py-2 font-mono-code text-[11px] leading-relaxed text-foreground whitespace-pre-wrap break-words">
        {outputText(value)}
      </pre>
    </div>
  );
}

function TestResultCard({ test }: { test: TestResult }) {
  const Icon = test.passed ? CheckCircle2 : XCircle;
  const statusText = test.passed ? "Gecti" : "Basarisiz";
  return (
    <div className="rounded-lg border border-border bg-background p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={`h-4 w-4 ${test.passed ? "text-success" : "text-destructive"}`} />
        <span className="text-xs font-semibold text-foreground">{test.name}</span>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${test.passed ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"}`}>
          {statusText}
        </span>
        {test.visibility === "hidden" ? (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">Gizli test</span>
        ) : null}
        {typeof test.matchPct === "number" ? (
          <span className="ml-auto text-[10px] font-medium text-muted-foreground">%{Math.round(test.matchPct)} eslesme</span>
        ) : null}
      </div>
      <div className="mt-3 grid gap-2 lg:grid-cols-3">
        <TestOutputBlock label="Input" value={test.input} />
        <TestOutputBlock label="Beklenen Output" value={test.expected} />
        <TestOutputBlock label="Senin Output'un" value={test.actual} />
      </div>
      {test.diffDetail ? (
        <p className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-[11px] leading-relaxed text-destructive">{test.diffDetail}</p>
      ) : null}
    </div>
  );
}

function AgentSection({ agent }: { agent: AgentReport }) {
  const [open, setOpen] = useState(false);
  const Icon = agent.icon;
  const pct = Math.round((agent.score / agent.maxScore) * 100);

  return (
    <div className="rounded-xl bg-card shadow-card overflow-hidden">
      <button onClick={() => setOpen(!open)} className="w-full flex items-center gap-3 p-4 text-left hover:bg-muted/30 transition-colors">
        <div className="rounded-md bg-muted p-2 shrink-0"><Icon className="h-4 w-4 text-foreground" /></div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-foreground">{agent.name}</h3>
          <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1">{agent.summary}</p>
        </div>
        <span className="text-sm font-bold text-foreground tabular-nums shrink-0">{pct}%</span>
        <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 ${open ? "rotate-180" : ""}`} />
      </button>
      {open && (
        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} transition={{ duration: 0.2 }} className="border-t border-border px-4 pb-4 pt-3 space-y-2">
          {agent.testResults?.length ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-xs font-semibold text-foreground">
                <FlaskConical className="h-3.5 w-3.5" />
                Test Case Sonuclari
              </div>
              {agent.testResults.map((test, i) => <TestResultCard key={`${test.name}-${i}`} test={test} />)}
            </div>
          ) : null}
          {agent.findings.map((f, i) => <FindingRow key={i} f={f} />)}
        </motion.div>
      )}
    </div>
  );
}

/* ─── Code with annotations ─── */

function FileEvidencePanel({ items }: { items: LineEvidence[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-xl bg-card shadow-card p-4 mb-4 space-y-2">
      <h3 className="text-sm font-semibold text-foreground">Dosya Seviyesi Kanıtlar</h3>
      {items.map((item, index) => (
        <div key={`${item.agent}-${index}`} className="text-xs border border-border rounded-md p-2">
          <span className={`font-medium ${severityColor[item.severity]}`}>[{item.agent}]</span>
          <span className="text-muted-foreground ml-2">{item.message}</span>
        </div>
      ))}
    </div>
  );
}

function RejectedClaimsPanel({ items }: { items: RejectedClaimItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="rounded-xl bg-card shadow-card p-4 mt-4 space-y-2">
      <h3 className="text-sm font-semibold text-foreground">Reddedilen İddialar</h3>
      <p className="text-xs text-muted-foreground">
        Bu maddeler kodda somut kanıt bulunamadığı için öğrenci geri bildirimine dahil edilmedi.
      </p>
      {items.map((item, index) => (
        <div key={`${item.agentSource}-${index}`} className="text-xs border border-dashed border-border rounded-md p-2">
          <div className="font-medium text-foreground">[{item.agent}] {item.claim}</div>
          <div className="text-muted-foreground mt-1">↳ {item.reason}</div>
        </div>
      ))}
    </div>
  );
}

function AnnotatedCode({ fileContent, evidence }: { fileContent: string; evidence: LineEvidence[] }) {
  const lines = fileContent.split("\n");
  const evidenceMap = new Map<number, LineEvidence[]>();
  evidence.forEach((e) => {
    const arr = evidenceMap.get(e.line) || [];
    arr.push(e);
    evidenceMap.set(e.line, arr);
  });

  return (
    <div className="rounded-xl overflow-hidden shadow-card">
      <div className="flex items-center gap-2 px-4 py-2.5 bg-card border-b border-border">
        <FileCode className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium text-foreground">Satır Bazlı Kanıtlar</span>
      </div>
      <div className="terminal-bg p-4 max-h-[50vh] overflow-auto font-mono-code text-xs leading-relaxed">
        {lines.map((line, i) => {
          const lineNum = i + 1;
          const annotations = evidenceMap.get(lineNum);
          const hasAnnotation = !!annotations;
          const highlightBg = annotations
            ? annotations.some((a) => a.severity === "error")
              ? "bg-destructive/10"
              : annotations.some((a) => a.severity === "warning")
                ? "bg-warning/10"
                : "bg-primary/5"
            : "";

          return (
            <div key={i}>
              <div className={`flex ${highlightBg} ${hasAnnotation ? "rounded" : ""}`}>
                <span className="select-none text-muted-foreground/30 w-10 text-right pr-4 shrink-0 tabular-nums">{lineNum}</span>
                <span className="text-terminal-foreground whitespace-pre">{line || " "}</span>
              </div>
              {annotations?.map((a, j) => (
                <div key={j} className="flex pl-10 ml-4 border-l-2 border-primary/30 py-1">
                  <span className={`text-[11px] ${severityColor[a.severity]}`}>
                    ↳ [{a.agent}] {a.message}
                  </span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ─── Main Report ─── */

interface AnalysisReportProps {
  report: ReportData;
  onClose: () => void;
}

const AnalysisReport = ({ report, onClose }: AnalysisReportProps) => {
  const reportRef = useRef<HTMLDivElement>(null);
  const [exporting, setExporting] = useState(false);
  const { lineEvidence, fileEvidence } = partitionEvidence(report.evidence);
  const rejectedClaims = report.rejectedClaims ?? [];

  const handleExportPdf = useCallback(async () => {
    if (!reportRef.current) return;
    setExporting(true);
    try {
      // Temporarily expand all agent sections for PDF
      const el = reportRef.current;
      const canvas = await html2canvas(el, {
        scale: 2,
        useCORS: true,
        backgroundColor: "#ffffff",
        logging: false,
      });
      const imgData = canvas.toDataURL("image/png");
      const pdf = new jsPDF({
        orientation: "portrait",
        unit: "mm",
        format: "a4",
      });
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
  }, [report.fileName]);

  return (
    <motion.div initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.3 }} className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-foreground">Analiz Raporu</h2>
          <p className="text-sm text-muted-foreground mt-0.5">{report.fileName} — değerlendirme tamamlandı</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleExportPdf}
            disabled={exporting}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium shadow-button-primary hover:brightness-110 transition-all disabled:opacity-50"
          >
            <Download className="h-4 w-4" />
            {exporting ? "Dışa aktarılıyor..." : "PDF İndir"}
          </button>
          <button onClick={onClose} className="px-4 py-2 rounded-lg bg-secondary text-secondary-foreground text-sm font-medium hover:bg-muted transition-colors">
            Çalışma Alanına Dön
          </button>
        </div>
      </div>

      {/* Printable content */}
      <div ref={reportRef} className="space-y-6">
        {/* Execution Stats */}
        <ExecutionStats
          executionTimeMs={report.executionTimeMs}
          memoryUsageMb={report.memoryUsageMb}
          peakMemoryMb={report.peakMemoryMb}
        />

        {report.relevanceScoreWarning ? (
          <div
            className="rounded-xl border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-950 dark:text-amber-100 flex gap-3 items-start"
            role="status"
          >
            <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600 dark:text-amber-400 mt-0.5" />
            <p className="leading-relaxed">{report.relevanceScoreWarning}</p>
          </div>
        ) : null}

        {report.summary || (report.strengths?.length ?? 0) > 0 || (report.weaknesses?.length ?? 0) > 0 || (report.recommendations?.length ?? 0) > 0 ? (
          <div className="rounded-xl bg-card shadow-card p-6 space-y-4">
            {report.summary ? (
              <div>
                <h3 className="text-sm font-semibold text-foreground">Genel Değerlendirme</h3>
                <p className="text-sm text-muted-foreground mt-2 leading-relaxed">{report.summary}</p>
              </div>
            ) : null}
            {report.strengths?.length ? (
              <div>
                <h3 className="text-sm font-semibold text-foreground">Güçlü Yönler</h3>
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground list-disc pl-5">
                  {report.strengths.map((item) => <li key={`strength-${item}`}>{item}</li>)}
                </ul>
              </div>
            ) : null}
            {report.weaknesses?.length ? (
              <div>
                <h3 className="text-sm font-semibold text-foreground">Geliştirilmesi Gereken Yönler</h3>
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground list-disc pl-5">
                  {report.weaknesses.map((item) => <li key={`weakness-${item}`}>{item}</li>)}
                </ul>
              </div>
            ) : null}
            {report.recommendations?.length ? (
              <div>
                <h3 className="text-sm font-semibold text-foreground">Yapılacaklar / Öneriler</h3>
                <ul className="mt-2 space-y-1 text-sm text-muted-foreground list-disc pl-5">
                  {report.recommendations.map((item) => <li key={`recommendation-${item}`}>{item}</li>)}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}

        {report.resourceRecommendations?.length ? (
          <div className="rounded-xl bg-card shadow-card p-6">
            <h3 className="text-sm font-semibold text-foreground">Öğrenci İçin Kaynak Önerileri</h3>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              {report.resourceRecommendations.map((item) => (
                <a
                  key={item.url}
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  className="rounded-xl border border-primary/15 bg-primary/5 p-4 transition-colors hover:border-primary/35"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="text-sm font-semibold text-foreground">{item.title}</div>
                    <span className="rounded-full bg-background px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                      {item.priority}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-muted-foreground leading-relaxed">{item.reason}</p>
                  <p className="mt-3 break-all text-[11px] text-primary">{item.url}</p>
                </a>
              ))}
            </div>
          </div>
        ) : null}

        {/* Score overview */}
        <div className="rounded-xl bg-card shadow-card p-6">
          <div className="flex flex-col sm:flex-row items-center gap-6">
            <ScoreRing score={report.totalScore} max={report.maxScore} />
            <div className="flex-1 w-full space-y-3">
              {report.rubric.map((cat) => (
                <RubricBar key={cat.name} cat={cat} />
              ))}
            </div>
          </div>
        </div>

        {/* Tabs */}
        <Tabs defaultValue="agents" className="w-full">
          <TabsList className="w-full justify-start">
            <TabsTrigger value="agents">Ajan Geri Bildirimleri</TabsTrigger>
            <TabsTrigger value="evidence">Satır Bazlı Kanıtlar</TabsTrigger>
          </TabsList>

          <TabsContent value="agents" className="space-y-3 mt-4">
            {report.agents.map((agent) => (
              <AgentSection key={agent.id} agent={agent} />
            ))}
          </TabsContent>

          <TabsContent value="evidence" className="mt-4">
            <FileEvidencePanel items={fileEvidence} />
            <AnnotatedCode fileContent={report.fileContent} evidence={lineEvidence} />
            <RejectedClaimsPanel items={rejectedClaims} />
          </TabsContent>
        </Tabs>
      </div>
    </motion.div>
  );
};

export default AnalysisReport;
