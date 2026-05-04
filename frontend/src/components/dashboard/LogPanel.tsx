import { useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Terminal } from "lucide-react";
import { useTranslation } from "@/i18n/LanguageContext";

export interface LogEntry {
  id: string;
  timestamp: string;
  agent: string;
  message: string;
  type: "info" | "success" | "error" | "warning";
}

interface LogPanelProps {
  logs: LogEntry[];
}

const typeColorMap: Record<LogEntry["type"], string> = {
  info: "text-blue-400",
  success: "text-green-400",
  error: "text-red-400",
  warning: "text-yellow-400",
};

const LogPanel = ({ logs }: LogPanelProps) => {
  const { t } = useTranslation();
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="flex flex-col rounded-xl overflow-hidden shadow-card">
      <div className="flex items-center gap-2 px-4 py-2.5 bg-card border-b border-border">
        <Terminal className="h-4 w-4 text-muted-foreground" />
        <span className="text-sm font-medium text-foreground">{t("logs.title")}</span>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">{logs.length} {t("logs.records")}</span>
      </div>
      <div
        ref={scrollRef}
        className="terminal-bg p-4 max-h-[300px] overflow-auto font-mono-code text-xs leading-relaxed space-y-1"
      >
        {logs.length === 0 && (
          <p className="text-muted-foreground/60 italic">{t("logs.noLogs")}</p>
        )}
        <AnimatePresence initial={false}>
          {logs.map((log, i) => (
            <motion.div
              key={log.id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.1, delay: i > logs.length - 5 ? (i - (logs.length - 5)) * 0.05 : 0 }}
              className="flex gap-3"
            >
              <span className="text-muted-foreground/50 tabular-nums shrink-0">{log.timestamp}</span>
              <span className={`shrink-0 font-medium ${typeColorMap[log.type]}`}>[{log.agent}]</span>
              <span className="text-terminal-foreground">{log.message}</span>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </div>
  );
};

export default LogPanel;
