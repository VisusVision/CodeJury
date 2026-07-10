import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import WorkspacePage from "@/components/dashboard/WorkspacePage";
import { getAssignment, getCourse } from "@/services/api";
import { useAuth } from "../auth/AuthContext";

interface Student {
  id: string;
  first_name: string;
  last_name: string;
  student_no: string;
}

const AssignmentWorkspace = () => {
  const { courseId, assignmentId } = useParams<{ courseId: string; assignmentId: string }>();
  const { status, role, user } = useAuth();
  const [student, setStudent] = useState<Student | null>(null);
  const [courseName, setCourseName] = useState("");
  const [assignmentName, setAssignmentName] = useState("");
  const [assignmentDescription, setAssignmentDescription] = useState<string | null>(null);
  const [assignmentDueDate, setAssignmentDueDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
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
    });
  }, [status, role, user, navigate]);

  useEffect(() => {
    if (status !== "authenticated" || role !== "student") return;

    const fetchData = async () => {
      if (!courseId || !assignmentId) {
        navigate("/courses", { replace: true });
        return;
      }
      try {
        const [course, assignment] = await Promise.all([getCourse(courseId), getAssignment(assignmentId)]);
        if (assignment.course_id && assignment.course_id !== courseId) {
          navigate(`/courses/${assignment.course_id}/assignments/${assignment.id}`, { replace: true });
          return;
        }
        setErrorMessage(null);
        setCourseName(course?.name || "");
        setAssignmentName(assignment?.name || "");
        setAssignmentDescription(assignment?.description || null);
        setAssignmentDueDate(assignment?.due_date || null);
      } catch (error) {
        console.error(error);
        setErrorMessage("Ödev bilgileri yüklenemedi.");
        setCourseName("");
        setAssignmentName("");
        setAssignmentDescription(null);
        setAssignmentDueDate(null);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [courseId, assignmentId, navigate, status, role]);

  if (status === "loading" || !student || loading) return null;

  if (errorMessage) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6">
        <div className="max-w-md rounded-lg border border-destructive/30 bg-card p-5 text-center shadow-sm">
          <p className="text-sm text-destructive">{errorMessage}</p>
          <button
            type="button"
            onClick={() => navigate(courseId ? `/courses/${courseId}/assignments` : "/courses")}
            className="mt-4 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
          >
            Ödevlere dön
          </button>
        </div>
      </div>
    );
  }

  const studentFullName = `${student.first_name} ${student.last_name}`;

  return (
    <WorkspacePage
      sidebarTitle={studentFullName}
      sidebarSubtitle={courseName}
      headerTitle={assignmentName}
      assignmentDescription={assignmentDescription}
      assignmentId={assignmentId || ""}
      studentNo={student.student_no}
      assignmentDueDate={assignmentDueDate}
      onBack={() => navigate(`/courses/${courseId}/assignments`)}
    />
  );
};

export default AssignmentWorkspace;
