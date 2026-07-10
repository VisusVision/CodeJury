/** Gelistirmede bos string = ayni origin (/api -> Vite proxy -> FastAPI). Uzak cihazdan UI acilinca gerekli. */
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "" : "http://127.0.0.1:8001");

const parseApiErrorMessage = async (response: Response, fallback: string) => {
  const rawText = await response.text();
  const normalizedText = rawText.trim();

  if (!normalizedText) {
    return `${fallback} (${response.status})`;
  }

  try {
    const parsed = JSON.parse(normalizedText) as { detail?: unknown; message?: unknown; error?: unknown };
    const detail = parsed.detail ?? parsed.message ?? parsed.error;
    if (typeof detail === "string" && detail.trim()) {
      return detail.trim();
    }
  } catch {
    // Non-JSON error bodies fall through to the raw text below.
  }

  return normalizedText;
};

export interface ApiFinding {
  severity: "error" | "warning" | "info" | "success";
  message: string;
  line?: number | null;
  agent?: string | null;
  code?: string | null;
}

export interface ApiTestResult {
  name: string;
  input: string;
  expected: string;
  actual: string;
  passed: boolean;
  visibility?: "public" | "hidden";
  matchPct?: number;
  diffDetail?: string;
}

export interface ApiAgentReport {
  id: string;
  name: string;
  summary: string;
  score: number;
  maxScore: number;
  findings: ApiFinding[];
  testResults?: ApiTestResult[];
}

export interface ApiRubricCategory {
  name: string;
  weight: number;
  score: number;
  maxScore: number;
}

export interface ApiLineEvidence {
  line: number;
  agent: string;
  message: string;
  severity: "error" | "warning" | "info" | "success";
  scope?: "file";
}

export interface ApiRejectedClaim {
  agent: string;
  agentSource: string;
  claim: string;
  reason: string;
}

export interface ApiResourceRecommendation {
  title: string;
  url: string;
  reason: string;
  resourceType: "docs" | "tutorial" | "video" | "practice";
  priority: "high" | "medium";
}

export interface ApiTaskAlignment {
  factor: number;
  programmatic_factor?: number;
  llm_factor?: number | null;
  llm_off_topic: boolean;
  reasons: string[];
  capability_match?: number;
}

export interface ApiAgentDiagnosticRow {
  id: string;
  score?: number | null;
  llm_status: string;
  confidence?: number | null;
  guardrail_flags: string[];
}

export interface ApiAgentDiagnostics {
  agents: ApiAgentDiagnosticRow[];
  taskAlignment?: Record<string, unknown>;
  runtime?: {
    llm?: {
      enabled?: boolean;
      provider?: string;
      general_model?: string;
      coder_model?: string;
      base_url?: string;
    };
    sandbox?: {
      mode?: string;
      pool_ready?: boolean;
      execution_backend?: string;
      container_count?: number;
      available_count?: number;
    };
    pipeline_ms?: number;
  };
  lastLlmCall?: Record<string, unknown>;
}

export interface ApiAnalysisResult {
  totalScore: number;
  maxScore: number;
  rubric: ApiRubricCategory[];
  agents: ApiAgentReport[];
  evidence: ApiLineEvidence[];
  rejectedClaims?: ApiRejectedClaim[];
  fileName: string;
  executionTimeMs: number;
  memoryUsageMb: number;
  peakMemoryMb: number;
  /** Backend rubrik duzeltmeleri; sessionStorage surumu ile eslestirmek icin */
  analysisEngine?: string;
  summary?: string;
  strengths?: string[];
  weaknesses?: string[];
  recommendations?: string[];
  resourceRecommendations?: ApiResourceRecommendation[];
  /** Dusuk not + zayif gorev uyumu (backend kosullu) */
  relevanceScoreWarning?: string | null;
  taskAlignment?: ApiTaskAlignment;
  reportStatus?: "preparing" | "ready";
  agentDiagnostics?: ApiAgentDiagnostics;
}

interface AnalysisJobAccepted {
  job_id: string;
  status: "queued" | "running";
}

interface AnalysisJobStatus {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  updated_at?: string;
  report_status?: "preparing" | "ready";
  result?: ApiAnalysisResult;
  error?: string;
}

interface AnalysisJobProgressMeta {
  status: AnalysisJobStatus["status"];
  reportStatus: "preparing" | "ready";
}

export interface Student {
  id: string;
  student_no: string;
  tc_no: string;
  first_name: string;
  last_name: string;
  department_id?: string | null;
  department_name?: string | null;
  created_at?: string;

  class_year?: number | null;
}

export interface StudentImportSkippedRow {
  student_no: string;
  tc_no: string;
  first_name: string;
  last_name: string;
  department_name: string;
  reason: string;

  class_year?: number | null;
}

export interface StudentImportResponse {
  created: Student[];
  skipped: StudentImportSkippedRow[];
}

export interface Course {
  id: string;
  name: string;
  code: string;
  department_id?: string | null;
  created_at?: string;

  class_year?: number | null;
}

export interface Assignment {
  id: string;
  course_id: string;
  name: string;
  description: string | null;
  due_date?: string | null;
  created_at?: string;
}

export interface AssignmentTestCase {
  id?: string;
  assignment_id?: string;
  name: string;
  stdin: string;
  expected_stdout: string;
  expected_exit_code?: number;
  visibility: "public" | "hidden";
  source: "manual" | "ai";
  display_order?: number;
}

export interface Teacher {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  created_at?: string;
}

export interface Department {
  id: string;
  name: string;
  created_by?: string | null;
  created_at?: string;
}

export interface QuestionItem {
  id: string;
  content: string;
  color: "blue" | "green" | "pink" | "yellow";
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface RubricCriterion {
  name: string;
  description: string;
  max_score: number;
}

export interface Rubric {
  id: string;
  assignment_id: string;
  criteria: RubricCriterion[];
  status: "draft" | "approved";
  created_by?: string | null;
  created_at?: string;
  updated_at?: string;
}

function normalizeRubricCriteria(raw: unknown): RubricCriterion[] {
  let parsed: unknown = raw;

  if (typeof raw === "string") {
    try {
      parsed = JSON.parse(raw);
    } catch {
      return [];
    }
  }

  if (!Array.isArray(parsed)) {
    return [];
  }

  return parsed.map((item) => {
    const record = (item ?? {}) as Record<string, unknown>;
    return {
      name: String(record.name ?? ""),
      description: String(record.description ?? ""),
      max_score: Number(record.max_score ?? 0) || 0,
    };
  });
}

function normalizeRubric(raw: unknown): Rubric {
  const record = (raw ?? {}) as Record<string, unknown>;
  return {
    id: String(record.id ?? ""),
    assignment_id: String(record.assignment_id ?? ""),
    criteria: normalizeRubricCriteria(record.criteria),
    status: (record.status === "approved" ? "approved" : "draft") as "draft" | "approved",
    created_by: record.created_by ? String(record.created_by) : null,
    created_at: record.created_at ? String(record.created_at) : undefined,
    updated_at: record.updated_at ? String(record.updated_at) : undefined,
  };
}

const networkHint =
  "`npm run dev` hem Vite hem API'yi baslatir; yalnizca arayuz icin `npm run dev:vite`. " +
  "Hata suruyorsa `npm run dev` ile API'yi baslatin (varsayilan port 8001) veya DEV_API_PORT ile uyumlu Vite proxy kullanin.";

function apiErrorMessage(errorText: string, fallback: string): string {
  try {
    const parsed = JSON.parse(errorText) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    if (detail && typeof detail === "object") {
      const record = detail as Record<string, unknown>;
      if (typeof record.message === "string" && record.message.trim()) {
        return record.message;
      }
      if (Array.isArray(record.issues)) {
        const messages = record.issues
          .map((item) => (item && typeof item === "object" ? (item as Record<string, unknown>).message : null))
          .filter((message): message is string => typeof message === "string" && Boolean(message.trim()));
        if (messages.length) {
          return messages.join(" ");
        }
      }
    }
  } catch {
    // Fall through to the raw text below.
  }
  return errorText || fallback;
}

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

const ANALYSIS_POLL_INTERVAL_MS = 1500;
const ANALYSIS_POLL_MAX_ATTEMPTS = 200;
const LLM_FETCH_TIMEOUT_MS = 120_000;
const RUBRIC_FETCH_TIMEOUT_MS = 180_000;

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`İstek zaman aşımına uğradı (${Math.round(timeoutMs / 1000)} sn).`);
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

function isAnalysisJobAccepted(value: unknown): value is AnalysisJobAccepted {
  const record = (value ?? {}) as Record<string, unknown>;
  return typeof record.job_id === "string" && (record.status === "queued" || record.status === "running");
}

async function pollAnalysisJob(
  jobId: string,
  signal?: AbortSignal,
  onProgress?: (result: ApiAnalysisResult, meta: AnalysisJobProgressMeta) => void,
): Promise<ApiAnalysisResult> {
  let lastProgressToken = "";
  for (let attempt = 0; attempt < ANALYSIS_POLL_MAX_ATTEMPTS; attempt += 1) {
    if (signal?.aborted) {
      throw new DOMException("Analiz iptal edildi.", "AbortError");
    }
    if (attempt > 0) {
      await sleep(ANALYSIS_POLL_INTERVAL_MS);
    }
    const response = await fetch(`${API_BASE_URL}/api/analyze/jobs/${encodeURIComponent(jobId)}`, {
      cache: "no-store",
      signal,
    });
    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(apiErrorMessage(errorText, `Analiz durumu alinamadi (${response.status})`));
    }
    const job = (await response.json()) as AnalysisJobStatus;
    if (job.result && onProgress) {
      const progressToken = `${job.status}:${job.report_status || job.result.reportStatus || "preparing"}:${job.updated_at || attempt}`;
      if (progressToken !== lastProgressToken) {
        lastProgressToken = progressToken;
        onProgress(
          {
            ...job.result,
            reportStatus: job.result.reportStatus || job.report_status || (job.status === "completed" ? "ready" : "preparing"),
          },
          {
            status: job.status,
            reportStatus: job.report_status || job.result.reportStatus || (job.status === "completed" ? "ready" : "preparing"),
          },
        );
      }
    }
    if (job.status === "completed") {
      if (!job.result) {
        throw new Error("Analiz tamamlandi ancak sonuc alinamadi.");
      }
      return {
        ...job.result,
        reportStatus: job.result.reportStatus || job.report_status || "ready",
      };
    }
    if (job.status === "failed") {
      throw new Error(job.error || "Analiz tamamlanamadi. Lutfen tekrar deneyin.");
    }
  }
  throw new Error("Analiz zaman asimina ugradi. Lutfen tekrar deneyin.");
}

export async function analyzeCode(
  fileName: string,
  fileContent: string,
  assignmentId?: string,
  reportLanguage?: string,
  studentNo?: string,
  signal?: AbortSignal,
  onProgress?: (result: ApiAnalysisResult, meta: AnalysisJobProgressMeta) => void,
): Promise<ApiAnalysisResult> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_name: fileName,
        file_content: fileContent,
        assignment_id: assignmentId,
        student_no: studentNo,
        report_language: reportLanguage || "tr",
      }),
      signal,
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg === "Failed to fetch" || msg.includes("NetworkError") || msg.includes("Load failed")) {
      throw new Error(`${msg}. ${networkHint}`);
    }
    throw e;
  }

  if (!response.ok) {
    const errorText = await response.text();
    const statusCode = response.status;
    const msg = apiErrorMessage(errorText, `Server Error (${statusCode})`);
    throw new Error(msg);
  }

  const payload = await response.json();
  if (isAnalysisJobAccepted(payload)) {
    return pollAnalysisJob(payload.job_id, signal, onProgress);
  }
  return payload as ApiAnalysisResult;
}

export interface ApiHealthResponse {
  status: "ok" | "degraded" | string;
  analysis_ready?: boolean;
  worker_count?: number;
  ready_worker_count?: number;
  version?: string;
  analysis_engine?: string;
  demo_mode?: boolean;
  llm?: {
    enabled?: boolean;
    general_model?: string;
    coder_model?: string;
    provider?: string;
    base_url?: string;
  };
  sandbox?: {
    mode?: "pool" | "unavailable" | string;
    state?: string;
    pool_ready?: boolean;
    container_count?: number;
    available_count?: number;
    target_size?: number;
  };
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    return response.ok;
  } catch {
    return false;
  }
}

export async function fetchHealth(): Promise<ApiHealthResponse | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    if (!response.ok) return null;
    return (await response.json()) as ApiHealthResponse;
  } catch {
    return null;
  }
}

export async function loginStudent(studentNo: string, password: string): Promise<Student | null> {
  const response = await fetch(`${API_BASE_URL}/api/student/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ student_no: studentNo, password }),
  });

  if (response.status === 401 || response.status === 404) return null;

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Öğrenci giriş hatası (${response.status}): ${errorText}`);
  }

  return response.json();
}

export async function getStudents(): Promise<Student[]> {
  const response = await fetch(`${API_BASE_URL}/api/students`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Öğrenci listesi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function createStudent(payload: {
  student_no: string;
  tc_no: string;
  first_name: string;
  last_name: string;
  department_id: string;
  class_year?: number | null;
}): Promise<Student> {
  const response = await fetch(`${API_BASE_URL}/api/students`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Öğrenci ekleme hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function updateStudent(studentId: string, payload: {
  student_no: string;
  tc_no: string;
  first_name: string;
  last_name: string;
  class_year?: number | null;
  department_id: string;
}): Promise<Student> {
  const response = await fetch(`${API_BASE_URL}/api/students/${studentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Öğrenci güncelleme hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function deleteStudent(studentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/students/${studentId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Öğrenci silme hatası (${response.status}): ${errorText}`);
  }
}

export async function importStudentsCsv(file: File): Promise<StudentImportResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE_URL}/api/students/import-csv`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`CSV öğrenci yükleme hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getStudentCourses(studentId: string): Promise<Course[]> {
  const response = await fetch(`${API_BASE_URL}/api/student/${studentId}/courses`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders listesi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getCourse(courseId: string): Promise<Course> {
  const response = await fetch(`${API_BASE_URL}/api/courses/${courseId}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders detayı hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getCourseAssignments(courseId: string): Promise<Assignment[]> {
  const response = await fetch(`${API_BASE_URL}/api/courses/${courseId}/assignments`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ödev listesi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getAssignment(assignmentId: string): Promise<Assignment> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ödev detayı hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function createUploadHistoryRecord(payload: {
  student_first_name: string;
  student_last_name: string;
  student_no: string;
  uploaded_file_name: string;
  assignment_id?: string | null;
  score?: number;
  has_error?: boolean;
}): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/upload-history`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Yükleme geçmişi kaydı hatası (${response.status}): ${errorText}`);
  }
}

export interface UploadHistoryApiRecord {
  id: string;
  uploaded_file_name: string;
  uploaded_at: string;
  has_error: boolean;
  score?: number | null;
  assignment_id?: string | null;
}

export async function getUploadHistoryRecords(studentNo: string, assignmentId?: string): Promise<UploadHistoryApiRecord[]> {
  const url = new URL(`${API_BASE_URL || window.location.origin}/api/upload-history`, window.location.origin);
  url.searchParams.set("student_no", studentNo);
  if (assignmentId) {
    url.searchParams.set("assignment_id", assignmentId);
  }

  const response = await fetch(url.toString());
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Yükleme geçmişi listeleme hatası (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data as UploadHistoryApiRecord[] : [];
}

export interface EvaluationRecord {
  id: string;
  student_first_name: string;
  student_last_name: string;
  student_no: string;
  assignment_id: string;
  uploaded_file_name: string;
  score?: number | null;
  usefulness?: number | null;
  accuracy?: number | null;
  clarity?: number | null;
  comment?: string;
  status: "pending" | "submitted";
  created_at: string;
  submitted_at?: string | null;
  uploaded_at?: string | null;
}

export async function getCurrentEvaluation(studentNo: string, assignmentId?: string): Promise<EvaluationRecord | null> {
  const url = new URL(`${API_BASE_URL || window.location.origin}/api/evaluations/current`, window.location.origin);
  url.searchParams.set("student_no", studentNo);
  if (assignmentId) {
    url.searchParams.set("assignment_id", assignmentId);
  }
  const response = await fetch(url.toString());
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Değerlendirme durumu hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getEvaluations(): Promise<EvaluationRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/evaluations`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Değerlendirme listesi hatası (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data as EvaluationRecord[] : [];
}

export async function submitEvaluation(payload: {
  student_no: string;
  assignment_id: string;
  usefulness: number;
  accuracy: number;
  clarity: number;
  comment: string;
}): Promise<EvaluationRecord> {
  const response = await fetch(`${API_BASE_URL}/api/evaluations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Değerlendirme gönderimi hatası (${response.status}): ${errorText}`);
  }

  return response.json();
}

export async function registerTeacher(payload: {
  first_name: string;
  last_name: string;
  email: string;
  password: string;
}): Promise<Teacher> {
  const response = await fetch(`${API_BASE_URL}/api/teacher/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Öğretmen kaydı hatası (${response.status}): ${errorText}`);
  }

  return response.json();
}

export async function loginTeacher(email: string, password: string): Promise<Teacher> {
  const response = await fetch(`${API_BASE_URL}/api/teacher/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Öğretmen girişi hatası (${response.status}): ${errorText}`);
  }

  return response.json();
}

export async function getDepartments(): Promise<Department[]> {
  const response = await fetch(`${API_BASE_URL}/api/departments`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Bölüm listesi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function createDepartment(payload: { name: string; created_by?: string | null }): Promise<Department> {
  const response = await fetch(`${API_BASE_URL}/api/departments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Bölüm ekleme hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function deleteDepartment(departmentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/departments/${departmentId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Bölüm silme hatası (${response.status}): ${errorText}`);
  }
}

export async function getCourses(): Promise<Course[]> {
  const response = await fetch(`${API_BASE_URL}/api/courses`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders listesi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function createCourse(payload: { name: string; code: string; department_id?: string | null; class_year?: number | null }): Promise<Course> {
  const response = await fetch(`${API_BASE_URL}/api/courses`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders ekleme hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function deleteCourse(courseId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/courses/${courseId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders silme hatası (${response.status}): ${errorText}`);
  }
}

export async function getAssignments(): Promise<Assignment[]> {
  const response = await fetch(`${API_BASE_URL}/api/assignments`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ödev listesi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function createAssignment(payload: {
  course_id: string;
  name: string;
  description?: string | null;
  due_date?: string | null;
}): Promise<Assignment> {
  const response = await fetch(`${API_BASE_URL}/api/assignments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ödev ekleme hatası (${response.status}): ${apiErrorMessage(errorText, "Ödev eklenemedi")}`);
  }
  return response.json();
}

export async function deleteAssignment(assignmentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ödev silme hatası (${response.status}): ${errorText}`);
  }
}

export async function getAssignmentTestCases(assignmentId: string): Promise<AssignmentTestCase[]> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}/test-cases`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Test listesi hatasi (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data as AssignmentTestCase[] : [];
}

export async function replaceAssignmentTestCases(
  assignmentId: string,
  testCases: AssignmentTestCase[],
): Promise<AssignmentTestCase[]> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}/test-cases`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ test_cases: testCases }),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Test kaydetme hatasi (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data as AssignmentTestCase[] : [];
}

export async function suggestAssignmentTestCases(assignmentId: string): Promise<AssignmentTestCase[]> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}/test-cases/suggest`, {
    method: "POST",
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Test onerisi hatasi (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data?.suggestions) ? data.suggestions as AssignmentTestCase[] : [];
}

export async function getRubrics(): Promise<Rubric[]> {
  const response = await fetch(`${API_BASE_URL}/api/rubrics`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik listesi hatası (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data.map(normalizeRubric) : [];
}

export async function getRubricByAssignment(assignmentId: string): Promise<Rubric | null> {
  const response = await fetch(`${API_BASE_URL}/api/rubrics/by-assignment/${assignmentId}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik detayı hatası (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  if (!data) return null;
  return normalizeRubric(data);
}

export async function upsertRubric(payload: {
  assignment_id: string;
  criteria: RubricCriterion[];
  status: "draft" | "approved";
  created_by?: string | null;
}): Promise<Rubric> {
  const response = await fetch(`${API_BASE_URL}/api/rubrics/upsert`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik kaydetme hatası (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return normalizeRubric(data);
}

export async function updateRubricStatusByAssignment(assignmentId: string, status: "draft" | "approved"): Promise<Rubric> {
  const response = await fetch(`${API_BASE_URL}/api/rubrics/by-assignment/${assignmentId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik durum güncelleme hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function suggestRubric(payload: {
  assignment_title: string;
  assignment_description: string;
  criterion_count?: number;
  report_language?: string;
}): Promise<{ criteria: RubricCriterion[] }> {
  const response = await fetchWithTimeout(
    `${API_BASE_URL}/api/rubric/suggest`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    RUBRIC_FETCH_TIMEOUT_MS,
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik AI önerisi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export interface AssignmentSuggestion {
  id: string;
  title: string;
  summary: string;
  description: string;
}

export type AssignmentDifficulty = "easy" | "medium" | "hard";

export async function fetchAssignmentSuggestions(
  courseHint?: string,
  count?: number,
  difficulty?: AssignmentDifficulty | null,
  preferFresh?: boolean,
  reportLanguage?: string,
): Promise<{ suggestions: AssignmentSuggestion[] }> {
  const response = await fetchWithTimeout(
    `${API_BASE_URL}/api/faculty/assignment-assistant/suggestions`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        course_hint: courseHint ?? "",
        count: count ?? 5,
        difficulty: difficulty ?? "medium",
        prefer_fresh: Boolean(preferFresh),
        report_language: reportLanguage || "tr",
      }),
    },
    LLM_FETCH_TIMEOUT_MS,
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Ödev önerileri hatası (${response.status}): ${apiErrorMessage(errorText, "Ödev önerileri alınamadı")}`,
    );
  }
  return response.json();
}

export async function generateAssignmentExample(payload: {
  assignment_title: string;
  assignment_description: string;
  course_hint?: string;
}): Promise<{ example: string; source?: string }> {
  const response = await fetchWithTimeout(
    `${API_BASE_URL}/api/faculty/assignment-assistant/example`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
    LLM_FETCH_TIMEOUT_MS,
  );
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Ödev örneği hatası (${response.status}): ${apiErrorMessage(errorText, "Ödev örneği üretilemedi")}`,
    );
  }
  return response.json();
}

export async function getQuestions(): Promise<QuestionItem[]> {
  const response = await fetch(`${API_BASE_URL}/api/questions`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Sorular listesi hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function createQuestion(payload: {
  content: string;
  color: "blue" | "green" | "pink" | "yellow";
}): Promise<QuestionItem> {
  const response = await fetch(`${API_BASE_URL}/api/questions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Soru ekleme hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function deleteQuestion(questionId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/questions/${questionId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Soru silme hatası (${response.status}): ${errorText}`);
  }
}

export async function getAssignmentQuestions(assignmentId: string): Promise<QuestionItem[]> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}/questions`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Atanan sorular hatası (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function updateAssignmentQuestions(payload: {
  assignment_id: string;
  question_ids: string[];
}): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/assignment-questions/update`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Soru güncelleme hatası (${response.status}): ${errorText}`);
  }
}

export async function updateTeacherEmail(teacherId: string, email: string): Promise<Teacher> {
  const response = await fetch(`${API_BASE_URL}/api/teacher/${teacherId}/email`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) {
    throw new Error(await parseApiErrorMessage(response, "E-posta güncellenemedi"));
  }
  return response.json();
}

export async function updateTeacherPassword(
  teacherId: string,
  payload: { current_password?: string; new_password: string },
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/teacher/${teacherId}/password`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await parseApiErrorMessage(response, "Şifre güncellenemedi"));
  }
}
