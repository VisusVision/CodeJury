import { useCallback, useState } from "react";
import { Check, Loader2, RefreshCw, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { fetchAssignmentSuggestions, type AssignmentSuggestion } from "@/services/api";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface AssignmentAssistantPanelProps {
  onApplyDraft: (title: string, description: string) => void;
  className?: string;
}

export default function AssignmentAssistantPanel({ onApplyDraft, className }: AssignmentAssistantPanelProps) {
  const [courseHint, setCourseHint] = useState("");
  const [loading, setLoading] = useState(false);
  const [suggestions, setSuggestions] = useState<AssignmentSuggestion[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const loadSuggestions = useCallback(async () => {
    setLoading(true);
    setSelectedId(null);
    try {
      const { suggestions: list } = await fetchAssignmentSuggestions(courseHint.trim() || undefined, 5);
      setSuggestions(list);
      if (!list.length) {
        toast.message("Öneri gelmedi", { description: "Tekrar deneyin veya bağlam alanını doldurun." });
      }
    } catch (e) {
      setSuggestions([]);
      toast.error(e instanceof Error ? e.message : "Öneriler alınamadı");
    } finally {
      setLoading(false);
    }
  }, [courseHint]);

  const apply = useCallback(
    (s: AssignmentSuggestion) => {
      onApplyDraft(s.title, s.description);
      setSelectedId(s.id);
      toast.success("Başlık ve açıklama taslağa yazıldı", {
        description: "Soldan düzenleyip ödev ekleyebilirsiniz.",
      });
    },
    [onApplyDraft],
  );

  return (
    <div
      className={cn(
        "flex flex-col rounded-xl border border-border bg-card shadow-card overflow-hidden min-h-[440px] max-h-[min(80vh,720px)]",
        className,
      )}
    >
      <div className="flex items-center gap-2 px-4 py-3 border-b border-border bg-muted/30">
        <div className="h-8 w-8 rounded-lg bg-primary/15 flex items-center justify-center shrink-0">
          <Sparkles className="h-4 w-4 text-primary" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold text-foreground">Ödev konusu önerileri</h3>
          <p className="text-[11px] text-muted-foreground">
            Yapay zekâdan konu listesi alın; beğendiğinizi tek tıkla forma aktarın
          </p>
        </div>
      </div>

      <div className="p-3 space-y-2 border-b border-border">
        <label className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          Ders / bağlam (isteğe bağlı)
        </label>
        <input
          type="text"
          value={courseHint}
          onChange={(e) => setCourseHint(e.target.value)}
          placeholder="Örn. BLM201 Veri Yapıları, 2. sınıf, Python…"
          className="w-full px-2.5 py-1.5 rounded-lg border border-input bg-background text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <Button type="button" size="sm" className="w-full" onClick={() => void loadSuggestions()} disabled={loading}>
          {loading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              <span className="ml-2">Öneriler hazırlanıyor…</span>
            </>
          ) : (
            <>
              <RefreshCw className="h-4 w-4" />
              <span className="ml-2">Önerileri getir</span>
            </>
          )}
        </Button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
        {suggestions.length === 0 && !loading && (
          <p className="text-xs text-muted-foreground text-center py-8 px-2">
            Önce «Önerileri getir»e basın. Liste burada görünür; bir kartı seçince başlık ve açıklama soldaki forma yazılır.
          </p>
        )}
        {suggestions.map((s) => (
          <div
            key={s.id}
            className={cn(
              "rounded-lg border p-3 space-y-2 transition-colors",
              selectedId === s.id ? "border-primary bg-primary/5" : "border-border bg-background/50",
            )}
          >
            <div className="space-y-1">
              <p className="text-sm font-semibold text-foreground leading-snug">{s.title}</p>
              {s.summary ? (
                <p className="text-xs text-muted-foreground leading-relaxed">{s.summary}</p>
              ) : null}
            </div>
            <div className="text-xs text-foreground/90 leading-relaxed whitespace-pre-wrap border-t border-border/60 pt-2">
              {s.description}
            </div>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              className="w-full"
              onClick={() => apply(s)}
              disabled={loading}
            >
              {selectedId === s.id ? (
                <>
                  <Check className="h-4 w-4 text-emerald-600" />
                  <span className="ml-2">Taslakta</span>
                </>
              ) : (
                "Bu öneriyi kullan"
              )}
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}
