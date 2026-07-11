import { CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

export interface FormalTestFixture {
  name: string;
  content: string;
}

export interface FormalOracleValidation {
  status: string;
  provider: string;
  model: string;
  schema_version?: string;
  verified_at?: string;
  reason?: string;
}

export interface FormalTestResult {
  name: string;
  input?: string;
  expected?: string;
  actual?: string;
  passed: boolean;
  visibility?: "public" | "hidden";
  status?: string;
  source?: string;
  matchPct?: number;
  diffDetail?: string;
  id?: string;
  actualStderr?: string;
  errorType?: string;
  errorMessageTr?: string;
  files?: FormalTestFixture[];
  oracleValidation?: FormalOracleValidation | null;
}

export interface FormalTestSummary {
  passed: number;
  failed: number;
  error: number;
  total: number;
}

export interface FormalTestProvenance {
  testSource?: string;
  testEvidenceStatus?: string;
  formalPassed?: number;
  formalTotal?: number;
  testSetId?: string;
  testSetHash?: string;
  cacheVersion?: number;
}

interface FormalTestResultsProps {
  audience: "student" | "teacher";
  testResults: FormalTestResult[];
  hiddenTestSummary?: FormalTestSummary | null;
  provenance?: FormalTestProvenance | null;
  compact?: boolean;
}

const outputText = (value?: string) => (value ?? "").trim() || "(cikti yok)";

const statusLabel = (status?: string, passed?: boolean) => {
  const normalized = String(status ?? "").trim().toLowerCase();
  if (normalized === "error") return "Hata";
  if (normalized === "pass" || normalized === "passed" || passed) return "Gecti";
  return "Basarisiz";
};

const statusTone = (status?: string, passed?: boolean) => {
  const normalized = String(status ?? "").trim().toLowerCase();
  if (normalized === "error") return "bg-amber-500/10 text-amber-700";
  if (normalized === "pass" || normalized === "passed" || passed) return "bg-success/10 text-success";
  return "bg-destructive/10 text-destructive";
};

function OutputBlock({ label, value, compact }: { label: string; value?: string; compact?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">{label}</div>
      <pre
        className={cn(
          "overflow-auto rounded-md border border-border bg-background font-mono-code leading-relaxed text-foreground whitespace-pre-wrap break-words",
          compact ? "max-h-24 px-2 py-1.5 text-[10px]" : "max-h-32 px-3 py-2 text-[11px]",
        )}
      >
        {outputText(value)}
      </pre>
    </div>
  );
}

function HiddenSummaryCard({ summary }: { summary: FormalTestSummary }) {
  return (
    <div className="rounded-lg border border-border bg-muted/30 px-3 py-2.5">
      <p className="text-xs font-semibold text-foreground">Gizli test ozeti</p>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {summary.total} gizli test • {summary.passed} gecti • {summary.failed} basarisiz • {summary.error} hata
      </p>
    </div>
  );
}

function ProvenancePanel({ provenance }: { provenance: FormalTestProvenance }) {
  const rows = [
    provenance.testSource ? ["Kaynak", provenance.testSource] : null,
    provenance.testEvidenceStatus ? ["Kanıt durumu", provenance.testEvidenceStatus] : null,
    typeof provenance.formalPassed === "number" && typeof provenance.formalTotal === "number"
      ? ["Formal skor", `${provenance.formalPassed}/${provenance.formalTotal}`]
      : null,
    provenance.testSetId ? ["Set ID", provenance.testSetId] : null,
    provenance.testSetHash ? ["Set hash", provenance.testSetHash] : null,
    typeof provenance.cacheVersion === "number" ? ["Cache surumu", `v${provenance.cacheVersion}`] : null,
  ].filter(Boolean) as [string, string][];

  if (!rows.length) return null;

  return (
    <div className="rounded-lg border border-primary/15 bg-primary/5 px-3 py-2.5">
      <p className="text-xs font-semibold text-foreground">Formal test kaniti</p>
      <div className="mt-2 grid gap-1.5">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-start justify-between gap-3 text-[11px]">
            <span className="text-muted-foreground">{label}</span>
            <span className="max-w-[65%] break-all text-right font-medium text-foreground">{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StudentHiddenCard({ test, compact }: { test: FormalTestResult; compact?: boolean }) {
  const Icon = test.status === "error" ? AlertTriangle : test.passed ? CheckCircle2 : XCircle;
  return (
    <div className={cn("rounded-lg border border-border bg-background", compact ? "px-3 py-2.5" : "p-3")}>
      <div className="flex flex-wrap items-center gap-2">
        <Icon
          className={cn(
            "h-4 w-4",
            test.status === "error" ? "text-amber-600" : test.passed ? "text-success" : "text-destructive",
          )}
        />
        <span className="text-xs font-semibold text-foreground">{test.name}</span>
        <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">Gizli test</span>
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", statusTone(test.status, test.passed))}>
          {statusLabel(test.status, test.passed)}
        </span>
      </div>
    </div>
  );
}

function PublicCaseCard({ test, compact }: { test: FormalTestResult; compact?: boolean }) {
  const Icon = test.passed ? CheckCircle2 : XCircle;
  return (
    <div className={cn("rounded-lg border border-border bg-background", compact ? "px-3 py-2.5" : "p-3")}>
      <div className="flex flex-wrap items-center gap-2">
        <Icon className={cn("h-4 w-4", test.passed ? "text-success" : "text-destructive")} />
        <span className="text-xs font-semibold text-foreground">{test.name}</span>
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", statusTone(test.status, test.passed))}>
          {statusLabel(test.status, test.passed)}
        </span>
        {typeof test.matchPct === "number" ? (
          <span className="ml-auto text-[10px] font-medium text-muted-foreground">%{Math.round(test.matchPct)} eslesme</span>
        ) : null}
      </div>
      <div className={cn("grid gap-2", compact ? "mt-2" : "mt-3 lg:grid-cols-3")}>
        <OutputBlock label="Input" value={test.input} compact={compact} />
        <OutputBlock label="Beklenen Output" value={test.expected} compact={compact} />
        <OutputBlock label="Senin Output'un" value={test.actual} compact={compact} />
      </div>
      {test.errorMessageTr ? (
        <p className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-[11px] leading-relaxed text-destructive">
          {test.errorMessageTr}
        </p>
      ) : null}
      {test.diffDetail ? (
        <p className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-[11px] leading-relaxed text-destructive">{test.diffDetail}</p>
      ) : null}
    </div>
  );
}

function TeacherCaseCard({ test, compact }: { test: FormalTestResult; compact?: boolean }) {
  const Icon = test.status === "error" ? AlertTriangle : test.passed ? CheckCircle2 : XCircle;
  const isHidden = test.visibility === "hidden";

  return (
    <div className={cn("rounded-lg border border-border bg-background", compact ? "px-3 py-2.5" : "p-3")}>
      <div className="flex flex-wrap items-center gap-2">
        <Icon
          className={cn(
            "h-4 w-4",
            test.status === "error" ? "text-amber-600" : test.passed ? "text-success" : "text-destructive",
          )}
        />
        <span className="text-xs font-semibold text-foreground">{test.name}</span>
        {isHidden ? (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">Gizli test</span>
        ) : null}
        <span className={cn("rounded-full px-2 py-0.5 text-[10px] font-semibold", statusTone(test.status, test.passed))}>
          {statusLabel(test.status, test.passed)}
        </span>
        {test.source ? (
          <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground">{test.source}</span>
        ) : null}
      </div>

      <div className={cn("grid gap-2", compact ? "mt-2" : "mt-3 lg:grid-cols-3")}>
        <OutputBlock label="Input" value={test.input} compact={compact} />
        <OutputBlock label="Beklenen Output" value={test.expected} compact={compact} />
        <OutputBlock label="Gercek Output" value={test.actual} compact={compact} />
      </div>

      {test.actualStderr ? (
        <div className="mt-2">
          <OutputBlock label="Stderr" value={test.actualStderr} compact={compact} />
        </div>
      ) : null}

      {test.errorType || test.errorMessageTr ? (
        <div className="mt-2 space-y-1 text-[11px]">
          {test.errorType ? <p className="text-foreground"><span className="font-semibold">Hata tipi:</span> {test.errorType}</p> : null}
          {test.errorMessageTr ? <p className="text-destructive">{test.errorMessageTr}</p> : null}
        </div>
      ) : null}

      {test.diffDetail ? (
        <p className="mt-2 rounded-md bg-destructive/10 px-3 py-2 text-[11px] leading-relaxed text-destructive">{test.diffDetail}</p>
      ) : null}

      {test.files?.length ? (
        <div className="mt-2 space-y-2">
          <p className="text-[10px] font-semibold uppercase text-muted-foreground">Fixture dosyalari</p>
          {test.files.map((file) => (
            <div key={file.name} className="rounded-md border border-border bg-muted/30 px-2.5 py-2">
              <p className="text-[11px] font-semibold text-foreground">{file.name}</p>
              <pre className="mt-1 max-h-24 overflow-auto whitespace-pre-wrap break-words font-mono-code text-[10px] text-muted-foreground">
                {file.content}
              </pre>
            </div>
          ))}
        </div>
      ) : null}

      {test.oracleValidation ? (
        <div className="mt-2 rounded-md border border-border bg-muted/20 px-2.5 py-2 text-[11px] text-muted-foreground">
          <p className="font-semibold text-foreground">Oracle</p>
          <p>{test.oracleValidation.provider} / {test.oracleValidation.model}</p>
          <p>{test.oracleValidation.status}</p>
        </div>
      ) : null}
    </div>
  );
}

const FormalTestResults = ({
  audience,
  testResults,
  hiddenTestSummary,
  provenance,
  compact = false,
}: FormalTestResultsProps) => {
  if (!testResults.length && !hiddenTestSummary && !provenance) {
    return null;
  }

  return (
    <div className="space-y-2">
      {audience === "teacher" && provenance ? <ProvenancePanel provenance={provenance} /> : null}
      {audience === "student" && hiddenTestSummary?.total ? <HiddenSummaryCard summary={hiddenTestSummary} /> : null}

      {testResults.map((test, index) => {
        const key = `${test.name}-${index}`;
        if (audience === "student" && test.visibility === "hidden") {
          return <StudentHiddenCard key={key} test={test} compact={compact} />;
        }
        if (audience === "teacher") {
          return <TeacherCaseCard key={key} test={test} compact={compact} />;
        }
        return <PublicCaseCard key={key} test={test} compact={compact} />;
      })}
    </div>
  );
};

export default FormalTestResults;
