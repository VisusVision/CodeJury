-- Add color to question bank for pastel-coded question labels
ALTER TABLE public.question_bank
  ADD COLUMN IF NOT EXISTS color TEXT NOT NULL DEFAULT 'blue';
