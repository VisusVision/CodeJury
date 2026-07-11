import { AlertTriangle, CheckCircle2, HelpCircle, TrendingDown, TrendingUp } from "lucide-react";
import type { ApiAlgorithmResult, ComplexityGap } from "@/services/api";
import { cn } from "@/lib/utils";

interface AlgorithmResultsProps {
  audience: "student" | "teacher";
  result: ApiAlgorithmResult;
  compact?: boolean;
}

const GAP_LABELS: Record<ComplexityGap, string> = {
  better_than_expected: "Beklentiden İyi",
  matches_expected: "Beklentiyle Uyumlu",
  worse_than_expected: "Beklentiden Kötü",
  unknown: "Belirsiz",
};

const GAP_TONES: Record<ComplexityGap, string> = {
  better_than_expected: "bg-success/10 text-success",
  matches_expected: "bg-primary/10 text-primary",
  worse_than_expected: "bg-destructive/10 text-destructive",
  unknown: "bg-muted text-muted-foreground",
};

const GAP_ICONS: Record<ComplexityGap, typeof CheckCircle2> = {
  better_than_expected: TrendingUp,
  matches_expected: CheckCircle2,
  worse_than_expected: TrendingDown,
  unknown: HelpCircle,
};

const SOURCE_LABELS: Record<string, string> = {
  llm_verified: "LLM doğrulamalı",
  deterministic_fallback: "Deterministik yedek",
  unknown: "Bilinmiyor",
};

function isLowConfidence(confidence: number | null | undefined): boolean {
  return confidence == null || confidence < 0.5;
}

function shouldSuppressPenalty(result: ApiAlgorithmResult): boolean {
  return result.complexityGap === "unknown" || isLowConfidence(result.actualConfidence);
}

function MetricRow({ label, value, compact }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className="min-w-0">
      <div className={cn("font-semibold uppercase text-muted-foreground", compact ? "text-[10px]" : "text-[11px]")}>
        {label}
      </div>
      <p className={cn("mt-0.5 text-foreground", compact ? "text-[11px]" : "text-xs")}>{value || "—"}</p>
    </div>
  );
}

const AlgorithmResults = ({ audience, result, compact }: AlgorithmResultsProps) => {
  const GapIcon = GAP_ICONS[result.complexityGap];
  const suppressPenalty = shouldSuppressPenalty(result);
  const detected = result.detectedAlgorithms.length ? result.detectedAlgorithms.join(", ") : "Tespit edilmedi";
  const structures = result.dataStructures.length ? result.dataStructures.join(", ") : "—";

  return (
    <div className={cn("space-y-3", compact ? "text-[11px]" : "text-xs")}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-semibold", GAP_TONES[result.complexityGap])}>
          <GapIcon className="h-3.5 w-3.5 shrink-0" />
          {GAP_LABELS[result.complexityGap]}
        </span>
        {result.gapSteps != null && result.complexityGap === "worse_than_expected" && !suppressPenalty ? (
          <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive">
            {result.gapSteps} kademe fark
          </span>
        ) : null}
      </div>

      {suppressPenalty ? (
        <div className="flex items-start gap-2 rounded-lg border border-border bg-muted/30 px-3 py-2 text-[11px] text-muted-foreground">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warning" />
          <span>Düşük güven veya belirsiz karmaşıklık — skor cezası uygulanmadı.</span>
        </div>
      ) : null}

      <div className={cn("grid gap-3", compact ? "sm:grid-cols-2" : "sm:grid-cols-2 lg:grid-cols-3")}>
        <MetricRow label="Tespit Edilen Algoritma" value={detected} compact={compact} />
        <MetricRow label="Veri Yapıları" value={structures} compact={compact} />
        <MetricRow label="Gerçek Karmaşıklık" value={result.timeComplexity} compact={compact} />
        <MetricRow label="Beklenen Karmaşıklık" value={result.expectedComplexity} compact={compact} />
        {audience === "teacher" ? (
          <>
            <MetricRow label="Gerçek Yaklaşım" value={result.actualFamily} compact={compact} />
            <MetricRow label="Beklenen Yaklaşım" value={result.expectedApproach} compact={compact} />
          </>
        ) : (
          <MetricRow label="Beklenen Yaklaşım" value={result.expectedApproach} compact={compact} />
        )}
      </div>

      {result.gapExplanation ? (
        <div className="rounded-lg border border-border bg-muted/20 px-3 py-2.5">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">Açıklama</div>
          <p className="mt-1 leading-relaxed text-foreground">{result.gapExplanation}</p>
        </div>
      ) : null}

      {result.recommendedApproach ? (
        <div className="rounded-lg border border-primary/15 bg-primary/5 px-3 py-2.5">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">Önerilen Yaklaşım</div>
          <p className="mt-1 leading-relaxed text-foreground">{result.recommendedApproach}</p>
        </div>
      ) : null}

      {result.evidence.length > 0 ? (
        <div className="space-y-1.5">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">Satır Kanıtları</div>
          {result.evidence.map((item, index) => (
            <div key={`${item.line}-${item.kind}-${index}`} className="rounded-md border border-border bg-card px-3 py-2">
              <div className="flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                <span className="font-mono-code">:{item.line}</span>
                <span>{item.kind}</span>
              </div>
              <p className="mt-1 text-foreground">{item.detail}</p>
            </div>
          ))}
        </div>
      ) : null}

      {audience === "teacher" ? (
        <div className="rounded-lg border border-dashed border-border bg-muted/20 px-3 py-2.5 space-y-1.5">
          <div className="text-[10px] font-semibold uppercase text-muted-foreground">Öğretmen Provenansı</div>
          <div className="grid gap-2 sm:grid-cols-2">
            <MetricRow
              label="Kaynak"
              value={SOURCE_LABELS[result.expectedSource ?? "unknown"] ?? result.expectedSource ?? "—"}
              compact
            />
            <MetricRow
              label="Güven"
              value={
                result.expectedConfidence != null
                  ? `%${Math.round(result.expectedConfidence * 100)}`
                  : result.actualConfidence != null
                    ? `%${Math.round(result.actualConfidence * 100)} (gerçek)`
                    : "—"
              }
              compact
            />
            <MetricRow
              label="Beklenti Sürümü"
              value={result.expectationVersion != null ? String(result.expectationVersion) : "—"}
              compact
            />
            <MetricRow
              label="Aileler"
              value={(result.expectedFamilies ?? []).join(", ") || "—"}
              compact
            />
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default AlgorithmResults;
