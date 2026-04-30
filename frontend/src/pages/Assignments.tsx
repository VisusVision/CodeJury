import { useEffect, useState, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { BookOpen, LogOut, GraduationCap, FileText, ArrowLeft, X } from "lucide-react";
import { getCourse, getCourseAssignments, getStudentCourses, getAssignmentQuestions, QuestionItem } from "@/services/api";
import { differenceInDays, differenceInHours, format } from "date-fns";
import { tr } from "date-fns/locale";
import { cn } from "@/lib/utils";

interface Student {
  id: string;
  first_name: string;
  last_name: string;
  student_no: string;
  department_name?: string | null;
}

interface Course {
  id: string;
  name: string;
  code: string;
}

interface Assignment {
  id: string;
  name: string;
  description: string | null;
  due_date?: string | null;
}

const Assignments = () => {
  const { courseId } = useParams<{ courseId: string }>();
  const [student, setStudent] = useState<Student | null>(null);
  const [course, setCourse] = useState<Course | null>(null);
  const [allCourses, setAllCourses] = useState<Course[]>([]);
  const [assignments, setAssignments] = useState<Assignment[]>([]);
  const [loading, setLoading] = useState(true);
  const [hoveredAssignmentId, setHoveredAssignmentId] = useState<string | null>(null);
  const hoverTimeoutRef = useRef<Record<string, number | null>>({});
  const [assignmentQuestions, setAssignmentQuestions] = useState<Record<string, QuestionItem[]>>({});
  const [loadingQuestions, setLoadingQuestions] = useState<Record<string, boolean>>({});
  const navigate = useNavigate();

  useEffect(() => {
    const stored = sessionStorage.getItem("student");
    if (!stored) {
      navigate("/login");
      return;
    }
    const s = JSON.parse(stored) as Student;
    setStudent(s);

    const fetchData = async () => {
      try {
        const [courseData, coursesData, assignmentsData] = await Promise.all([
          getCourse(courseId!),
          getStudentCourses(s.id),
          getCourseAssignments(courseId!),
        ]);
        const safeAssignments = assignmentsData || [];

        setCourse(courseData);
        setAllCourses(coursesData || []);
        setAssignments(safeAssignments);
      } catch (error) {
        console.error(error);
        setCourse(null);
        setAllCourses([]);
        setAssignments([]);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [courseId, navigate]);

  const handleLogout = () => {
    sessionStorage.removeItem("student");
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

  if (!student) return null;

  return (
    <div className="grid grid-cols-[260px_1fr] h-screen overflow-hidden bg-background">
      {/* Sidebar */}
      <aside className="flex flex-col h-full bg-sidebar">
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
            {student.student_no}
            {student.department_name ? ` - ${student.department_name}` : ""}
          </p>
        </div>

        <nav className="flex-1 px-3 space-y-0.5">
          <div className="px-2 py-2">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Dersler</span>
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
            <span>Çıkış Yap</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex flex-col p-6 lg:p-8 overflow-hidden">
        <button
          onClick={() => navigate("/courses")}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-4 w-fit transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> Derslere Dön
        </button>

        <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Ödevler</h1>
        <p className="text-sm text-muted-foreground mb-6">
          {course?.name} — {course?.code}
        </p>

        {loading ? (
          <p className="text-sm text-muted-foreground">Yükleniyor...</p>
        ) : assignments.length === 0 ? (
          <div className="text-center py-12">
            <FileText className="h-8 w-8 text-muted-foreground/40 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">Bu ders için henüz ödev tanımlanmamış.</p>
          </div>
        ) : (
          <div className="grid gap-2 max-w-2xl relative">
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
                    remainingLabel = "Teslim tarihi geçmiştir";
                    remainingColor = "text-destructive";
                  } else if (days === 0) {
                    remainingLabel = `${hours} saat kaldı`;
                    remainingColor = "text-orange-500";
                  } else {
                    remainingLabel = `${days} gün kaldı`;
                    remainingColor = days <= 3 ? "text-orange-500" : "text-emerald-500";
                  }
                }

                const questions = assignmentQuestions[assignment.id] || [];
                const isHovered = hoveredAssignmentId === assignment.id;
                const isLoading = loadingQuestions[assignment.id];

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
                        {assignment.description && (
                          <p className="text-xs text-muted-foreground mt-0.5 whitespace-normal break-words">{assignment.description}</p>
                        )}
                        {assignment.due_date && (
                          <p className="text-xs text-muted-foreground mt-0.5">
                            Son teslim: {format(new Date(assignment.due_date), "dd MMM yyyy HH:mm", { locale: tr })}
                          </p>
                        )}
                      </div>
                      
                      {/* Görevler badge - hover trigger */}
                      <div
                        onMouseEnter={() => handleBadgeMouseEnter(assignment.id)}
                        onMouseLeave={() => handleBadgeMouseLeave(assignment.id)}
                        className="absolute top-2 right-2 px-2 py-0.5 rounded-full bg-slate-500/15 text-slate-600 dark:text-slate-400 text-[10px] font-semibold cursor-pointer hover:bg-slate-500/25 transition-colors"
                      >
                        Görevler
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
                          <span className="text-xs font-semibold text-slate-600 dark:text-slate-400">GÖREVLER</span>
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
                            <div className="p-3 text-xs text-muted-foreground text-center">Sorular yükleniyor...</div>
                          ) : questions.length === 0 ? (
                            <div className="p-3 text-xs text-muted-foreground text-center">Henüz soru atanmamış</div>
                          ) : (
                            <div className="divide-y divide-border">
                              {questions.map((q) => (
                                <div
                                  key={q.id}
                                  className={cn(
                                    "px-3 py-2 text-xs border-l-4",
                                    q.color === "blue"
                                      ? "bg-blue-50 border-l-blue-500 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400"
                                      : q.color === "green"
                                        ? "bg-green-50 border-l-green-500 text-green-700 dark:bg-green-900/20 dark:text-green-400"
                                        : q.color === "pink"
                                          ? "bg-pink-50 border-l-pink-500 text-pink-700 dark:bg-pink-900/20 dark:text-pink-400"
                                          : "bg-yellow-50 border-l-yellow-500 text-yellow-700 dark:bg-yellow-900/20 dark:text-yellow-400"
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
