import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes, Navigate } from "react-router-dom";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { LanguageProvider } from "@/i18n/LanguageContext";
import Login from "./pages/Login.tsx";
import Courses from "./pages/Courses.tsx";
import Assignments from "./pages/Assignments.tsx";
import AssignmentWorkspace from "./pages/AssignmentWorkspace.tsx";
import FacultyDashboard from "./pages/faculty/FacultyDashboard.tsx";
import RubricEditor from "./pages/faculty/RubricEditor.tsx";
import NotFound from "./pages/NotFound.tsx";

const queryClient = new QueryClient();

const App = () => (
  <LanguageProvider>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <Toaster />
        <Sonner />
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/login" element={<Login />} />
            <Route path="/courses" element={<Courses />} />
            <Route path="/courses/:courseId/assignments" element={<Assignments />} />
            <Route path="/courses/:courseId/assignments/:assignmentId" element={<AssignmentWorkspace />} />
            <Route path="/faculty/dashboard" element={<FacultyDashboard />} />
            <Route path="/faculty/rubric/:assignmentId" element={<RubricEditor />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </TooltipProvider>
    </QueryClientProvider>
  </LanguageProvider>
);

export default App;
