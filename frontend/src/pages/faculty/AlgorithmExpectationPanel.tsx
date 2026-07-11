import { useEffect, useState } from "react";
import { Loader2, X, BarChart3 } from "lucide-react";
import { getAlgorithmExpectation, type ApiAlgorithmExpectation } from "@/services/api";

interface AssignmentRef {
  id: string;
  name: string;
}

interface AlgorithmExpectationPanelProps {
  assignment: AssignmentRef;
  open: boolean;
  onClose: () => void;
}

const SOURCE_LABELS: Record<ApiAlgorithmExpectation["source"], string> = {
  llm_verified: "LLM doğrulamalı",
  deterministic_fallback: "Deterministik yedek",
  unknown: "Bilinmiyor",
};

const VERIFICATION_LABELS: Record<ApiAlgorithmExpectation["verificationStatus"], string> = {
  verified: "Doğrulandı",
  fallback: "Yedek mod",
  unknown: "Bilinmiyor",
};

function ReadOnlyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 px-3 py-2.5">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <p className="mt-1 text-sm text-foreground leading-relaxed">{value || "—"}</p>
    </div>
  );
}

const AlgorithmExpectationPanel = ({ assignment, open, onClose }: AlgorithmExpectationPanelProps) => {
  const [loading, setLoading] = useState(false);
  const [expectation, setExpectation] = useState<ApiAlgorithmExpectation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      setExpectation(null);
      setError(null);
      setLoading(false);
      return;
    }

    let cancelled = false;
    const load = async () => {
      setLoading(true);
      setError(null);
      setExpectation(null);
      try {
        const data = await getAlgorithmExpectation(assignment.id);
        if (!cancelled) {
          setExpectation(data);
        }
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : "Beklenti yüklenemedi.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [assignment.id, open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl bg-card shadow-card">
        <div className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="rounded-md bg-muted p-2">
              <BarChart3 className="h-4 w-4 text-foreground" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-foreground">Algoritma Beklentisi</h2>
              <p className="text-xs text-muted-foreground">{assignment.name} — salt okunur</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Kapat"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-auto px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Beklenti yükleniyor...
            </div>
          ) : error ? (
            <div className="rounded-xl border border-border bg-muted/30 px-4 py-6 text-center text-sm text-muted-foreground">
              {error}
            </div>
          ) : expectation ? (
            <div className="space-y-3">
              <ReadOnlyRow label="Beklenen Karmaşıklık" value={expectation.expectedComplexity} />
              <ReadOnlyRow label="Beklenen Yaklaşım" value={expectation.expectedApproach} />
              <ReadOnlyRow label="Algoritma Aileleri" value={expectation.algorithmFamilies.join(", ")} />
              <div className="grid gap-3 sm:grid-cols-2">
                <ReadOnlyRow label="Kaynak" value={SOURCE_LABELS[expectation.source]} />
                <ReadOnlyRow label="Doğrulama Durumu" value={VERIFICATION_LABELS[expectation.verificationStatus]} />
                <ReadOnlyRow label="Güven" value={`%${Math.round(expectation.confidence * 100)}`} />
                <ReadOnlyRow label="Sürüm" value={String(expectation.version)} />
              </div>
              <div className="grid gap-3 sm:grid-cols-2">
                <ReadOnlyRow label="Çıkarıcı Sağlayıcı" value={expectation.extractorProvider} />
                <ReadOnlyRow label="Çıkarıcı Model" value={expectation.extractorModel} />
                <ReadOnlyRow label="Doğrulayıcı Sağlayıcı" value={expectation.verifierProvider} />
                <ReadOnlyRow label="Doğrulayıcı Model" value={expectation.verifierModel} />
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
};

export default AlgorithmExpectationPanel;
