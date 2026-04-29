import { useEffect, useState } from "react";
import { Sparkles, Check, Trash2, Plus, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { getRubricByAssignment, suggestRubric, upsertRubric } from "@/services/api";

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

const RubricModal = ({ assignment, teacherId, open, onClose }: RubricModalProps) => {
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [criteria, setCriteria] = useState<RubricCriterion[]>([]);
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState(false);

  useEffect(() => {
    if (!open) return;
    const aid = String(assignment?.id ?? "").trim();
    if (!aid) {
      toast.error("Geçersiz ödev kimliği");
      return;
    }
    const fetchRubric = async () => {
      setLoading(true);
      try {
        const rubricData = await getRubricByAssignment(assignment.id);
        if (rubricData) {
          setRubric(rubricData as Rubric);
          setCriteria((rubricData.criteria as RubricCriterion[]) || []);
        } else {
          setRubric(null);
          setCriteria([]);
        }
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : "Rubrik getirilemedi";
        toast.error(msg);
      } finally {
        setLoading(false);
      }
    };
    fetchRubric();
  }, [assignment.id, open]);

  const requestAiSuggestion = async () => {
    setAiLoading(true);
    try {
      const data = await suggestRubric({
        assignment_title: assignment.name,
        assignment_description: assignment.description || "",
      });
      setCriteria(data.criteria || []);
      toast.success("AI rubrik önerisi oluşturuldu. Lütfen kontrol edip onaylayın.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "AI önerisi alınamadı";
      toast.error(msg);
    } finally {
      setAiLoading(false);
    }
  };

  const updateCriterion = (index: number, field: keyof RubricCriterion, value: string | number) => {
    const updated = [...criteria];
    (updated[index] as Record<string, unknown>)[field] = value;
    setCriteria(updated);
  };

  const removeCriterion = (index: number) => {
    setCriteria(criteria.filter((_, i) => i !== index));
  };

  const addCriterion = () => {
    setCriteria([...criteria, { name: "", description: "", max_score: 10 }]);
  };

  const saveRubric = async (status: "draft" | "approved") => {
    if (criteria.length === 0) {
      toast.error("En az bir kriter eklemelisiniz.");
      return;
    }
    const hasEmpty = criteria.some((c) => !c.name.trim());
    if (hasEmpty) {
      toast.error("Tüm kriterlerin adı doldurulmalıdır.");
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
      toast.success(status === "approved" ? "Rubrik onaylandı!" : "Rubrik taslak olarak kaydedildi.");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Kaydetme hatası";
      toast.error(msg);
    }
  };

  if (!open) return null;

  const totalScore = criteria.reduce((sum, c) => sum + (Number(c.max_score) || 0), 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />

      <div className="relative bg-background border border-border rounded-2xl shadow-2xl w-full max-w-2xl h-[85vh] max-h-[85vh] flex flex-col mx-4">
        <div className="flex items-start justify-between gap-4 p-5 border-b border-border shrink-0">
          <div className="space-y-1">
            <h2 className="text-lg font-bold text-foreground">Rubrik Düzenleyici</h2>
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
                {rubric.status === "approved" ? "Onaylandı" : "Taslak"}
              </span>
            )}
            <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
              <X className="h-5 w-5" />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground text-sm">Yükleniyor...</div>
          ) : (
            <>
              {assignment.description && (
                <p className="text-xs text-muted-foreground bg-muted/50 p-3 rounded-lg">{assignment.description}</p>
              )}

              <button
                type="button"
                onClick={requestAiSuggestion}
                disabled={aiLoading}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-gradient-to-r from-primary to-primary/80 text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
              >
                {aiLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
                {aiLoading ? "AI düşünüyor..." : "AI Rubrik Önerisi Al"}
              </button>

              <div className="space-y-2.5">
                {criteria.map((c, i) => (
                  <div key={i} className="p-2.5 rounded-xl border border-border bg-card space-y-1.5">
                    <div className="flex items-start justify-between gap-1.5">
                      <div className="flex-1 space-y-1.5">
                        <input
                          type="text"
                          value={c.name}
                          onChange={(e) => updateCriterion(i, "name", e.target.value)}
                          placeholder="Kriter adı"
                          className="w-full px-3 py-1 rounded-lg border border-input bg-background text-foreground text-sm font-medium focus:outline-none focus:ring-2 focus:ring-ring"
                        />
                        <textarea
                          value={c.description}
                          onChange={(e) => updateCriterion(i, "description", e.target.value)}
                          placeholder="Açıklama"
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
                            min={0}
                          />
                          <span className="text-xs text-muted-foreground">pt</span>
                        </div>
                        <button type="button" onClick={() => removeCriterion(i)} className="text-muted-foreground hover:text-destructive transition-colors">
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
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg border border-dashed border-border text-sm text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors"
              >
                <Plus className="h-4 w-4" /> Kriter Ekle
              </button>
            </>
          )}
        </div>

        {!loading && criteria.length > 0 && (
          <div className="flex items-center justify-between p-4 border-t border-border shrink-0">
            <div>
              <p className="text-sm font-medium text-foreground">Toplam: {totalScore} puan</p>
              <p className="text-xs text-muted-foreground">{criteria.length} kriter</p>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => saveRubric("draft")}
                className="px-3 py-1.5 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
              >
                Taslak Kaydet
              </button>
              <button
                type="button"
                onClick={() => saveRubric("approved")}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-700 transition-colors"
              >
                <Check className="h-4 w-4" /> Onayla
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default RubricModal;
