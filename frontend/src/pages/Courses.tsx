import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, LogOut, GraduationCap } from "lucide-react";
import { getStudentCourses } from "@/services/api";

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

const Courses = () => {
  const [student, setStudent] = useState<Student | null>(null);
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const stored = sessionStorage.getItem("student");
    if (!stored) {
      navigate("/login");
      return;
    }
    const s = JSON.parse(stored) as Student;
    setStudent(s);

    const fetchCourses = async () => {
      try {
        const coursesData = await getStudentCourses(s.id);
        setCourses(coursesData || []);
      } catch (error) {
        console.error(error);
        setCourses([]);
      } finally {
        setLoading(false);
      }
    };
    fetchCourses();
  }, [navigate]);

  const handleLogout = () => {
    sessionStorage.removeItem("student");
    navigate("/login");
  };

  if (!student) return null;

  return (
    <div className="grid grid-cols-[260px_1fr] min-h-screen bg-background">
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

          {loading ? (
            <div className="px-2 py-6 text-center">
              <p className="text-xs text-muted-foreground/60">Yükleniyor...</p>
            </div>
          ) : courses.length === 0 ? (
            <div className="px-2 py-6 text-center">
              <BookOpen className="h-5 w-5 text-muted-foreground/40 mx-auto mb-2" />
              <p className="text-xs text-muted-foreground/60">Kayıtlı ders bulunamadı</p>
            </div>
          ) : (
            courses.map((course) => (
              <button
                key={course.id}
                onClick={() => navigate(`/courses/${course.id}/assignments`)}
                className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors duration-150"
              >
                <BookOpen className="h-4 w-4 text-primary shrink-0" />
                <span className="truncate">{course.name}</span>
              </button>
            ))
          )}
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
      <main className="flex flex-col p-6 lg:p-8">
        <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Derslerim</h1>
        <p className="text-sm text-muted-foreground mb-6">Bir ders seçerek ödevlerinizi görüntüleyebilirsiniz.</p>

        {!loading && courses.length > 0 && (
          <div className="grid gap-3 max-w-2xl">
            {courses.map((course) => (
              <button
                key={course.id}
                onClick={() => navigate(`/courses/${course.id}/assignments`)}
                className="flex items-center gap-4 p-4 rounded-xl border border-border bg-card hover:shadow-md transition-all text-left"
              >
                <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <BookOpen className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <p className="font-medium text-foreground">{course.name}</p>
                  <p className="text-xs text-muted-foreground">{course.code}</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </main>
    </div>
  );
};

export default Courses;
