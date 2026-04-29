-- Add question bank and assignment-question mapping
CREATE TABLE IF NOT EXISTS public.question_bank (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content TEXT NOT NULL,
  labels JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_by UUID NULL REFERENCES public.teachers(id) ON DELETE SET NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.question_bank
  ADD COLUMN IF NOT EXISTS labels JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE public.question_bank
  ADD COLUMN IF NOT EXISTS created_by UUID NULL REFERENCES public.teachers(id) ON DELETE SET NULL;

ALTER TABLE public.question_bank
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE TABLE IF NOT EXISTS public.assignment_questions (
  assignment_id UUID NOT NULL REFERENCES public.assignments(id) ON DELETE CASCADE,
  question_id UUID NOT NULL REFERENCES public.question_bank(id) ON DELETE CASCADE,
  display_order INTEGER NOT NULL DEFAULT 1,
  selected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (assignment_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_assignment_questions_assignment_id
  ON public.assignment_questions(assignment_id, display_order ASC, selected_at DESC);

CREATE INDEX IF NOT EXISTS idx_assignment_questions_question_id
  ON public.assignment_questions(question_id);

CREATE INDEX IF NOT EXISTS idx_question_bank_created_at
  ON public.question_bank(created_at DESC);
