/** Gelistirmede bos string = ayni origin (/api -> Vite proxy -> FastAPI). Uzak cihazdan UI acilinca gerekli. */
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "" : "http://127.0.0.1:8001");

export interface ApiFinding {
  severity: "error" | "warning" | "info" | "success";
  message: string;
  line?: number | null;
  agent?: string | null;
  code?: string | null;
}

export interface ApiAgentReport {
  id: string;
  name: string;
  summary: string;
  score: number;
  maxScore: number;
  findings: ApiFinding[];
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
}

export interface ApiAnalysisResult {
  totalScore: number;
  maxScore: number;
  rubric: ApiRubricCategory[];
  agents: ApiAgentReport[];
  evidence: ApiLineEvidence[];
  fileName: string;
  executionTimeMs: number;
  memoryUsageMb: number;
  peakMemoryMb: number;
  /** Backend rubrik duzeltmeleri; sessionStorage surumu ile eslestirmek icin */
  analysisEngine?: string;
  /** Dusuk not + zayif gorev uyumu (backend kosullu) */
  relevanceScoreWarning?: string | null;
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

export async function analyzeCode(fileName: string, fileContent: string, assignmentId?: string, reportLanguage?: string): Promise<ApiAnalysisResult> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file_name: fileName,
        file_content: fileContent,
        assignment_id: assignmentId,
        report_language: reportLanguage || "tr",
      }),
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

  return response.json();
}

export async function checkHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE_URL}/api/health`);
    return response.ok;
  } catch {
    return false;
  }
}

export async function loginStudent(studentNo: string, tcNo: string): Promise<Student | null> {
  const response = await fetch(`${API_BASE_URL}/api/student/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ student_no: studentNo, tc_no: tcNo }),
  });

  if (response.status === 404) return null;

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ogrenci giris hatasi (${response.status}): ${errorText}`);
  }

  return response.json();
}

export async function getStudents(): Promise<Student[]> {
  const response = await fetch(`${API_BASE_URL}/api/students`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ogrenci listesi hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Ogrenci ekleme hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Ogrenci guncelleme hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function deleteStudent(studentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/students/${studentId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ogrenci silme hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`CSV ogrenci yukleme hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getStudentCourses(studentId: string): Promise<Course[]> {
  const response = await fetch(`${API_BASE_URL}/api/student/${studentId}/courses`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders listesi hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getCourse(courseId: string): Promise<Course> {
  const response = await fetch(`${API_BASE_URL}/api/courses/${courseId}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders detayi hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getCourseAssignments(courseId: string): Promise<Assignment[]> {
  const response = await fetch(`${API_BASE_URL}/api/courses/${courseId}/assignments`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Odev listesi hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function getAssignment(assignmentId: string): Promise<Assignment> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Odev detayi hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Yukleme gecmisi kayit hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Yukleme gecmisi listeleme hatasi (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data as UploadHistoryApiRecord[] : [];
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
    throw new Error(`Ogretmen kayit hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Ogretmen giris hatasi (${response.status}): ${errorText}`);
  }

  return response.json();
}

export async function getDepartments(): Promise<Department[]> {
  const response = await fetch(`${API_BASE_URL}/api/departments`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Bolum listesi hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Bolum ekleme hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function deleteDepartment(departmentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/departments/${departmentId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Bolum silme hatasi (${response.status}): ${errorText}`);
  }
}

export async function getCourses(): Promise<Course[]> {
  const response = await fetch(`${API_BASE_URL}/api/courses`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders listesi hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Ders ekleme hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function deleteCourse(courseId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/courses/${courseId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ders silme hatasi (${response.status}): ${errorText}`);
  }
}

export async function getAssignments(): Promise<Assignment[]> {
  const response = await fetch(`${API_BASE_URL}/api/assignments`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Odev listesi hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Odev ekleme hatasi (${response.status}): ${apiErrorMessage(errorText, "Odev eklenemedi")}`);
  }
  return response.json();
}

export async function deleteAssignment(assignmentId: string): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/api/assignments/${assignmentId}`, { method: "DELETE" });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Odev silme hatasi (${response.status}): ${errorText}`);
  }
}

export async function getRubrics(): Promise<Rubric[]> {
  const response = await fetch(`${API_BASE_URL}/api/rubrics`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik listesi hatasi (${response.status}): ${errorText}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? data.map(normalizeRubric) : [];
}

export async function getRubricByAssignment(assignmentId: string): Promise<Rubric | null> {
  const response = await fetch(`${API_BASE_URL}/api/rubrics/by-assignment/${assignmentId}`);
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik detayi hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Rubrik kaydetme hatasi (${response.status}): ${errorText}`);
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
    throw new Error(`Rubrik durum guncelleme hatasi (${response.status}): ${errorText}`);
  }
  return response.json();
}

export async function suggestRubric(payload: {
  assignment_title: string;
  assignment_description: string;
  criterion_count?: number;
  report_language?: string;
}): Promise<{ criteria: RubricCriterion[] }> {
  const response = await fetch(`${API_BASE_URL}/api/rubric/suggest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Rubrik AI onerisi hatasi (${response.status}): ${errorText}`);
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
  const response = await fetch(`${API_BASE_URL}/api/faculty/assignment-assistant/suggestions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      course_hint: courseHint ?? "",
      count: count ?? 5,
      difficulty: difficulty ?? "medium",
      prefer_fresh: Boolean(preferFresh),
      report_language: reportLanguage || "tr",
    }),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(
      `Ödev önerileri hatası (${response.status}): ${apiErrorMessage(errorText, "Ödev önerileri alınamadı")}`,
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
    throw new Error(`Sorular güncelleme hatası (${response.status}): ${errorText}`);
  }
}

export async function updateTeacherEmail(teacherId: string, email: string): Promise<Teacher> {
  const response = await fetch(`${API_BASE_URL}/api/teacher/${teacherId}/email`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Ogretmen e-posta guncelleme hatasi (${response.status}): ${errorText}`);
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
    const errorText = await response.text();
    throw new Error(`Ogretmen sifre guncelleme hatasi (${response.status}): ${errorText}`);
  }
}
