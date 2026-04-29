import { useState, useCallback, useRef } from "react";
import { Play, StopCircle } from "lucide-react";
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
} from "lucide-react";
import ProjectSidebar from "@/components/dashboard/ProjectSidebar";
import FileUploadZone from "@/components/dashboard/FileUploadZone";
import { type AgentStatus } from "@/components/dashboard/AgentCard";
import LogPanel, { type LogEntry } from "@/components/dashboard/LogPanel";
import CodeEditor, { type CodeAnnotation } from "@/components/dashboard/CodeEditor";
import { type ReportData, generateMockReport } from "@/components/dashboard/AnalysisReport";
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
  { id: "evidence", name: "Kanıtlandırma Ajanı", description: "Bulguları satır numaralarıyla eşleştirerek somutlaştırır.", icon: Search },
  { id: "orchestrator", name: "Rubrik Ajanı", description: "Tüm bulguları toplar ve rubriğe göre nihai notu oluşturur.", icon: Brain },
];

const Index = () => {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);
  const [agentStatuses, setAgentStatuses] = useState<Record<string, AgentStatus>>(
    Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus]))
  );
  const [agentActions, setAgentActions] = useState<Record<string, string>>({});
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [report, setReport] = useState<ReportData | null>(null);
  const [uploadRecords, setUploadRecords] = useState<UploadRecord[]>([]);
  const [findings, setFindings] = useState<CodeAnnotation[]>([]);
  const [highlightedLine, setHighlightedLine] = useState<number | null>(null);
  const [exporting, setExporting] = useState(false);
  const [hasEverRun, setHasEverRun] = useState(false);
  const reportRef = useRef<HTMLDivElement>(null);

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
    setFiles((prev) => {
      const remaining = prev.filter((f) => f.name !== name);
      if (remaining.length === 0 && hasEverRun) {
        // All files removed after at least one run: reset UI but keep upload history
        setLogs([]);
        setAgentStatuses(Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus])));
        setAgentActions({});
        setReport(null);
        setFindings([]);
        setHighlightedLine(null);
        setIsRunning(false);
      }
      return remaining;
    });
    if (activeFile === name) setActiveFile(null);
  }, [activeFile, hasEverRun]);

  const addLog = useCallback((agent: string, message: string, type: LogEntry["type"] = "info") => {
    const now = new Date();
    const ts = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
    setLogs((prev) => [...prev, { id: `${Date.now()}-${Math.random()}`, timestamp: ts, agent, message, type }]);
  }, []);

  const simulateRun = useCallback(async () => {
    if (files.length === 0) return;
    setHasEverRun(true);
    setIsRunning(true);
    setLogs([]);
    setFindings([]);
    setHighlightedLine(null);
    setReport(null);
    setAgentStatuses(Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus])));
    setAgentActions({});

    // Always add new upload records for current files
    const newRecords = files.map((file) => ({
      id: `${Date.now()}-${Math.random()}`,
      fileName: file.name,
      timestamp: new Date(),
      hasError: Math.random() < 0.2,
    }));
    setUploadRecords((prev) => [...prev, ...newRecords]);

    addLog("Sistem", `${files.length} dosya analiz için hazırlanıyor...`, "info");

    const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

    const staticAgents = ["quality", "seniority", "guideline"];
    for (const id of staticAgents) {
      setAgentStatuses((p) => ({ ...p, [id]: "thinking" }));
      addLog(agentDefs.find((a) => a.id === id)!.name, "Statik analiz başlatıldı...", "info");
    }
    await wait(1500);
    for (const id of staticAgents) {
      setAgentStatuses((p) => ({ ...p, [id]: "acting" }));
      setAgentActions((p) => ({ ...p, [id]: "Kod yapısı taranıyor..." }));
      addLog(agentDefs.find((a) => a.id === id)!.name, "Kod yapısı taranıyor...", "info");
    }
    await wait(2000);

    setAgentStatuses((p) => ({ ...p, testing: "thinking" }));
    addLog("Test Ajanı", "Sandbox ortamı hazırlanıyor...", "info");
    await wait(1000);
    setAgentStatuses((p) => ({ ...p, testing: "acting" }));
    setAgentActions((p) => ({ ...p, testing: "Kod derleniyor ve çalıştırılıyor..." }));
    addLog("Test Ajanı", "Kod derleniyor ve çalıştırılıyor...", "info");
    await wait(1500);

    for (const id of staticAgents) {
      setAgentStatuses((p) => ({ ...p, [id]: "done" }));
      setAgentActions((p) => ({ ...p, [id]: "Analiz tamamlandı ✓" }));
      addLog(agentDefs.find((a) => a.id === id)!.name, "Analiz tamamlandı.", "success");
    }
    await wait(500);

    setAgentStatuses((p) => ({ ...p, testing: "done" }));
    setAgentActions((p) => ({ ...p, testing: "Tüm testler geçti ✓" }));
    addLog("Test Ajanı", "Tüm testler başarıyla geçti.", "success");
    await wait(500);

    setAgentStatuses((p) => ({ ...p, evidence: "thinking" }));
    addLog("Kanıtlandırma Ajanı", "Bulgular satır numaralarıyla eşleştiriliyor...", "info");
    await wait(1500);
    setAgentStatuses((p) => ({ ...p, evidence: "done" }));
    setAgentActions((p) => ({ ...p, evidence: "12 bulgu eşleştirildi ✓" }));
    addLog("Kanıtlandırma Ajanı", "12 bulgu başarıyla eşleştirildi.", "success");
    await wait(500);

    setAgentStatuses((p) => ({ ...p, orchestrator: "thinking" }));
    addLog("Rubrik Ajanı", "Nihai değerlendirme hesaplanıyor...", "info");
    await wait(1500);
    setAgentStatuses((p) => ({ ...p, orchestrator: "done" }));
    setAgentActions((p) => ({ ...p, orchestrator: "Nihai puan: 82/100" }));
    addLog("Rubrik Ajanı", "Nihai puan: 82/100 — Rapor hazır.", "success");

    // Generate report & findings
    const firstFile = files[0];
    if (firstFile) {
      const mockReport = generateMockReport(firstFile.name, firstFile.content);
      setReport(mockReport);

      // Build findings from report evidence
      const codeAnnotations: CodeAnnotation[] = mockReport.evidence.map((e) => ({
        line: e.line,
        severity: e.severity,
        message: e.message,
        agent: e.agent,
      }));
      setFindings(codeAnnotations);

      const scorePct = Math.round((mockReport.totalScore / mockReport.maxScore) * 100);
      setUploadRecords((prev) => {
        const updated = [...prev];
        let lastIdx = -1;
        for (let i = updated.length - 1; i >= 0; i--) {
          if (updated[i].fileName === firstFile.name) { lastIdx = i; break; }
        }
        if (lastIdx >= 0) updated[lastIdx] = { ...updated[lastIdx], score: scorePct };
        return updated;
      });
    }

    setIsRunning(false);
  }, [files, addLog]);

  const handleReset = useCallback(() => {
    if (!hasEverRun) return;
    setIsRunning(false);
    setLogs([]);
    setAgentStatuses(Object.fromEntries(agentDefs.map((a) => [a.id, "idle" as AgentStatus])));
    setAgentActions({});
    setReport(null);
    setFindings([]);
    setHighlightedLine(null);
    // uploadRecords are intentionally kept
  }, [hasEverRun]);

  const handleFindingClick = useCallback((line: number) => {
    setHighlightedLine(line);
  }, []);

  const handleExportPdf = useCallback(async () => {
    if (!report) return;
    setExporting(true);
    try {
      // Create a temporary element for PDF rendering
      const tempDiv = document.createElement("div");
      tempDiv.style.position = "absolute";
      tempDiv.style.left = "-9999px";
      tempDiv.style.width = "800px";
      tempDiv.style.padding = "32px";
      tempDiv.style.background = "#ffffff";
      tempDiv.innerHTML = `
        <h1 style="font-size:24px;font-weight:bold;margin-bottom:8px">Analiz Raporu</h1>
        <p style="color:#666;margin-bottom:24px">${report.fileName} — Puan: ${Math.round((report.totalScore / report.maxScore) * 100)}%</p>
        <div style="margin-bottom:16px">
          ${report.rubric.map(c => `<div style="margin-bottom:8px"><strong>${c.name}:</strong> ${c.score}/${c.maxScore}</div>`).join("")}
        </div>
        <div>
          ${report.agents.map(a => `<div style="margin-bottom:12px;padding:12px;background:#f5f5f5;border-radius:8px"><strong>${a.name}</strong> (${Math.round((a.score / a.maxScore) * 100)}%)<br/><span style="color:#666">${a.summary}</span></div>`).join("")}
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
  }, [report]);

  const activeFileData = files.find((f) => f.name === activeFile);
  const hasFiles = files.length > 0;

  return (
    <div className="grid grid-cols-[260px_1fr] min-h-screen bg-background">
      <ProjectSidebar
        files={files}
        activeFile={activeFile}
        onSelectFile={setActiveFile}
        onRemoveFile={handleRemoveFile}
      />

      {!hasFiles ? (
        /* No files: centered upload + empty right panel */
        <main className="flex-1 grid grid-cols-[1fr_360px] overflow-hidden">
          <div className="flex flex-col p-6 lg:p-8 pt-8">
            <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Agent Workspace</h1>
            <p className="text-sm text-muted-foreground mb-6">Başlamak için kod dosyanızı yükleyin.</p>
            <div className="w-full max-w-lg">
              <FileUploadZone onFilesUploaded={handleFilesUploaded} uploadedFiles={files} onRemoveFile={handleRemoveFile} />
            </div>
          </div>
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
        </main>
      ) : (
        /* Files loaded: 3-panel layout */
        <main className="flex flex-col h-screen overflow-hidden">
          {/* Top bar */}
          <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-card shrink-0">
            <div>
              <h1 className="text-lg font-bold tracking-tight text-foreground">Agent Workspace</h1>
              <p className="text-xs text-muted-foreground">
                {files.length} dosya yüklendi{isRunning ? " — analiz devam ediyor..." : report ? " — analiz tamamlandı" : ""}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {isRunning ? (
                <button
                  onClick={() => setIsRunning(false)}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-destructive text-destructive-foreground text-sm font-medium transition-all active:scale-95"
                >
                  <StopCircle className="h-4 w-4" /> Durdur
                </button>
              ) : (
                (
                  <motion.button
                    whileTap={{ scale: 0.95 }}
                    onClick={simulateRun}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium shadow-button-primary hover:brightness-110 transition-all"
                  >
                    <Play className="h-4 w-4" /> Ajanları Çalıştır
                  </motion.button>
                )
              )}
            </div>
          </header>

          {/* Content area: editor + right panel */}
          <div className="flex-1 grid grid-cols-[1fr_360px] overflow-hidden">
            {/* Left: Code editor + bottom panels */}
            <div className="flex flex-col overflow-hidden border-r border-border">
              {/* Code editor — takes less space, bottom panels get more */}
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

              {/* Bottom panels: Log + Upload History + Stats — bigger */}
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

              {/* Compact file upload strip at bottom */}
              <div className="shrink-0 border-t border-border">
                <FileUploadZone onFilesUploaded={handleFilesUploaded} uploadedFiles={[]} onRemoveFile={handleRemoveFile} compact />
              </div>
            </div>

            {/* Right panel: 3 tabs */}
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
      )}
    </div>
  );
};

export default Index;
