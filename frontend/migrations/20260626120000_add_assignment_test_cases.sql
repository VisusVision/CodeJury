CREATE TABLE IF NOT EXISTS public.assignment_test_cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  stdin TEXT NOT NULL DEFAULT '',
  expected_stdout TEXT NOT NULL DEFAULT '',
  expected_exit_code INTEGER NOT NULL DEFAULT 0,
  visibility TEXT NOT NULL DEFAULT 'hidden' CHECK (visibility IN ('public', 'hidden')),
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'ai')),
  display_order INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_assignment_test_cases_assignment_id
  ON public.assignment_test_cases(assignment_id, display_order ASC, created_at ASC);
