import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  GraduationCap, LogOut, Building2, BookOpen, FileText, Plus, Trash2, Pencil, Settings, CalendarIcon, Clock, Users, ShieldCheck, Loader2,
} from "lucide-react";
import { format, differenceInDays, differenceInHours } from "date-fns";
import { tr as trLocale } from "date-fns/locale";
import { enUS as enLocale } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { useTranslation, LanguageToggle } from "@/i18n/LanguageContext";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import RubricModal from "@/components/faculty/RubricModal";
import AssignmentChatbot from "@/components/faculty/AssignmentChatbot";
import SettingsPanel from "@/components/faculty/SettingsPanel";
import StudentsPanel from "@/components/faculty/StudentsPanel";
import { toast } from "sonner";
import {
  createAssignment,
  createCourse,
  createDepartment,
  deleteAssignment as removeAssignment,
  deleteCourse as removeCourse,
  deleteDepartment as removeDepartment,
  getAssignments,
  getCourses,
  getDepartments,
  getEvaluations,
  getRubrics,
  updateRubricStatusByAssignment,
  type EvaluationRecord,
} from "@/services/api";

interface Teacher {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
}

interface Department {
  id: string;
  name: string;
}

interface Course {
  id: string;
  name: string;
  code: string;
  department_id?: string | null;
  class_year?: number | null;
}

interface Assignment {
  id: string;
  name: string;
  description: string | null;
  course_id: string;
  due_date: string | null;
}

type Tab = "departments" | "courses" | "assignments" | "students" | "evaluations" | "settings";

interface RubricModalState {
  open: boolean;
  assignment: Assignment | null;
}

const getErrorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

const FacultyDashboard = () => {
  const { t, language } = useTranslation();
  const dateLocale = language === "tr" ? trLocale : enLocale;
  const navigate = useNavigate();
  const [teacher, setTeacher] = useState<Teacher | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("departments");
  const [departments, setDepartments] = useState<Department[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [rubricStatuses, setRubricStatuses] = useState<Record<string, string>>({});
  const [evaluations, setEvaluations] = useState<EvaluationRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [rubricModal, setRubricModal] = useState<RubricModalState>({ open: false, assignment: null });
  const [chatbotOpen, setChatbotOpen] = useState(false);
  const [assignmentSubmitting, setAssignmentSubmitting] = useState(false);

  // Form states
  const [newDeptName, setNewDeptName] = useState("");
  const [newCourseName, setNewCourseName] = useState("");
  const [newCourseCode, setNewCourseCode] = useState("");
  const [selectedDeptId, setSelectedDeptId] = useState("");
  const [selectedClassYear, setSelectedClassYear] = useState("");
  const [newAssignmentName, setNewAssignmentName] = useState("");
  const [newAssignmentDesc, setNewAssignmentDesc] = useState("");
  const [selectedCourseId, setSelectedCourseId] = useState("");
  const [dueDate, setDueDate] = useState<Date | undefined>(undefined);
  const [dueTime, setDueTime] = useState("23:59");

  useEffect(() => {
    const checkAuth = async () => {
      const teacherRaw = sessionStorage.getItem("teacher");
      if (!teacherRaw) {
        navigate("/login");
        return;
      }
      const teacherData = JSON.parse(teacherRaw) as Teacher;
      setTeacher(teacherData);
      await fetchAll();
      setLoading(false);
    };
    checkAuth();
  }, [navigate]);

  const fetchAll = async () => {
    const [departmentsData, coursesData, assignmentsData, rubricsData, evaluationsData] = await Promise.all([
      getDepartments(),
      getCourses(),
      getAssignments(),
      getRubrics(),
      getEvaluations(),
    ]);
    setDepartments(departmentsData);
    setCourses(coursesData);
    setAssignments(assignmentsData as Assignment[]);
    const statusMap: Record<string, string> = {};
    rubricsData.forEach((r) => { statusMap[r.assignment_id] = r.status; });
    setRubricStatuses(statusMap);
    setEvaluations(evaluationsData);
  };

  const handleLogout = async () => {
    sessionStorage.removeItem("teacher");
    navigate("/login");
  };

  // CRUD handlers
  const addDepartment = async () => {
    if (!newDeptName.trim()) return;
    try {
      await createDepartment({
        name: newDeptName.trim(),
        created_by: teacher!.id,
      });
      toast.success("Bölüm eklendi");
      setNewDeptName("");
      await fetchAll();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, "Bölüm eklenemedi"));
    }
  };

  const deleteDepartment = async (id: string) => {
    try {
      await removeDepartment(id);
      toast.success("Bölüm silindi");
      await fetchAll();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, "Bölüm silinemedi"));
    }
  };

  const addCourse = async () => {
    if (!newCourseName.trim() || !newCourseCode.trim() || !selectedClassYear.trim()) return;
    const normalizedName = newCourseName.trim().replace(/\b\w+/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
    try {
      await createCourse({
        name: normalizedName,
        code: newCourseCode.trim(),
        department_id: selectedDeptId || null,
        class_year: Number(selectedClassYear),
      });
      toast.success("Ders eklendi");
      setNewCourseName("");
      setNewCourseCode("");
      setSelectedDeptId("");
      setSelectedClassYear("");
      await fetchAll();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, "Ders eklenemedi"));
    }
  };

  const deleteCourse = async (id: string) => {
    try {
      await removeCourse(id);
      toast.success("Ders silindi");
      await fetchAll();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, "Ders silinemedi"));
    }
  };

  const addAssignment = async () => {
    if (assignmentSubmitting || !newAssignmentName.trim() || !selectedCourseId) return;
    let dueDateISO: string | null = null;
    if (dueDate) {
      const [h, m] = dueTime.split(":").map(Number);
      const d = new Date(dueDate);
      d.setHours(h, m, 0, 0);
      dueDateISO = d.toISOString();
    }
    const normalizedName = newAssignmentName.trim().replace(/\b\w+/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
    setAssignmentSubmitting(true);
    try {
      const created = await createAssignment({
        name: normalizedName,
        description: newAssignmentDesc.trim() || null,
        course_id: selectedCourseId,
        due_date: dueDateISO,
      });
      toast.success("Ödev eklendi");
      setNewAssignmentName("");
      setNewAssignmentDesc("");
      setDueDate(undefined);
      setDueTime("23:59");
      if (created && typeof (created as Assignment).id === "string" && (created as Assignment).id.trim()) {
        setAssignments((prev) => [
          created as Assignment,
          ...prev.filter((a) => a.id !== (created as Assignment).id),
        ]);
      }
      await fetchAll();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, "Ödev eklenemedi"));
    } finally {
      setAssignmentSubmitting(false);
    }
  };

  const approveAssignment = async (assignmentId: string) => {
    const status = rubricStatuses[assignmentId];
    if (!status) {
      toast.error("Önce rubrik oluşturmalısınız");
      return;
    }
    try {
      await updateRubricStatusByAssignment(assignmentId, "approved");
      toast.success("Ödev onaylandı");
      await fetchAll();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, "Onaylama başarısız"));
    }
  };

  const deleteAssignment = async (id: string) => {
    try {
      await removeAssignment(id);
      toast.success("Ödev silindi");
      await fetchAll();
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, "Ödev silinemedi"));
    }
  };

  if (loading || !teacher) {
    return <div className="min-h-screen flex items-center justify-center text-muted-foreground">{t("common.loading")}</div>;
  }

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    { key: "departments", label: t("faculty.tabs.departments"), icon: <Building2 className="h-4 w-4" /> },
    { key: "courses", label: t("faculty.tabs.courses"), icon: <BookOpen className="h-4 w-4" /> },
    { key: "assignments", label: t("faculty.tabs.assignments"), icon: <FileText className="h-4 w-4" /> },
    { key: "students", label: t("faculty.tabs.students"), icon: <Users className="h-4 w-4" /> },
    { key: "evaluations", label: language === "tr" ? "Değerlendirmeler" : "Evaluations", icon: <FileText className="h-4 w-4" /> },
    { key: "settings", label: t("faculty.tabs.settings"), icon: <Settings className="h-4 w-4" /> },
  ];

  return (
    <div className="grid grid-cols-[260px_1fr] h-screen bg-background overflow-hidden">
      {/* Sidebar */}
      <aside className="flex flex-col h-full bg-sidebar border-r border-border/50 overflow-hidden">
        <div className="p-5 pb-4">
          <div className="flex items-center gap-2 mb-1">
            <div className="h-6 w-6 rounded-md bg-primary flex items-center justify-center">
              <GraduationCap className="h-3.5 w-3.5 text-primary-foreground" />
            </div>
            <h1 className="text-sm font-bold text-foreground tracking-tight">
              {teacher.first_name} {teacher.last_name}
            </h1>
          </div>
          <p className="text-xs text-muted-foreground mt-1">{t("faculty.title")}</p>
        </div>

        <nav className="flex-1 px-3 space-y-0.5 overflow-auto">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm transition-colors duration-150 ${
                activeTab === tab.key
                  ? "bg-card shadow-card text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>

        <div className="p-3 border-t border-border/50">
          <button
            onClick={handleLogout}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors duration-150"
          >
            <LogOut className="h-4 w-4" />
            <span>{t("common.logout")}</span>
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className={cn("flex flex-col p-6 lg:p-8", (activeTab === "settings" || activeTab === "students" || activeTab === "evaluations") ? "overflow-hidden" : "overflow-y-auto")}>
        {activeTab === "departments" && (
          <>
            <div className="flex items-center justify-between mb-1">
              <h1 className="text-2xl font-bold tracking-tight text-foreground">{t("faculty.departments.title")}</h1>
              <LanguageToggle />
            </div>
            <p className="text-sm text-muted-foreground mb-6">{t("faculty.departments.subtitle")}</p>

            <div className="flex gap-2 mb-6 max-w-lg">
              <input
                type="text"
                value={newDeptName}
                onChange={(e) => setNewDeptName(e.target.value)}
                placeholder="Bölüm adı"
                className="flex-1 px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              />
              <button onClick={addDepartment} className="flex items-center gap-1 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all">
                <Plus className="h-4 w-4" /> Ekle
              </button>
            </div>

            <div className="grid gap-2 max-w-lg">
              {departments.map((d) => (
                <div key={d.id} className="flex items-center justify-between p-3 rounded-xl border border-border bg-card">
                  <div className="flex items-center gap-3">
                    <Building2 className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium text-foreground">{d.name}</span>
                  </div>
                  <button onClick={() => deleteDepartment(d.id)} className="text-muted-foreground hover:text-destructive transition-colors">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </>
        )}

        {activeTab === "courses" && (
          <>
            <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Dersler</h1>
            <p className="text-sm text-muted-foreground mb-6">Ders ekleyin veya mevcut dersleri yönetin.</p>

            <div className="flex flex-col gap-3 mb-6 max-w-lg">
              <div className="grid grid-cols-2 gap-2">
                <input
                  type="text"
                  value={newCourseName}
                  onChange={(e) => setNewCourseName(e.target.value)}
                  placeholder="Ders adı"
                  className="px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <input
                  type="text"
                  value={newCourseCode}
                  onChange={(e) => setNewCourseCode(e.target.value)}
                  placeholder="Ders kodu"
                  className="px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div className="grid grid-cols-2 gap-2">
                <select
                  value={selectedDeptId}
                  onChange={(e) => setSelectedDeptId(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="">Bölüm seçin</option>
                  {departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.name}</option>
                  ))}
                </select>

                <div className="flex items-center gap-2 w-full">
                  <select
                    value={selectedClassYear}
                    onChange={(e) => setSelectedClassYear(e.target.value)}
                    className="flex-1 min-w-0 px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="">Sınıf seçin</option>
                    <option value="1">1. sınıf</option>
                    <option value="2">2. sınıf</option>
                    <option value="3">3. sınıf</option>
                    <option value="4">4. sınıf</option>
                  </select>
                  <button onClick={addCourse} className="flex items-center gap-1 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all">
                    <Plus className="h-4 w-4" /> Ekle
                  </button>
                </div>
              </div>
            </div>

            <div className="grid gap-2 max-w-lg">
              {courses.map((c) => (
                <div key={c.id} className="flex items-center justify-between p-3 rounded-xl border border-border bg-card">
                  <div className="flex items-center gap-3">
                    <BookOpen className="h-4 w-4 text-primary" />
                    <div>
                      <span className="text-sm font-medium text-foreground">{c.name}</span>
                      <span className="text-xs text-muted-foreground ml-2">{c.code}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        {c.class_year ? `${c.class_year}. sınıf` : "Genel"}
                      </span>
                    </div>
                  </div>
                  <button onClick={() => deleteCourse(c.id)} className="text-muted-foreground hover:text-destructive transition-colors">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          </>
        )}

        {activeTab === "assignments" && (
          <>
            <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Ödevler</h1>
            <p className="text-sm text-muted-foreground mb-6">Ödev oluşturun ve düzenleyin.</p>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Left: Add form */}
              <div>
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">Yeni Ödev</h2>
                    <div className="group relative">
                      <div className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-emerald-500/30 bg-emerald-500/10 text-emerald-600">
                        <ShieldCheck className="h-3.5 w-3.5" />
                      </div>
                      <div className="pointer-events-none absolute left-0 top-8 z-20 w-72 rounded-lg border border-border bg-card p-3 text-xs shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                        <p className="font-semibold text-emerald-700 dark:text-emerald-300">Güvenlik Ajanı Aktif</p>
                        <p className="mt-1 text-muted-foreground">
                          Kayıt öncesi suç, madde kullanımı, terör gibi riskli içerikler kontrol edilir. Paylaşılan içeriklerin hukuki sorumluluğu eğitmene aittir.
                        </p>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => setChatbotOpen(true)}
                    className="group relative flex items-center gap-1.5 pl-2 pr-3 py-1.5 rounded-full bg-gradient-to-r from-primary to-purple-600 text-primary-foreground text-xs font-semibold shadow-lg hover:shadow-xl transition-all hover:scale-105 hover:-translate-y-0.5"
                    title="AI ile ödev oluştur"
                  >
                    <span className="text-base leading-none animate-bounce">🤖</span>
                    <span>AI ile Oluştur</span>
                    <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-emerald-400 animate-ping" />
                    <span className="absolute -top-1 -right-1 h-2 w-2 rounded-full bg-emerald-400" />
                  </button>
                </div>
                <div className="flex flex-col gap-3">
                  <select
                    value={selectedCourseId}
                    onChange={(e) => setSelectedCourseId(e.target.value)}
                    className="px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="">Ders seçin</option>
                    {courses.map((c) => (
                      <option key={c.id} value={c.id}>{c.name} ({c.code}) - {c.class_year ? `${c.class_year}. sınıf` : "Genel"}</option>
                    ))}
                  </select>
                  <input
                    type="text"
                    value={newAssignmentName}
                    onChange={(e) => setNewAssignmentName(e.target.value)}
                    placeholder="Ödev başlığı"
                    className="px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  <textarea
                    value={newAssignmentDesc}
                    onChange={(e) => setNewAssignmentDesc(e.target.value)}
                    placeholder="Ödev açıklaması"
                    rows={4}
                    className="px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  />
                  {/* Due date & time */}
                  <div className="flex gap-2">
                    <Popover>
                      <PopoverTrigger asChild>
                        <button
                          type="button"
                          className={cn(
                            "flex-1 flex items-center gap-2 px-3 py-2 rounded-lg border border-input bg-background text-sm text-left",
                            !dueDate && "text-muted-foreground"
                          )}
                        >
                          <CalendarIcon className="h-4 w-4" />
                          {dueDate ? format(dueDate, "dd MMM yyyy", { locale: dateLocale }) : (language === "tr" ? "Son tarih seçin" : "Select deadline")}
                        </button>
                      </PopoverTrigger>
                      <PopoverContent className="w-auto p-0" align="start">
                        <Calendar
                          mode="single"
                          selected={dueDate}
                          onSelect={setDueDate}
                          disabled={(date) => date < new Date(new Date().setHours(0, 0, 0, 0))}
                          initialFocus
                          className={cn("p-3 pointer-events-auto")}
                        />
                      </PopoverContent>
                    </Popover>
                    <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg border border-input bg-background">
                      <Clock className="h-4 w-4 text-muted-foreground" />
                      <input
                        type="time"
                        value={dueTime}
                        onChange={(e) => setDueTime(e.target.value)}
                        className="bg-transparent text-foreground text-sm focus:outline-none w-20"
                      />
                    </div>
                  </div>
                  <button
                    onClick={addAssignment}
                    disabled={assignmentSubmitting}
                    className="flex items-center gap-1 px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all w-fit disabled:opacity-60 disabled:cursor-not-allowed"
                  >
                    {assignmentSubmitting ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" /> Ajan kontrol ediyor...
                      </>
                    ) : (
                      <>
                        <Plus className="h-4 w-4" /> Ödev Ekle
                      </>
                    )}
                  </button>
                </div>
              </div>

              {/* Right: Assignment list */}
              <div>
                <h2 className="text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-3">Düzenleyici</h2>
                <div className="space-y-2">
                  {assignments.length === 0 ? (
                    <div className="text-center py-8 text-sm text-muted-foreground">
                      <FileText className="h-6 w-6 mx-auto mb-2 opacity-40" />
                      Henüz ödev eklenmemiş.
                    </div>
                  ) : (
                    assignments.map((a) => {
                      const course = courses.find((c) => c.id === a.course_id);
                      let remainingLabel = "";
                      let remainingColor = "text-muted-foreground";
                      if (a.due_date) {
                        const now = new Date();
                        const due = new Date(a.due_date);
                        const days = differenceInDays(due, now);
                        const hours = differenceInHours(due, now);
                        if (hours <= 0) {
                          remainingLabel = "";
                          remainingColor = "text-destructive";
                        } else if (days === 0) {
                          remainingLabel = `${hours} saat kaldı`;
                          remainingColor = "text-orange-500";
                        } else {
                          remainingLabel = `${days} gün kaldı`;
                          remainingColor = days <= 3 ? "text-orange-500" : "text-emerald-500";
                        }
                      }
                      return (
                        <div key={a.id} className="flex items-center justify-between p-3 rounded-xl border border-border bg-card">
                          <div className="flex items-center gap-3 flex-1 min-w-0">
                            <FileText className="h-4 w-4 text-primary shrink-0" />
                            <div className="min-w-0">
                              <div className="flex items-center gap-2">
                                <p className="text-sm font-medium text-foreground truncate">{a.name}</p>
                                {(() => {
                                  const isPastDue = Boolean(a.due_date && new Date(a.due_date) < new Date());
                                  const st = rubricStatuses[a.id];
                                  const isApproved = st === "approved";
                                  if (isPastDue) {
                                    return (
                                      <span className={cn(
                                        "text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded whitespace-nowrap",
                                        "bg-destructive/15 text-destructive"
                                      )}>
                                        Geçmiş
                                      </span>
                                    );
                                  }
                                  return (
                                    <span className={cn(
                                      "text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.5 rounded whitespace-nowrap",
                                      isApproved
                                        ? "bg-emerald-500/15 text-emerald-600"
                                        : "bg-yellow-500/15 text-yellow-600"
                                    )}>
                                      {isApproved ? "Onaylandı" : "Taslak"}
                                    </span>
                                  );
                                })()}
                                {remainingLabel && (
                                  <span className={cn("text-xs font-medium whitespace-nowrap", remainingColor)}>
                                    {remainingLabel}
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-muted-foreground">
                                {course?.name || "—"}{course?.code ? ` (${course.code})` : ""}{course?.class_year ? ` - ${course.class_year}. sınıf` : ""}
                                {a.due_date && ` · ${format(new Date(a.due_date), "dd MMM yyyy HH:mm", { locale: dateLocale })}`}
                              </p>
                            </div>
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            <button
                              onClick={() => setRubricModal({ open: true, assignment: a })}
                              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-accent text-accent-foreground text-xs font-medium hover:bg-accent/80 transition-colors"
                            >
                              <Pencil className="h-3 w-3" /> Düzenle
                            </button>
                            <button onClick={() => deleteAssignment(a.id)} className="text-muted-foreground hover:text-destructive transition-colors">
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </div>
                        </div>
                      );
                    })
                  )}
                </div>
              </div>

            </div>

            {/* Rubric Modal */}
            {rubricModal.assignment && (
              <RubricModal
                assignment={rubricModal.assignment}
                teacherId={teacher!.id}
                open={rubricModal.open}
                onClose={() => { setRubricModal({ open: false, assignment: null }); fetchAll(); }}
              />
            )}

            <AssignmentChatbot
              open={chatbotOpen}
              onClose={() => setChatbotOpen(false)}
              courses={courses}
              teacherId={teacher!.id}
              onCreated={fetchAll}
            />
          </>
        )}

        {activeTab === "settings" && teacher && <SettingsPanel teacher={teacher} onTeacherUpdate={setTeacher} />}

        {activeTab === "students" && <StudentsPanel departments={departments} />}

        {activeTab === "evaluations" && (
          <div className="flex h-full flex-col overflow-hidden">
            <h1 className="mb-1 text-2xl font-bold tracking-tight text-foreground">{language === "tr" ? "Değerlendirmeler" : "Evaluations"}</h1>
            <p className="mb-6 text-sm text-muted-foreground">
              {language === "tr" ? "Öğrenci değerlendirme listesi." : "Student evaluation list."}
            </p>

            <div className="overflow-x-auto rounded-xl border border-border bg-card">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-muted/60 backdrop-blur">
                  <tr className="text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                    <th className="whitespace-nowrap px-4 py-3">Öğrenci No</th>
                    <th className="whitespace-nowrap px-4 py-3">Ad</th>
                    <th className="whitespace-nowrap px-4 py-3">Soyad</th>
                    <th className="whitespace-nowrap px-4 py-3">Fayda</th>
                    <th className="whitespace-nowrap px-4 py-3">Doğruluk</th>
                    <th className="whitespace-nowrap px-4 py-3">Açıklık</th>
                    <th className="whitespace-nowrap px-4 py-3">Yorum</th>
                    <th className="whitespace-nowrap px-4 py-3">Durum</th>
                    <th className="whitespace-nowrap px-4 py-3">Ödev</th>
                    <th className="whitespace-nowrap px-4 py-3">Teslim Tarihi</th>
                  </tr>
                </thead>
                <tbody>
                  {evaluations.length === 0 ? (
                    <tr>
                      <td className="px-4 py-8 text-center text-muted-foreground" colSpan={10}>
                        {language === "tr" ? "Henüz değerlendirme yok." : "No evaluations yet."}
                      </td>
                    </tr>
                  ) : (
                    evaluations.map((evaluation) => (
                      <tr key={evaluation.id} className="border-t border-border/50">
                        <td className="whitespace-nowrap px-4 py-3 font-medium text-foreground">{evaluation.student_no}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{evaluation.student_first_name}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{evaluation.student_last_name}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-center">
                          {evaluation.usefulness ? `${evaluation.usefulness}/5` : '-'}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-center">
                          {evaluation.accuracy ? `${evaluation.accuracy}/5` : '-'}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-center">
                          {evaluation.clarity ? `${evaluation.clarity}/5` : '-'}
                        </td>
                        <td className="max-w-xs px-4 py-3 text-xs text-muted-foreground truncate" title={evaluation.comment || ''}>
                          {evaluation.comment ? evaluation.comment : '-'}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <span className={cn(
                            "inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider",
                            evaluation.status === "pending"
                              ? "bg-amber-500/15 text-amber-700"
                              : "bg-emerald-500/15 text-emerald-700"
                          )}>
                            {evaluation.status === "pending"
                              ? (language === "tr" ? "Bekliyor" : "Pending")
                              : (language === "tr" ? "Gönderildi" : "Submitted")}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{evaluation.uploaded_file_name}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-xs text-muted-foreground">
                          {evaluation.uploaded_at ? new Date(evaluation.uploaded_at).toLocaleDateString('tr-TR', {
                            year: 'numeric',
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit'
                          }) : '-'}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default FacultyDashboard;
