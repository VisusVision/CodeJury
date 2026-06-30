import { Server, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { formatRuntimeHealthLabel } from "@/lib/runtimeHealthLabel";
import { useRuntimeHealth } from "@/hooks/useRuntimeHealth";
import { useTranslation } from "@/i18n/LanguageContext";

interface RuntimeHealthBadgeProps {
  className?: string;
  compact?: boolean;
}

const statusDotClass: Record<ReturnType<typeof formatRuntimeHealthLabel>["status"], string> = {
  ok: "bg-success",
  degraded: "bg-warning",
  unknown: "bg-muted-foreground/50",
};

export default function RuntimeHealthBadge({ className, compact = false }: RuntimeHealthBadgeProps) {
  const { t } = useTranslation();
  const { health, loading } = useRuntimeHealth();
  const label = formatRuntimeHealthLabel(health);

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-2.5 py-1.5 text-[11px] text-muted-foreground",
        className,
      )}
      title={t("runtimeHealth.title")}
    >
      <span className={cn("h-2 w-2 shrink-0 rounded-full", statusDotClass[label.status], loading && "animate-pulse")} />
      {!compact && (
        <span className="hidden sm:inline font-medium text-foreground/80">{t("runtimeHealth.title")}</span>
      )}
      <span className="inline-flex items-center gap-1 truncate max-w-[140px] sm:max-w-[220px]">
        <Sparkles className="h-3 w-3 shrink-0" />
        <span className="truncate">{loading ? t("runtimeHealth.loading") : label.llmText}</span>
      </span>
      <span className="inline-flex items-center gap-1 truncate max-w-[120px] sm:max-w-[180px]">
        <Server className="h-3 w-3 shrink-0" />
        <span className="truncate">{loading ? "…" : label.sandboxText}</span>
      </span>
    </div>
  );
}
