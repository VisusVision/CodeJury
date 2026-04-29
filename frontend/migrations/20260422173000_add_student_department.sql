-- Add department support to students and switch uniqueness to student_no + tc_no
ALTER TABLE public.students
  ADD COLUMN IF NOT EXISTS department_id UUID NULL REFERENCES public.departments(id) ON DELETE SET NULL;

ALTER TABLE public.students
  DROP CONSTRAINT IF EXISTS students_student_no_key;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'students_student_no_tc_no_key'
      AND conrelid = 'public.students'::regclass
  ) THEN
    ALTER TABLE public.students
      ADD CONSTRAINT students_student_no_tc_no_key UNIQUE (student_no, tc_no);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_students_department_id
  ON public.students(department_id);
