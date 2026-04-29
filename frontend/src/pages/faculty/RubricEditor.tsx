import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Sparkles, Check, Pencil, Trash2, Plus, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { getAssignment, getRubricByAssignment, suggestRubric, upsertRubric } from "@/services/api";

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

const RubricEditor = () => {
  const { assignmentId } = useParams<{ assignmentId: string }>();
  const navigate = useNavigate();
  const [assignment, setAssignment] = useState<Assignment | null>(null);
  const [rubric, setRubric] = useState<Rubric | null>(null);
  const [criteria, setCriteria] = useState<RubricCriterion[]>([]);
  const [loading, setLoading] = useState(true);
  const [aiLoading, setAiLoading] = useState(false);
  const [teacherId, setTeacherId] = useState<string | null>(null);

  useEffect(() => {
    const init = async () => {
      try {
        const teacherRaw = sessionStorage.getItem("teacher");
        if (!teacherRaw) {
          navigate("/login");
          return;
        }
        const teacher = JSON.parse(teacherRaw) as { id: string };
        setTeacherId(teacher.id);

        if (!assignmentId) {
          navigate("/faculty/dashboard");
          return;
        }

        const [assignData, rubricData] = await Promise.all([
          getAssignment(assignmentId),
          getRubricByAssignment(assignmentId),
        ]);

        setAssignment(assignData as Assignment);
        if (rubricData) {
          setRubric(rubricData as any);
          setCriteria((rubricData.criteria as any) || []);
        }
      } catch (err: any) {
        toast.error(err.message || "Rubrik verileri yuklenemedi");
        navigate("/faculty/dashboard");
      } finally {
        setLoading(false);
      }
    };
    init();
  }, [assignmentId, navigate]);

  const requestAiSuggestion = async () => {
    if (!assignment) return;
    setAiLoading(true);
    try {
      const data = await suggestRubric({
        assignment_title: assignment.name,
        assignment_description: assignment.description || "",
      });
      setCriteria(data.criteria || []);
      toast.success("AI rubrik önerisi oluşturuldu. Lütfen kontrol edip onaylayın.");
    } catch (err: any) {
      toast.error(err.message || "AI önerisi alınamadı");
    } finally {
      setAiLoading(false);
    }
  };

  const updateCriterion = (index: number, field: keyof RubricCriterion, value: string | number) => {
    const updated = [...criteria];
    (updated[index] as any)[field] = value;
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

    if (!assignmentId) {
      toast.error("Geçersiz ödev");
      return;
    }

    try {
      const saved = await upsertRubric({
        assignment_id: assignmentId,
        criteria,
        status,
        created_by: teacherId,
      });
      setRubric(saved as any);
      toast.success(status === "approved" ? "Rubrik onaylandı!" : "Rubrik taslak olarak kaydedildi.");
    } catch (err: any) {
      toast.error(err.message || "Kaydetme hatası");
    }
  };

  if (loading) {
    return <div className="min-h-screen flex items-center justify-center text-muted-foreground">Yükleniyor...</div>;
  }

  const totalScore = criteria.reduce((sum, c) => sum + (Number(c.max_score) || 0), 0);

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto p-6 lg:p-8">
        <button
          onClick={() => navigate("/faculty/dashboard")}
          className="flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground mb-6 transition-colors"
        >
          <ArrowLeft className="h-4 w-4" /> Panele Dön
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Rubrik Düzenleyici</h1>
          <p className="text-sm text-muted-foreground">{assignment?.name}</p>
          {assignment?.description && (
            <p className="text-xs text-muted-foreground mt-1 bg-muted/50 p-3 rounded-lg">{assignment.description}</p>
          )}
        </div>

        {/* Status badge */}
        {rubric && (
          <div className="mb-4">
            <span className={`inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium ${
              rubric.status === "approved"
                ? "bg-green-100 text-green-800"
                : "bg-yellow-100 text-yellow-800"
            }`}>
              {rubric.status === "approved" ? "Onaylandı" : "Taslak"}
            </span>
          </div>
        )}

        {/* AI Suggestion button */}
        <button
          onClick={requestAiSuggestion}
          disabled={aiLoading}
          className="flex items-center gap-2 px-4 py-2.5 rounded-lg bg-gradient-to-r from-primary to-primary/80 text-primary-foreground text-sm font-medium hover:brightness-110 transition-all mb-6 disabled:opacity-50"
        >
          {aiLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
          {aiLoading ? "AI düşünüyor..." : "AI Rubrik Önerisi Al"}
        </button>

        {/* Criteria list */}
        <div className="space-y-3 mb-6">
          {criteria.map((c, i) => (
            <div key={i} className="p-4 rounded-xl border border-border bg-card space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div className="flex-1 space-y-2">
                  <input
                    type="text"
                    value={c.name}
                    onChange={(e) => updateCriterion(i, "name", e.target.value)}
                    placeholder="Kriter adı"
                    className="w-full px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm font-medium focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                  <textarea
                    value={c.description}
                    onChange={(e) => updateCriterion(i, "description", e.target.value)}
                    placeholder="Açıklama"
                    rows={2}
                    className="w-full px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                  />
                </div>
                <div className="flex flex-col items-end gap-2 shrink-0">
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      value={c.max_score}
                      onChange={(e) => updateCriterion(i, "max_score", parseInt(e.target.value) || 0)}
                      className="w-16 px-2 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm text-center focus:outline-none focus:ring-2 focus:ring-ring"
                      min={0}
                    />
                    <span className="text-xs text-muted-foreground">puan</span>
                  </div>
                  <button onClick={() => removeCriterion(i)} className="text-muted-foreground hover:text-destructive transition-colors">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        <button
          onClick={addCriterion}
          className="flex items-center gap-1 px-3 py-2 rounded-lg border border-dashed border-border text-sm text-muted-foreground hover:text-foreground hover:border-primary/50 transition-colors mb-6"
        >
          <Plus className="h-4 w-4" /> Kriter Ekle
        </button>

        {/* Summary and actions */}
        {criteria.length > 0 && (
          <div className="flex items-center justify-between p-4 rounded-xl border border-border bg-muted/30">
            <div>
              <p className="text-sm font-medium text-foreground">Toplam: {totalScore} puan</p>
              <p className="text-xs text-muted-foreground">{criteria.length} kriter</p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => saveRubric("draft")}
                className="px-4 py-2 rounded-lg border border-border text-sm font-medium text-foreground hover:bg-muted/50 transition-colors"
              >
                Taslak Kaydet
              </button>
              <button
                onClick={() => saveRubric("approved")}
                className="flex items-center gap-1 px-4 py-2 rounded-lg bg-green-600 text-white text-sm font-medium hover:bg-green-700 transition-colors"
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

export default RubricEditor;
