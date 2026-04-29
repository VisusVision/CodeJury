import { useState, useCallback, useRef, useEffect } from "react";
import { Play, StopCircle, ArrowLeft, LogOut } from "lucide-react";
import { motion } from "framer-motion";
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
} from "lucide-react";
import FileUploadZone from "@/components/dashboard/FileUploadZone";
import { type AgentStatus } from "@/components/dashboard/AgentCard";
import LogPanel, { type LogEntry } from "@/components/dashboard/LogPanel";
import CodeEditor, { type CodeAnnotation } from "@/components/dashboard/CodeEditor";
import { type ReportData } from "@/components/dashboard/AnalysisReport";
import { analyzeCode, createUploadHistoryRecord, getUploadHistoryRecords, type ApiAnalysisResult } from "@/services/api";
import UploadHistory, { type UploadRecord } from "@/components/dashboard/UploadHistory";
import ExecutionStats from "@/components/dashboard/ExecutionStats";
import RightPanel from "@/components/dashboard/RightPanel";

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

const agentDefs: AgentDef[] = [
  { id: "testing", name: "Test Ajanı", description: "Derleme, birim test ve çalışma zamanı çıktılarını inceler.", icon: FlaskConical },
  { id: "quality", name: "Kod Kalitesi Ajanı", description: "Algoritma, veri yapıları ve Big-O karmaşıklığını değerlendirir.", icon: Code2 },
  { id: "seniority", name: "Kıdem Ajanı", description: "Kodun olgunluk seviyesini ve modern dil kullanımını analiz eder.", icon: GraduationCap },
  { id: "guideline", name: "Standartlar Ajanı", description: "Temiz kod prensipleri ve stil kılavuzlarına uyumu denetler.", icon: BookCheck },
  { id: "security", name: "Güvenlik Ajanı", description: "SQL injection, kod enjeksiyonu, tehlikeli import ve sandbox ihlallerini tespit eder.", icon: ShieldAlert },
  { id: "evidence", name: "Kanıtlandırma Ajanı", description: "Bulguları satır numaralarıyla eşleştirerek somutlaştırır.", icon: Search },
  { id: "orchestrator", name: "Rubrik Ajanı", description: "Tüm bulguları toplar ve rubriğe göre nihai notu oluşturur.", icon: Brain },
];

// Map agent IDs to their icons for restoring from sessionStorage
const agentIconMap: Record<string, typeof FlaskConical> = {
  testing: FlaskConical,
  quality: Code2,
  seniority: GraduationCap,
  guideline: BookCheck,
  security: ShieldAlert,
  evidence: Search,
  orchestrator: Brain,
};

interface WorkspacePageProps {
  sidebarTitle: string;
  sidebarSubtitle: string;
  headerTitle: string;
  assignmentId: string;
  studentNo: string;
  assignmentDueDate?: string | null;
  onBack: () => void;
}

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

const WorkspacePage = ({ sidebarTitle, sidebarSubtitle, headerTitle, assignmentId, studentNo, assignmentDueDate, onBack }: WorkspacePageProps) => {
  const persisted = useRef(loadPersistedState(assignmentId, studentNo));
  const studentInitial = (sidebarTitle?.trim().charAt(0) || "A").toUpperCase();
  const isPastDue = Boolean(assignmentDueDate && new Date(assignmentDueDate) < new Date());

  const [files, setFiles] = useState<UploadedFile[]>(persisted.current?.files || []);
  const [activeFile, setActiveFile] = useState<string | null>(persisted.current?.activeFile || null);
  const [agentStatuses, setAgentStatuses] = useState<Record<string, AgentStatus>>(
    Object.fromEntries(agentDefs.map((a) => [a.id, (persisted.current?.hasEverRun ? "done" : "idle") as AgentStatus]))
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

  useEffect(() => {
    const loadUploadHistory = async () => {
      try {
        const rawStudent = sessionStorage.getItem("student");
        if (!rawStudent) return;
        const student = JSON.parse(rawStudent) as { student_no: string };
        const rows = await getUploadHistoryRecords(student.student_no, assignmentId);
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
  }, [assignmentId]);

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
  }, [activeFile, hasEverRun, isPastDue]);

  const addLog = useCallback((agent: string, message: string, type: LogEntry["type"] = "info") => {
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
    setLogs((prev) => [...prev, { id: `${Date.now()}-${Math.random()}`, timestamp: ts, agent, message, type }]);
  }, []);

  const runAnalysis = useCallback(async () => {
    if (isPastDue) {
      addLog("Sistem", "Teslim tarihi geçtiği için analiz başlatılamaz.", "error");
      return;
    }
    if (files.length === 0) return;
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

    addLog("Sistem", `${files.length} dosya analiz için hazırlanıyor...`, "info");

    // Set all agents to thinking
    agentDefs.forEach((a) => {
      setAgentStatuses((p) => ({ ...p, [a.id]: "thinking" }));
    });
    addLog("Sistem", "Ajanlar başlatılıyor...", "info");

    try {
      // Call the FastAPI backend
      const result: ApiAnalysisResult = await analyzeCode(firstFile.name, firstFile.content, assignmentId);

      // Update agent statuses from the result
      result.agents.forEach((agent) => {
        setAgentStatuses((p) => ({ ...p, [agent.id]: "done" }));
        const pct = Math.round((agent.score / agent.maxScore) * 100);
        setAgentActions((p) => ({ ...p, [agent.id]: `${agent.summary} (${pct}%)` }));
        addLog(agent.name, agent.summary, "success");
      });

      // Set orchestrator as done
      const totalPct = Math.round((result.totalScore / result.maxScore) * 100);
      setAgentStatuses((p) => ({ ...p, orchestrator: "done" }));
      setAgentActions((p) => ({ ...p, orchestrator: `Nihai puan: ${result.totalScore}/${result.maxScore}` }));
      addLog("Rubrik Ajanı", `Nihai puan: ${result.totalScore}/${result.maxScore} (${totalPct}%) — Rapor hazır.`, "success");

      // Map API agent icons
      const agentIconForReport = result.agents.map((a) => ({
        ...a,
        icon: agentIconMap[a.id] || FlaskConical,
      }));

      // Build report
      const reportData: ReportData = {
        totalScore: result.totalScore,
        maxScore: result.maxScore,
        rubric: result.rubric,
        agents: agentIconForReport,
        evidence: result.evidence,
        fileName: result.fileName,
        fileContent: firstFile.content,
        executionTimeMs: result.executionTimeMs,
        memoryUsageMb: result.memoryUsageMb,
        peakMemoryMb: result.peakMemoryMb,
      };
      setReport(reportData);

      // Build code annotations from evidence
      const codeAnnotations: CodeAnnotation[] = result.evidence.map((e) => ({
        line: e.line,
        severity: e.severity,
        message: e.message,
        agent: e.agent,
      }));
      setFindings(codeAnnotations);

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
        const rawStudent = sessionStorage.getItem("student");
        if (rawStudent) {
          const student = JSON.parse(rawStudent) as {
            first_name: string;
            last_name: string;
            student_no: string;
          };
          await createUploadHistoryRecord({
            student_first_name: student.first_name,
            student_last_name: student.last_name,
            student_no: student.student_no,
            uploaded_file_name: firstFile.name,
            assignment_id: assignmentId,
            score: totalPct,
            has_error: false,
          });
        }
      } catch (error) {
        console.error("Yükleme geçmişi kaydedilemedi:", error);
      }

    } catch (err: any) {
      const errorMsg = err?.message || "Bilinmeyen hata";
      addLog("Sistem", `Analiz hatası: ${errorMsg}`, "error");
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
        const rawStudent = sessionStorage.getItem("student");
        if (rawStudent) {
          const student = JSON.parse(rawStudent) as {
            first_name: string;
            last_name: string;
            student_no: string;
          };
          await createUploadHistoryRecord({
            student_first_name: student.first_name,
            student_last_name: student.last_name,
            student_no: student.student_no,
            uploaded_file_name: firstFile.name,
            assignment_id: assignmentId,
            has_error: true,
          });
        }
      } catch (error) {
        console.error("Yükleme geçmişi kaydedilemedi:", error);
      }
    } finally {
      setIsRunning(false);
    }
  }, [files, addLog, assignmentId, isPastDue]);

  const handleFindingClick = useCallback((line: number) => {
    setHighlightedLine(line);
  }, []);

  const handleExportPdf = useCallback(async () => {
    if (!report) return;
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
          .replace(/\"/g, "&quot;")
          .replace(/'/g, "&#39;");

      const now = new Date();
      const dateStr = now.toLocaleString("tr-TR", {
        day: "2-digit",
        month: "long",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });

      const rawStudent = sessionStorage.getItem("student");
      const student = rawStudent
        ? (JSON.parse(rawStudent) as {
            first_name?: string;
            last_name?: string;
            student_no?: string;
            department_name?: string | null;
          })
        : null;

      const studentName = `${student?.first_name || ""} ${student?.last_name || ""}`.trim() || sidebarTitle || "-";
      const departmentName = student?.department_name?.trim() || "-";
      const scorePct = Math.round((report.totalScore / report.maxScore) * 100);
      const scoreColor = scorePct >= 80 ? "#059669" : scorePct >= 60 ? "#d97706" : "#dc2626";
      const scoreBg = "#f9fafb";

      const rubricCards = report.rubric
        .map((category) => {
          const pct = Math.round((category.score / category.maxScore) * 100);
          return `
            <div style="padding:8px 10px;border:1px solid #d1d5db;border-radius:8px;background:#ffffff;font-size:11px;display:flex;justify-content:space-between;gap:8px;align-items:center;min-height:38px;">
              <span style="font-weight:600;color:#111827;line-height:1.2;">${escapeHtml(category.name)}</span>
              <span style="font-weight:700;color:#111827;white-space:nowrap;">${pct}/100</span>
            </div>
          `;
        })
        .join("");

      const agentCards = report.agents
        .map((agent) => {
          const pct = Math.round((agent.score / agent.maxScore) * 100);
          return `
            <div style="padding:8px 10px;border:1px solid #e5e7eb;border-radius:8px;background:#f9fafb;font-size:11px;min-height:58px;">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:4px;">
                <span style="font-weight:700;color:#111827;line-height:1.2;">${escapeHtml(agent.name)}</span>
                <span style="font-weight:700;color:#111827;white-space:nowrap;">${pct}%</span>
              </div>
              <div style="color:#4b5563;line-height:1.3;">${escapeHtml(agent.summary)}</div>
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

      tempDiv.innerHTML = `
        <div style="margin-bottom:10px;padding:10px 12px;border-radius:10px;background:${scoreBg};">
          <div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">
            <div style="flex:1;display:flex;flex-direction:column;gap:3px;color:#111827;min-width:0;padding-right:8px;">
              <div style="font-size:15px;font-weight:800;line-height:1.15;">${escapeHtml(studentName)} - ${escapeHtml(student?.student_no || studentNo || "")}</div>
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
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
            ${rubricCards}
          </div>
        </div>

        <div style="margin-bottom:8px;">
          <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">Ajan Özetleri</h2>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
            ${agentCards}
          </div>
        </div>

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
  }, [findings, headerTitle, report, sidebarSubtitle, sidebarTitle, studentNo]);

  const activeFileData = files.find((f) => f.name === activeFile);
  const hasFiles = files.length > 0;

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
            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Proje Dosyaları</span>
          </div>

          {files.length === 0 ? (
            <div className="px-2 py-6 text-center">
              <FolderOpen className="h-5 w-5 text-muted-foreground/40 mx-auto mb-2" />
              <p className="text-xs text-muted-foreground/60">Henüz dosya yüklenmedi</p>
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
                  title={isPastDue ? "Teslim tarihi geçtiği için dosya kaldırılamaz" : "Dosyayı kaldır"}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            ))
          )}
        </nav>

        <div className="p-3 border-t border-border/50">
          <button
            onClick={() => {
              sessionStorage.removeItem("student");
              window.location.href = "/login";
            }}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors duration-150"
          >
            <LogOut className="h-4 w-4" />
            <span>Çıkış Yap</span>
          </button>
        </div>
      </aside>

      <main className="flex flex-col h-screen overflow-hidden">
        <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-card shrink-0">
          <div className="flex items-center gap-4">
            <button
              onClick={onBack}
              className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              <ArrowLeft className="h-4 w-4" /> Ödevlere Dön
            </button>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold tracking-tight text-foreground">{headerTitle}</h1>
              </div>
              <p className="text-xs text-muted-foreground">
                {!hasFiles
                  ? "Başlamak için kod dosyanızı yükleyin."
                  : `${files.length} dosya yüklendi${isRunning ? " — analiz devam ediyor..." : report ? " — analiz tamamlandı" : ""}`}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isRunning ? (
              <button
                onClick={() => setIsRunning(false)}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive text-destructive-foreground text-sm font-medium transition-all active:scale-95"
              >
                <StopCircle className="h-4 w-4" /> Durdur
              </button>
            ) : isPastDue ? (
              <button
                disabled
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive/15 text-destructive text-sm font-medium cursor-not-allowed"
              >
                <StopCircle className="h-4 w-4" /> Teslim tarihi geçmiştir
              </button>
            ) : (
              <motion.button
                whileTap={{ scale: hasFiles ? 0.95 : 1 }}
                onClick={runAnalysis}
                disabled={!hasFiles}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium shadow-button-primary transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100"
              >
                <Play className="h-4 w-4" /> Ajanları Çalıştır
              </motion.button>
            )}
          </div>
        </header>

        <div className="flex-1 grid grid-cols-[1fr_360px] overflow-hidden">
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
            <div className="flex flex-col overflow-hidden border-r border-border">
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
                    Bir dosya seçin
                  </div>
                )}
              </div>

              <div className="flex-1 min-h-[240px] shrink-0 border-t border-border overflow-auto">
                <div className="grid grid-cols-1 xl:grid-cols-[1fr_320px] gap-0 h-full">
                  <LogPanel logs={logs} />
                  <div className="border-l border-border space-y-0">
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

              <div className="shrink-0 border-t border-border">
                <FileUploadZone
                  onFilesUploaded={handleFilesUploaded}
                  uploadedFiles={[]}
                  onRemoveFile={handleRemoveFile}
                  compact
                  disableRemove={isPastDue}
                />
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
      </main>
    </div>
  );
};

export default WorkspacePage;
