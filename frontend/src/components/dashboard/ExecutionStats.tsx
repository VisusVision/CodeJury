import { Timer, Cpu, MemoryStick } from "lucide-react";
import { motion } from "framer-motion";
import { useTranslation } from "@/i18n/LanguageContext";

interface ExecutionStatsProps {
  executionTimeMs: number;
  memoryUsageMb: number;
  peakMemoryMb: number;
}

const ExecutionStats = ({ executionTimeMs, memoryUsageMb, peakMemoryMb }: ExecutionStatsProps) => {
  const { t } = useTranslation();

  const formatTime = (ms: number) => {
    if (ms < 1000) return `${ms} ms`;
    return `${(ms / 1000).toFixed(2)} s`;
  };

  const stats = [
    {
      icon: Timer,
      label: t("report.executionTime"),
      value: formatTime(executionTimeMs),
      sub: executionTimeMs < 1000 ? t("report.fast") : executionTimeMs < 3000 ? t("report.normal") : t("report.slow"),
      color: executionTimeMs < 1000 ? "text-success" : executionTimeMs < 3000 ? "text-warning" : "text-destructive",
      bgColor: executionTimeMs < 1000 ? "bg-success/10" : executionTimeMs < 3000 ? "bg-warning/10" : "bg-destructive/10",
    },
    {
      icon: MemoryStick,
      label: t("report.memoryUsage"),
      value: `${memoryUsageMb.toFixed(1)} MB`,
      sub: memoryUsageMb < 50 ? t("report.low") : memoryUsageMb < 150 ? t("report.medium") : t("report.high"),
      color: memoryUsageMb < 50 ? "text-success" : memoryUsageMb < 150 ? "text-warning" : "text-destructive",
      bgColor: memoryUsageMb < 50 ? "bg-success/10" : memoryUsageMb < 150 ? "bg-warning/10" : "bg-destructive/10",
    },
    {
      icon: Cpu,
      label: t("report.peakMemory"),
      value: `${peakMemoryMb.toFixed(1)} MB`,
      sub: t("report.maximum"),
      color: "text-primary",
      bgColor: "bg-primary/10",
    },
  ];

  return (
    <div className="grid grid-cols-3 gap-3">
      {stats.map((stat, i) => (
        <motion.div
          key={stat.label}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3, delay: i * 0.1 }}
          className="rounded-xl bg-card shadow-card p-4 flex flex-col gap-2"
        >
          <div className="flex items-center gap-2">
            <div className={`rounded-md p-1.5 ${stat.bgColor}`}>
              <stat.icon className={`h-3.5 w-3.5 ${stat.color}`} />
            </div>
            <span className="text-xs text-muted-foreground">{stat.label}</span>
          </div>
          <div>
            <p className="text-lg font-bold text-foreground tabular-nums">{stat.value}</p>
            <p className={`text-[11px] font-medium ${stat.color}`}>{stat.sub}</p>
          </div>
        </motion.div>
      ))}
    </div>
  );
};

export default ExecutionStats;
