-- Remove deprecated labels column from question bank
ALTER TABLE public.question_bank
  DROP COLUMN IF EXISTS labels;
