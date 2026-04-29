import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import WorkspacePage from "@/components/dashboard/WorkspacePage";
import { getAssignment, getCourse } from "@/services/api";

interface Student {
  id: string;
  first_name: string;
  last_name: string;
  student_no: string;
}

const AssignmentWorkspace = () => {
  const { courseId, assignmentId } = useParams<{ courseId: string; assignmentId: string }>();
  const [student, setStudent] = useState<Student | null>(null);
  const [courseName, setCourseName] = useState("");
  const [assignmentName, setAssignmentName] = useState("");
  const [assignmentDueDate, setAssignmentDueDate] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    const stored = sessionStorage.getItem("student");
    if (!stored) {
      navigate("/login");
      return;
    }
    setStudent(JSON.parse(stored));

    const fetchData = async () => {
      try {
        const [course, assignment] = await Promise.all([getCourse(courseId!), getAssignment(assignmentId!)]);
        setCourseName(course?.name || "");
        setAssignmentName(assignment?.name || "");
        setAssignmentDueDate(assignment?.due_date || null);
      } catch (error) {
        console.error(error);
        setCourseName("");
        setAssignmentName("");
        setAssignmentDueDate(null);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [courseId, assignmentId, navigate]);

  if (!student || loading) return null;

  const studentFullName = `${student.first_name} ${student.last_name}`;

  return (
    <WorkspacePage
      sidebarTitle={studentFullName}
      sidebarSubtitle={courseName}
      headerTitle={assignmentName}
      assignmentId={assignmentId!}
      studentNo={student.student_no}
      assignmentDueDate={assignmentDueDate}
      onBack={() => navigate(`/courses/${courseId}/assignments`)}
    />
  );
};

export default AssignmentWorkspace;
