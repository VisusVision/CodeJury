import { useEffect, useState } from "react";
import { Sparkles, Check, Trash2, Plus, Loader2, X, Search } from "lucide-react";
import { toast } from "sonner";
import {
  getRubricByAssignment,
  suggestRubric,
  upsertRubric,
  getQuestions,
  createQuestion,
  deleteQuestion,
  getAssignmentQuestions,
  updateAssignmentQuestions,
  QuestionItem,
} from "@/services/api";
import { useTranslation } from "@/i18n/LanguageContext";

interface RubricCriterion {
  name: string;
  description: string;
  max_score: number;
}

interface Assignment {
  id: string;
  name: string;
  description: string | null;
}

interface Rubric {
  id: string;
  criteria: RubricCriterion[];
  status: string;
}

interface RubricModalProps {
  assignment: Assignment;
  teacherId: string;
  open: boolean;
  onClose: () => void;
}

type TabType = "rubric" | "questions";

const RUBRIC_MIN_CRITERIA = 10;
const RUBRIC_MAX_CRITERIA = 20;
const RUBRIC_MIN_POINTS = 5;
const RUBRIC_MAX_POINTS = 10;
const RUBRIC_TOTAL_POINTS = 100;

const getRubricValidationMessage = (criteria: RubricCriterion[], t: any = (key: string) => key) => {
  if (criteria.length < RUBRIC_MIN_CRITERIA || criteria.length > RUBRIC_MAX_CRITERIA) {
    return t("faculty.rubricModal.validationMinMax");
  }
  if (criteria.some((criterion) => !criterion.name.trim())) {
    return t("faculty.rubricModal.validationEmptyName");
  }
  if (
    criteria.some((criterion) => {
      const score = Number(criterion.max_score);
      return !Number.isInteger(score) || score < RUBRIC_MIN_POINTS || score > RUBRIC_MAX_POINTS;
    })
  ) {
    return t("faculty.rubricModal.validationScoreRange");
  }
  const total = criteria.reduce((sum, criterion) => sum + (Number(criterion.max_score) || 0), 0);
  if (total !== RUBRIC_TOTAL_POINTS) {
    return t("faculty.rubricModal.validationTotalPoints");
  }
  return null;
};

const RubricModal = ({ assignment, teacherId, open, onClose }: RubricModalProps) => {
  const { t, language } = useTranslation();
  const [activeTab, setActiveTab] = useState<TabType>("rubric");
  
  // Rubric states
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [criteria, setCriteria] = useState<RubricCriterion[]>([]);
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState(false);

  // Questions states
  const [questions, setQuestions] = useState<QuestionItem[]>([]);
  const [selectedQuestionIds, setSelectedQuestionIds] = useState<Set<string>>(new Set());
  const [questionSearch, setQuestionSearch] = useState("");
  const [newQuestionContent, setNewQuestionContent] = useState("");
  const [newQuestionColor, setNewQuestionColor] = useState<"blue" | "green" | "pink" | "yellow">("blue");
  const [questionsLoading, setQuestionsLoading] = useState(false);
  const [questionCreateLoading, setQuestionCreateLoading] = useState(false);
  const [questionSaveLoading, setQuestionSaveLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const aid = String(assignment?.id ?? "").trim();
    if (!aid) {
      toast.error(t("faculty.rubricModal.loadError") || "Geçersiz ödev kimliği");
      return;
    }

    const loadData = async () => {
      setLoading(true);
      setQuestionsLoading(true);
      try {
        // Load rubric
        const rubricData = await getRubricByAssignment(assignment.id);
        if (rubricData) {
          setRubric(rubricData as Rubric);
          const loadedCriteria = (rubricData.criteria as RubricCriterion[]) || [];
          setCriteria(loadedCriteria);
        } else {
          setRubric(null);
          setCriteria([]);
        }

        // Load all questions
        const allQuestions = await getQuestions();
        setQuestions(allQuestions);

        // Load assignment questions
        const assignmentQuestions = await getAssignmentQuestions(assignment.id);
        const selectedIds = new Set(assignmentQuestions.map((q) => q.id));
        setSelectedQuestionIds(selectedIds);
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : t("faculty.rubricModal.loadError");
        toast.error(msg);
      } finally {
        setLoading(false);
        setQuestionsLoading(false);
      }
    };

    loadData();
  }, [assignment.id, open]);

  const requestAiSuggestion = async () => {
    setAiLoading(true);
    try {
      const data = await suggestRubric({
        assignment_title: assignment.name,
        assignment_description: assignment.description || "",
        report_language: language,
      });
      setCriteria(data.criteria || []);
      toast.success(t("faculty.rubricModal.aiSuccess") || (language === "tr" ? "AI Önerisi Alındı" : "AI Suggestion Received"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : t("common.error");
      toast.error(msg);
    } finally {
      setAiLoading(false);
    }
  };

  const updateCriterion = (index: number, field: keyof RubricCriterion, value: string | number) => {
    setCriteria((prev) =>
      prev.map((criterion, i) =>
        i === index ? { ...criterion, [field]: value } : criterion,
      ),
    );
  };

  const removeCriterion = (index: number) => {
    setCriteria(criteria.filter((_, i) => i !== index));
  };

  const addCriterion = () => {
    if (criteria.length >= RUBRIC_MAX_CRITERIA) {
      toast.error(`${language === "tr" ? "En fazla" : "Maximum"} ${RUBRIC_MAX_CRITERIA} ${t("faculty.rubricModal.item")} ${language === "tr" ? "eklenebilir" : "can be added"}.`);
      return;
    }
    setCriteria([...criteria, { name: "", description: "", max_score: RUBRIC_MIN_POINTS }]);
  };

  const saveRubric = async (status: "draft" | "approved") => {
    const validationMessage = getRubricValidationMessage(criteria, t);
    if (validationMessage) {
      toast.error(validationMessage);
      return;
    }

    try {
      const saved = await upsertRubric({
        assignment_id: assignment.id,
        criteria,
        status,
        created_by: teacherId,
      });
      setRubric(saved);
      toast.success(status === "approved" ? t("faculty.rubricModal.saveApproveSuccess") : t("faculty.rubricModal.saveDraftSuccess"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (language === "tr" ? "Kaydetme hatası" : "Save error");
      toast.error(msg);
    }
  };

  const handleCreateQuestion = async () => {
    if (!newQuestionContent.trim()) {
      toast.error(language === "tr" ? "Soru içeriği boş olamaz" : "Question content cannot be empty");
      return;
    }

    setQuestionCreateLoading(true);
    try {
      const newQuestion = await createQuestion({
        content: newQuestionContent,
        color: newQuestionColor,
      });
      setQuestions([...questions, newQuestion]);
      setNewQuestionContent("");
      setNewQuestionColor("blue");
      toast.success(t("faculty.rubricModal.questionCreated"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (language === "tr" ? "Soru oluşturulamadı" : "Question could not be created");
      toast.error(msg);
    } finally {
      setQuestionCreateLoading(false);
    }
  };

  const toggleQuestionSelection = (questionId: string) => {
    const newSelected = new Set(selectedQuestionIds);
    if (newSelected.has(questionId)) {
      newSelected.delete(questionId);
    } else {
      newSelected.add(questionId);
    }
    setSelectedQuestionIds(newSelected);
  };

  const removeSelectedQuestion = (questionId: string) => {
    const newSelected = new Set(selectedQuestionIds);
    newSelected.delete(questionId);
    setSelectedQuestionIds(newSelected);
  };

  const saveSelectedQuestions = async () => {
    setQuestionSaveLoading(true);
    try {
      await updateAssignmentQuestions({
        assignment_id: assignment.id,
        question_ids: Array.from(selectedQuestionIds),
      });
      toast.success(t("faculty.rubricModal.questionsSaved"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (language === "tr" ? "Sorular kaydedilemedi" : "Questions could not be saved");
      toast.error(msg);
    } finally {
      setQuestionSaveLoading(false);
    }
  };

  const handleDeleteQuestion = async (questionId: string) => {
    try {
      await deleteQuestion(questionId);
      setQuestions(questions.filter((q) => q.id !== questionId));
      removeSelectedQuestion(questionId);
      toast.success(t("faculty.rubricModal.questionDeleted"));
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (language === "tr" ? "Soru silinemedi" : "Question could not be deleted");
      toast.error(msg);
    }
  };

  const filteredQuestions = questions.filter((q) =>
    q.content.toLowerCase().includes(questionSearch.toLowerCase())
  );

  const selectedQuestions = questions.filter((q) => selectedQuestionIds.has(q.id));

  const colorClasses: Record<string, string> = {
    blue: "bg-blue-50 border-blue-200 text-blue-700 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-400",
    green: "bg-green-50 border-green-200 text-green-700 dark:bg-green-900/30 dark:border-green-800 dark:text-green-400",
    pink: "bg-pink-50 border-pink-200 text-pink-700 dark:bg-pink-900/30 dark:border-pink-800 dark:text-pink-400",
    yellow: "bg-yellow-50 border-yellow-200 text-yellow-700 dark:bg-yellow-900/30 dark:border-yellow-800 dark:text-yellow-400",
  };

  const colorSelectClasses: Record<string, string> = {
    blue: "bg-blue-100 border-blue-300 dark:bg-blue-900 dark:border-blue-700",
    green: "bg-green-100 border-green-300 dark:bg-green-900 dark:border-green-700",
    pink: "bg-pink-100 border-pink-300 dark:bg-pink-900 dark:border-pink-700",
    yellow: "bg-yellow-100 border-yellow-300 dark:bg-yellow-900 dark:border-yellow-700",
  };

  const borderSelectClasses: Record<string, string> = {
    blue: "border-blue-600 dark:border-blue-400",
    green: "border-green-600 dark:border-green-400",
    pink: "border-pink-600 dark:border-pink-400",
    yellow: "border-yellow-600 dark:border-yellow-400",
  };

  if (!open) return null;

  const totalScore = criteria.reduce((sum, c) => sum + (Number(c.max_score) || 0), 0);
  const validationMessage = getRubricValidationMessage(criteria, t);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-background border border-border rounded-2xl shadow-2xl w-full max-w-3xl h-[85vh] max-h-[85vh] flex flex-col mx-4">
        <div className="flex items-start justify-between gap-4 p-5 border-b border-border shrink-0">
          <div className="space-y-1">
            <h2 className="text-lg font-bold text-foreground">{t("faculty.rubricModal.title")}</h2>
            <p className="text-xs text-muted-foreground">{assignment.name}</p>
          </div>
          <div className="flex items-center gap-3">
            {rubric && (
              <span
                className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                  rubric.status === "approved"
                    ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400"
                    : "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400"
                }`}
              >
                {rubric.status === "approved" ? t("faculty.evaluations.evaluated") : t("faculty.evaluations.notEvaluated")}
              </span>
            )}
            <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Tab selector */}
        <div className="flex border-b border-border shrink-0">
          <button
            type="button"
            onClick={() => setActiveTab("rubric")}
            className={`flex-1 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "rubric"
                ? "text-foreground border-primary"
                : "text-muted-foreground border-transparent hover:text-foreground"
            }`}
          >
            {t("faculty.rubricModal.rubricCriteria")}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab("questions")}
            className={`flex-1 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === "questions"
                ? "text-foreground border-primary"
                : "text-muted-foreground border-transparent hover:text-foreground"
            }`}
          >
            {t("faculty.rubricModal.questions")} ({selectedQuestions.length})
          </button>
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto">
          {activeTab === "rubric" && (
            <div className="p-5 space-y-4">
              {loading ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">{t("common.loading")}</div>
              ) : (
                <>
                  {assignment.description && (
                    <p className="text-xs text-muted-foreground bg-muted/50 p-3 rounded-lg">{assignment.description}</p>
                  )}

                  <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 p-3">
                    <div className="space-y-1">
                      <p className="text-xs font-medium text-foreground">
                        {language === "tr" ? "AI Rubrik Kapsamı" : "AI rubric scope"}
                      </p>
                      <p className="text-[11px] text-muted-foreground">
                        {language === "tr"
                          ? "Kriter sayısı ödev zorluğuna göre otomatik belirlenir. Her kriter 5-10 puan, toplam 100."
                          : "Criterion count is inferred from assignment difficulty. Each criterion is 5-10 points, total 100."}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={requestAiSuggestion}
                      disabled={aiLoading}
                      className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-primary to-primary/80 text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
                    >
                      {aiLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                      {aiLoading ? t("faculty.rubricModal.aiThinking") : t("faculty.rubricModal.aiSuggestionBtn")}
                    </button>
                  </div>

                  <div className="space-y-2.5">
                    {criteria.map((c, i) => (
                      <div key={i} className="p-2.5 rounded-xl border border-border bg-card space-y-1.5">
                        <div className="flex items-start justify-between gap-1.5">
                          <div className="flex-1 space-y-1.5">
                            <input
                              type="text"
                              value={c.name}
                              onChange={(e) => updateCriterion(i, "name", e.target.value)}
                              placeholder={t("faculty.rubricModal.placeholderName")}
                              className="w-full px-3 py-1 rounded-lg border border-input bg-background text-foreground text-sm font-medium focus:outline-none focus:ring-2 focus:ring-ring"
                            />
                            <textarea
                              value={c.description}
                              onChange={(e) => updateCriterion(i, "description", e.target.value)}
                              placeholder={t("faculty.rubricModal.placeholderDesc")}
                              rows={2}
                              className="w-full px-3 py-1 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                            />
                          </div>
                          <div className="flex flex-col items-end gap-1 shrink-0 pt-0.5">
                            <div className="flex items-center gap-1">
                              <input
                                type="number"
                                value={c.max_score}
                                onChange={(e) => updateCriterion(i, "max_score", parseInt(e.target.value, 10) || 0)}
                                className="w-14 px-2 py-0.5 rounded-lg border border-input bg-background text-foreground text-sm text-center focus:outline-none focus:ring-2 focus:ring-ring"
                                min={RUBRIC_MIN_POINTS}
                                max={RUBRIC_MAX_POINTS}
                              />
                              <span className="text-xs text-muted-foreground">pt</span>
                            </div>
                            <button
                              type="button"
                              onClick={() => removeCriterion(i)}
                              className="text-muted-foreground hover:text-destructive transition-colors"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>

                  <button
                    type="button"
                    onClick={addCriterion}
                    disabled={criteria.length >= RUBRIC_MAX_CRITERIA}
                    className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-dashed border-border text-sm text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Plus className="h-4 w-4" /> {t("faculty.rubricModal.addCriterion")}
                  </button>
                </>
              )}
            </div>
          )}

          {activeTab === "questions" && (
            <div className="p-5 space-y-4">
              {questionsLoading ? (
                <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">{language === "tr" ? "Sorular yükleniyor..." : "Questions loading..."}</div>
              ) : (
                <>
                  {/* Create new question */}
                  <div className="p-3 rounded-lg border border-border bg-card space-y-2">
                    <p className="text-xs font-medium text-foreground">{t("faculty.rubricModal.newQuestionTitle")}</p>
                    <div className="flex items-center gap-2">
                      <textarea
                        value={newQuestionContent}
                        onChange={(e) => setNewQuestionContent(e.target.value)}
                        placeholder={t("faculty.rubricModal.placeholderQuestion")}
                        rows={2}
                        className="flex-1 px-3 py-0 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                      />
                      <div className="flex items-center gap-1.5 flex-shrink-0">
                        {(["blue", "green", "pink", "yellow"] as const).map((color) => (
                          <button
                            key={color}
                            type="button"
                            onClick={() => setNewQuestionColor(color)}
                            className={`w-7 h-7 rounded-full border-2 transition-all ${
                              newQuestionColor === color
                                ? `${colorSelectClasses[color]} border-4 ${borderSelectClasses[color]}`
                                : `${colorSelectClasses[color]} border-2 border-gray-300 dark:border-gray-600`
                            }`}
                            title={color}
                          />
                        ))}
                      </div>
                      <button
                        type="button"
                        onClick={handleCreateQuestion}
                        disabled={questionCreateLoading}
                        className="px-3 py-1 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-1 flex-shrink-0"
                      >
                        {questionCreateLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
                        {t("common.add") || "Ekle"}
                      </button>
                    </div>
                  </div>

                  {/* Search questions */}
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <input
                      type="text"
                      value={questionSearch}
                      onChange={(e) => setQuestionSearch(e.target.value)}
                      placeholder={t("faculty.rubricModal.searchQuestions")}
                      className="w-full pl-9 pr-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>

                  {/* Selected questions */}
                  {selectedQuestions.length > 0 && (
                    <div className="p-3 rounded-lg border border-green-200 bg-green-50 dark:border-green-800 dark:bg-green-900/20 space-y-2">
                      <p className="text-xs font-medium text-green-700 dark:text-green-400">
                        {t("faculty.rubricModal.selectedQuestions")} ({selectedQuestions.length})
                      </p>
                      <div className="space-y-1">
                        {selectedQuestions.map((q) => (
                          <div key={q.id} className={`flex items-center justify-between p-2 rounded border ${colorClasses[q.color]}`}>
                            <p className="text-xs flex-1">{q.content}</p>
                            <button
                              type="button"
                              onClick={() => removeSelectedQuestion(q.id)}
                              className="ml-2 text-muted-foreground hover:text-destructive transition-colors"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* All questions */}
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-muted-foreground">{t("faculty.rubricModal.allQuestions")}</p>
                    <div className="space-y-1.5 max-h-60 overflow-y-auto">
                      {filteredQuestions.length === 0 ? (
                        <p className="text-xs text-muted-foreground py-3 text-center">{t("faculty.rubricModal.noQuestionsFound")}</p>
                      ) : (
                        filteredQuestions.map((q) => (
                          <div
                            key={q.id}
                            className={`flex items-center gap-2 p-2 rounded border cursor-pointer transition-all ${
                              selectedQuestionIds.has(q.id)
                                ? colorClasses[q.color]
                                : "border-border bg-card hover:bg-muted/50"
                            }`}
                          >
                            <input
                              type="checkbox"
                              checked={selectedQuestionIds.has(q.id)}
                              onChange={() => toggleQuestionSelection(q.id)}
                              className="h-4 w-4 rounded cursor-pointer"
                            />
                            <p className="text-xs flex-1">{q.content}</p>
                            <button
                              type="button"
                              onClick={() => handleDeleteQuestion(q.id)}
                              className="text-muted-foreground hover:text-destructive transition-colors"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        {activeTab === "rubric" && !loading && criteria.length > 0 && (
          <div className="flex items-center justify-between p-4 border-t border-border shrink-0">
            <div>
              <p className={`text-sm font-medium ${validationMessage ? "text-destructive" : "text-foreground"}`}>
                {language === "tr" ? "Toplam" : "Total"}: {totalScore} {language === "tr" ? "puan" : "pts"}
              </p>
              <p className="text-xs text-muted-foreground">{criteria.length} {t("faculty.rubricModal.item")}</p>
              {validationMessage && <p className="text-xs text-destructive">{validationMessage}</p>}
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => saveRubric("draft")}
                className="px-3 py-1.5 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
              >
                {t("faculty.rubricModal.saveDraft")}
              </button>
              <button
                type="button"
                onClick={() => saveRubric("approved")}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-700 transition-colors"
              >
                <Check className="h-4 w-4" /> {t("faculty.rubricModal.approve")}
              </button>
            </div>
          </div>
        )}

        {activeTab === "questions" && !questionsLoading && (
          <div className="flex justify-end gap-2 p-4 border-t border-border shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
            >
              {t("common.cancel")}
            </button>
            <button
              type="button"
              onClick={saveSelectedQuestions}
              disabled={questionSaveLoading}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50"
            >
              {questionSaveLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
              {t("faculty.rubricModal.saveQuestions")}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default RubricModal;
