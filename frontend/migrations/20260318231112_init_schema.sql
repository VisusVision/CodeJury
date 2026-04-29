-- PostgreSQL migration
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Students
CREATE TABLE IF NOT EXISTS public.students (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_no TEXT NOT NULL UNIQUE,
  tc_no TEXT NOT NULL,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Courses
CREATE TABLE IF NOT EXISTS public.courses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  code TEXT NOT NULL UNIQUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Student-course enrollment
CREATE TABLE IF NOT EXISTS public.student_courses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_id UUID NOT NULL REFERENCES public.students(id) ON DELETE CASCADE,
  course_id UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
  UNIQUE(student_id, course_id)
);

-- Assignments
CREATE TABLE IF NOT EXISTS public.assignments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id UUID NOT NULL REFERENCES public.courses(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  due_date TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Student upload history
CREATE TABLE IF NOT EXISTS public.student_upload_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  student_first_name TEXT NOT NULL,
  student_last_name TEXT NOT NULL,
  student_no TEXT NOT NULL,
  uploaded_file_name TEXT NOT NULL,
  uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_student_upload_history_student_no
  ON public.student_upload_history(student_no);

CREATE INDEX IF NOT EXISTS idx_student_upload_history_uploaded_at
  ON public.student_upload_history(uploaded_at DESC);

-- Teachers
CREATE TABLE IF NOT EXISTS public.teachers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Departments
CREATE TABLE IF NOT EXISTS public.departments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  created_by UUID REFERENCES public.teachers(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.courses
  ADD COLUMN IF NOT EXISTS department_id UUID REFERENCES public.departments(id) ON DELETE SET NULL;

-- Rubrics
CREATE TABLE IF NOT EXISTS public.rubrics (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
  criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved')),
  created_by UUID REFERENCES public.teachers(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_courses_department_id
  ON public.courses(department_id);

CREATE INDEX IF NOT EXISTS idx_rubrics_assignment_id
  ON public.rubrics(assignment_id);

-- Row-level security
ALTER TABLE public.teachers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.departments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rubrics ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Authenticated users can read teachers" ON public.teachers
  FOR SELECT USING (true);

CREATE POLICY "Authenticated users can update teachers" ON public.teachers
  FOR UPDATE USING (true);

CREATE POLICY "Authenticated users can read departments" ON public.departments
  FOR SELECT USING (true);

CREATE POLICY "Teachers can insert departments" ON public.departments
  FOR INSERT WITH CHECK (
    true
  );

CREATE POLICY "Teachers can update departments" ON public.departments
  FOR UPDATE USING (
    true
  );

CREATE POLICY "Teachers can delete departments" ON public.departments
  FOR DELETE USING (
    true
  );

CREATE POLICY "Authenticated users can read courses" ON public.courses
  FOR SELECT USING (true);

CREATE POLICY "Teachers can insert courses" ON public.courses
  FOR INSERT WITH CHECK (
    true
  );

CREATE POLICY "Teachers can update courses" ON public.courses
  FOR UPDATE USING (
    true
  );

CREATE POLICY "Teachers can delete courses" ON public.courses
  FOR DELETE USING (
    true
  );

CREATE POLICY "Authenticated users can read assignments" ON public.assignments
  FOR SELECT USING (true);

CREATE POLICY "Teachers can insert assignments" ON public.assignments
  FOR INSERT WITH CHECK (
    true
  );

CREATE POLICY "Teachers can update assignments" ON public.assignments
  FOR UPDATE USING (
    true
  );

CREATE POLICY "Teachers can delete assignments" ON public.assignments
  FOR DELETE USING (
    true
  );

CREATE POLICY "Authenticated can read rubrics" ON public.rubrics
  FOR SELECT USING (true);

CREATE POLICY "Teachers can insert rubrics" ON public.rubrics
  FOR INSERT WITH CHECK (
    true
  );

CREATE POLICY "Teachers can update rubrics" ON public.rubrics
  FOR UPDATE USING (
    true
  );

CREATE POLICY "Teachers can delete rubrics" ON public.rubrics
  FOR DELETE USING (
    true
  );
