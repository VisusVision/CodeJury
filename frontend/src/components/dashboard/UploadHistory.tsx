import { motion, AnimatePresence } from "framer-motion";
import { History, Upload, AlertCircle, CheckCircle2, TrendingUp, TrendingDown } from "lucide-react";
import { useTranslation } from "@/i18n/LanguageContext";

export interface UploadRecord {
  id: string;
  fileName: string;
  timestamp: Date;
  hasError: boolean;
  score?: number;
}

interface UploadHistoryProps {
  records: UploadRecord[];
}

const UploadHistory = ({ records }: UploadHistoryProps) => {
  const { t, language } = useTranslation();
  const totalUploads = records.length;
  const errorCount = records.filter((r) => r.hasError).length;
  const successCount = totalUploads - errorCount;
  const errorRate = totalUploads > 0 ? Math.round((errorCount / totalUploads) * 100) : 0;

  
  const scoredRecords = records.filter((r) => r.score !== undefined);
  const trend: "up" | "down" | "equal" | "none" = (() => {
    if (scoredRecords.length < 2) return "none";
    const last = scoredRecords[scoredRecords.length - 1]?.score ?? 0;
    const prev = scoredRecords[scoredRecords.length - 2]?.score ?? 0;
    if (last > prev) return "up";
    if (last < prev) return "down";
    return "equal";
  })();

  const formatDate = (date: Date | string) => {
    const d = date instanceof Date ? date : new Date(date);
    return d.toLocaleDateString(language === "tr" ? "tr-TR" : "en-US", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  return (
    <div className="rounded-xl bg-card shadow-card overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2 border-b border-border">
        <History className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-semibold text-foreground">{t("uploadHistory.title")}</span>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">{totalUploads} {t("uploadHistory.uploads")}</span>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-px bg-border/50">
        <div className="bg-card px-4 py-1.5 text-center">
          <p className="text-base font-bold text-foreground tabular-nums leading-none">{totalUploads}</p>
          <p className="text-[11px] text-muted-foreground">{t("uploadHistory.total")}</p>
        </div>
        <div className="bg-card px-4 py-1.5 text-center">
          <p className="text-base font-bold text-success tabular-nums leading-none">{successCount}</p>
          <p className="text-[11px] text-muted-foreground">{t("uploadHistory.successful")}</p>
        </div>
        <div className="bg-card px-4 py-1.5 text-center">
          <p className={`text-base font-bold tabular-nums leading-none ${errorCount > 0 ? "text-destructive" : "text-foreground"}`}>{errorCount}</p>
          <p className="text-[11px] text-muted-foreground">{t("uploadHistory.failed")}</p>
        </div>
      </div>

      {/* Progress indicator */}
      {trend !== "none" && (
        <div className={`flex items-center gap-2 px-4 py-1.5 ${trend === "up" ? "bg-success/5" : trend === "down" ? "bg-warning/5" : "bg-muted/40"} border-b border-border`}>
          {trend === "up" ? (
            <TrendingUp className="h-3.5 w-3.5 text-success" />
          ) : trend === "down" ? (
            <TrendingDown className="h-3.5 w-3.5 text-warning" />
          ) : (
            <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground" />
          )}
          <span className={`text-xs font-medium ${trend === "up" ? "text-success" : trend === "down" ? "text-warning" : "text-muted-foreground"}`}>
            {trend === "up" ? t("uploadHistory.trendUp") : trend === "down" ? t("uploadHistory.trendDown") : t("uploadHistory.trendEqual")}
          </span>
          {errorRate > 0 && (
            <span className="ml-auto text-[11px] text-muted-foreground">{t("uploadHistory.errorRate")}: %{errorRate}</span>
          )}
        </div>
      )}

      {/* Upload list */}
      <div className="max-h-[220px] overflow-auto divide-y divide-border/50">
        {records.length === 0 ? (
          <div className="px-4 py-4 text-center">
            <Upload className="h-5 w-5 text-muted-foreground/40 mx-auto mb-2" />
            <p className="text-xs text-muted-foreground/60">{t("uploadHistory.noUploads")}</p>
          </div>
        ) : (
          <AnimatePresence initial={false}>
            {[...records].reverse().map((record, i) => (
              <motion.div
                key={record.id}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.15, delay: i * 0.03 }}
                className="flex items-center gap-2 px-4 py-1.5 hover:bg-muted/30 transition-colors"
              >
                {record.hasError ? (
                  <AlertCircle className="h-3.5 w-3.5 text-destructive shrink-0" />
                ) : (
                  <CheckCircle2 className="h-3.5 w-3.5 text-success shrink-0" />
                )}
                <div className="flex-1 min-w-0">
                  <p className="text-xs font-medium text-foreground truncate">{record.fileName}</p>
                  <p className="text-[11px] text-muted-foreground">{formatDate(record.timestamp)}</p>
                </div>
                {record.score !== undefined && (
                  <span className="text-xs font-bold text-foreground tabular-nums shrink-0">{record.score}%</span>
                )}
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                  record.hasError ? "bg-destructive/10 text-destructive" : "bg-success/10 text-success"
                }`}>
                  {record.hasError ? t("common.error") : t("common.success")}
                </span>
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>
    </div>
  );
};

export default UploadHistory;
