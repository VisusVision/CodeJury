ALTER TABLE public.students
  ADD COLUMN IF NOT EXISTS class_year SMALLINT;

ALTER TABLE public.courses
  ADD COLUMN IF NOT EXISTS class_year SMALLINT;
