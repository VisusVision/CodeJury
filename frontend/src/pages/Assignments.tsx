import { useEffect, useState, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BookOpen, LogOut, GraduationCap, FileText, ArrowLeft, X } from "lucide-react";
import { getCourse, getCourseAssignments, getStudentCourses, getAssignmentQuestions, QuestionItem } from "@/services/api";
import { differenceInDays, differenceInHours, format } from "date-fns";
import { tr as trLocale } from "date-fns/locale";
import { enUS as enLocale } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import { splitAssignmentDescription } from "@/lib/assignmentDescription";
import { useAuth } from "../auth/AuthContext";

interface Student {
  id: string;
  first_name: string;
  last_name: string;
  student_no: string;
  department_name?: string | null;
  class_year?: number | null;
}

interface Course {
  id: string;
  name: string;
  code: string;
}

interface Assignment {
  id: string;
  course_id: string;
  name: string;
  description: string | null;
  due_date?: string | null;
}

const Assignments = () => {
  const { t, language } = useTranslation();
  const { status, role, user, logout } = useAuth();
  const dateLocale = language === "tr" ? trLocale : enLocale;
  const { courseId } = useParams<{ courseId: string }>();
  const [student, setStudent] = useState<Student | null>(null);
  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [hoveredAssignmentId, setHoveredAssignmentId] = useState<string | null>(null);
  const hoverTimeoutRef = useRef<Record<string, number | null>>({});
  const [assignmentQuestions, setAssignmentQuestions] = useState<Record<string, QuestionItem[]>>({});
  const [loadingQuestions, setLoadingQuestions] = useState<Record<string, boolean>>({});
  const navigate = useNavigate();

  useEffect(() => {
    if (status === "loading") return;
    if (status === "anonymous" || role !== "student") {
      navigate("/login");
      return;
    }
    if (!user) return;
    setStudent({
      id: String(user.id ?? ""),
      first_name: String(user.first_name ?? ""),
      last_name: String(user.last_name ?? ""),
      student_no: String(user.student_no ?? ""),
      department_name: user.department_name != null ? String(user.department_name) : null,
      class_year: user.class_year != null ? Number(user.class_year) : null,
    });
  }, [status, role, user, navigate]);

  useEffect(() => {
    if (status !== "authenticated" || role !== "student" || !user) return;

    const fetchData = async () => {
      if (!courseId) {
        navigate("/courses", { replace: true });
        return;
      }
      try {
        const [courseData, coursesData, assignmentsData] = await Promise.all([
          getCourse(courseId),
          getStudentCourses(String(user.id)),
          getCourseAssignments(courseId),
        ]);
        if (!coursesData.some((c) => c.id === courseId)) {
          navigate("/courses", { replace: true });
          return;
        }
        const safeAssignments = assignmentsData || [];

        setErrorMessage(null);
        setCourse(courseData);
        setAllCourses(coursesData || []);
        setAssignments(safeAssignments);
      } catch (error) {
        console.error(error);
        setErrorMessage(language === "tr" ? "Ders veya ödevler yüklenemedi." : "Course or assignments could not be loaded.");
        setCourse(null);
        setAllCourses([]);
        setAssignments([]);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [courseId, language, navigate, status, role, user]);

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  const loadAssignmentQuestions = async (assignmentId: string) => {
    if (assignmentQuestions[assignmentId]) return; // Already loaded
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

  const handleBadgeMouseEnter = (assignmentId: string) => {
    const t = hoverTimeoutRef.current[assignmentId];
    if (t) {
      window.clearTimeout(t);
      hoverTimeoutRef.current[assignmentId] = null;
    }
    setHoveredAssignmentId(assignmentId);
    loadAssignmentQuestions(assignmentId);
  };

  const handleBadgeMouseLeave = (assignmentId: string) => {
    hoverTimeoutRef.current[assignmentId] = window.setTimeout(() => {
      if (hoveredAssignmentId === assignmentId) setHoveredAssignmentId(null);
      hoverTimeoutRef.current[assignmentId] = null;
    }, 150) as unknown as number;
  };

  if (status === "loading" || !student) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-[260px_1fr] h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <aside className="flex flex-col h-full min-h-0 bg-sidebar">
        <div className="p-5 pb-4">
          <div className="flex items-center gap-2 mb-1">
            <div className="h-6 w-6 rounded-md bg-primary flex items-center justify-center">
              <GraduationCap className="h-3.5 w-3.5 text-primary-foreground" />
            </div>
            <h1 className="text-sm font-bold text-foreground tracking-tight">
              {student.first_name} {student.last_name}
            </h1>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {student.student_no}{student.class_year ? ` - ${student.class_year}. ${t("courses.classYear")}` : ""}
          </p>
          <p className="text-xs text-muted-foreground">
            {student.department_name || "—"}
          </p>
        </div>

        <nav className="flex-1 min-h-0 overflow-y-auto px-3 space-y-0.5">
          <div className="px-2 py-2">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">{t("courses.title")}</span>
          </div>
          {allCourses.map((c) => (
            <button
              key={c.id}
              onClick={() => navigate(`/courses/${c.id}/assignments`)}
              className={`flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm transition-colors duration-150 ${
                c.id === courseId
                  ? "bg-card shadow-card text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              }`}
            >
              <BookOpen className="h-4 w-4 text-primary shrink-0" />
              <span className="truncate">{c.name}</span>
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

      {/* Main content */}
      <main className="flex min-h-0 flex-col overflow-y-auto p-6 lg:p-8">
        <button
          onClick={() => navigate("/courses")}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4 w-fit transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> {t("assignments.backToCourses")}
        </button>

        <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">{t("assignments.title")}</h1>
        <p className="text-sm text-muted-foreground mb-6">
          {course?.name} — {course?.code}
        </p>

        {loading ? (
          <p className="text-sm text-muted-foreground">{t("common.loading")}</p>
        ) : errorMessage ? (
          <div className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            {errorMessage}
          </div>
        ) : assignments.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">{t("assignments.noAssignments")}</p>
          </div>
        ) : (
          <div className="grid max-w-2xl gap-2 pb-8 relative">
            {assignments.map((assignment) => (
              (() => {
                let remainingLabel = "";
                let remainingColor = "text-muted-foreground";
                if (assignment.due_date) {
                  const now = new Date();
                  const due = new Date(assignment.due_date);
                  const days = differenceInDays(due, now);
                  const hours = differenceInHours(due, now);
                  if (hours <= 0) {
                    remainingLabel = language === "tr" ? "Teslim tarihi geçmiştir" : "Past due";
                    remainingColor = "text-destructive";
                  } else if (days === 0) {
                    remainingLabel = language === "tr" ? `${hours} saat kaldı` : `${hours}h left`;
                    remainingColor = "text-orange-500";
                  } else {
                    remainingLabel = language === "tr" ? `${days} gün kaldı` : `${days}d left`;
                    remainingColor = days <= 3 ? "text-orange-500" : "text-emerald-500";
                  }
                }

                const questions = assignmentQuestions[assignment.id] || [];
                const isHovered = hoveredAssignmentId === assignment.id;
                const isLoading = loadingQuestions[assignment.id];
                const description = splitAssignmentDescription(assignment.description);

                return (
                  <div
                    key={assignment.id}
                    className="relative"
                  >
                    <button
                      onClick={() => navigate(`/courses/${courseId}/assignments/${assignment.id}`)}
                      className="relative flex items-start gap-2.5 px-2.5 py-2 rounded-xl border border-border bg-card hover:shadow-md transition-all text-left w-full"
                    >
                      <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0 mt-0.5">
                        <FileText className="h-4.5 w-4.5 text-primary" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-medium text-foreground truncate">{assignment.name}</p>
                          {remainingLabel && (
                            <span className={cn("text-xs font-medium whitespace-nowrap", remainingColor)}>
                              {remainingLabel}
                            </span>
                          )}
                        </div>
                        {description.body && (
                          <p className="text-xs text-muted-foreground mt-0.5 whitespace-normal break-words">{description.body}</p>
                        )}
                        {description.expectedOutput && (
                          <div className="mt-2 rounded-lg border border-primary/15 bg-primary/5 px-3 py-2">
                            <p className="text-[11px] font-semibold text-primary">Örnek çıktı</p>
                            <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px] leading-relaxed text-foreground">{description.expectedOutput}</pre>
                          </div>
                        )}
                        {assignment.due_date && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            {t("assignments.dueDate")}: {format(new Date(assignment.due_date), "dd MMM yyyy HH:mm", { locale: dateLocale })}
                          </p>
                        )}
                      </div>
                      
                      {/* Görevler badge - hover trigger */}
                      <div
                        onMouseEnter={() => handleBadgeMouseEnter(assignment.id)}
                        onMouseLeave={() => handleBadgeMouseLeave(assignment.id)}
                        className="absolute top-2 right-2 px-2 py-0.5 rounded-full bg-slate-500/15 text-slate-600 dark:text-slate-400 text-[10px] font-semibold cursor-pointer hover:bg-slate-500/25 transition-colors"
                      >
                        {t("assignments.tasks")}
                      </div>
                    </button>

                    {/* Hover panel - only shown on badge hover */}
                    {isHovered && hoveredAssignmentId === assignment.id && (
                      <div
                        className="absolute top-0 right-0 translate-x-[calc(100%+0.5rem)] w-64 bg-card border border-border rounded-lg shadow-lg z-40 overflow-hidden animate-in fade-in slide-in-from-left-2 duration-200"
                        onMouseEnter={() => {
                          const t = hoverTimeoutRef.current[assignment.id];
                          if (t) {
                            window.clearTimeout(t);
                            hoverTimeoutRef.current[assignment.id] = null;
                          }
                          setHoveredAssignmentId(assignment.id);
                        }}
                        onMouseLeave={() => {
                          hoverTimeoutRef.current[assignment.id] = window.setTimeout(() => {
                            if (hoveredAssignmentId === assignment.id) setHoveredAssignmentId(null);
                            hoverTimeoutRef.current[assignment.id] = null;
                          }, 150) as unknown as number;
                        }}
                      >
                        <div className="flex items-center justify-between px-3 py-2 bg-slate-500/10 border-b border-border">
                          <span className="text-xs font-semibold text-slate-600 dark:text-slate-400">{t("assignments.tasks").toUpperCase()}</span>
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
                          {isLoading ? (
                            <div className="p-3 text-xs text-muted-foreground text-center">{t("assignments.tasksLoading")}</div>
                          ) : questions.length === 0 ? (
                            <div className="p-3 text-xs text-muted-foreground text-center">{t("assignments.noTasks")}</div>
                          ) : (
                            <div className="divide-y divide-border">
                              {questions.map((q) => (
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
                );
              })()
            ))}
          </div>
        )}
      </main>
    </div>
  );
};

export default Assignments;
