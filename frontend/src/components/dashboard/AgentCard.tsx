import { motion } from "framer-motion";
import { LucideIcon } from "lucide-react";
import { useTranslation } from "@/i18n/LanguageContext";

export type AgentStatus = "idle" | "thinking" | "acting" | "done" | "error";

interface AgentCardProps {
  name: string;
  description: string;
  icon: LucideIcon;
  status: AgentStatus;
  lastAction?: string;
}

const AgentCard = ({ name, description, icon: Icon, status, lastAction }: AgentCardProps) => {
  const { t } = useTranslation();

  const statusConfig: Record<AgentStatus, { label: string; dotClass: string; bgClass: string }> = {
    idle: { label: t("agents.status.idle"), dotClass: "bg-muted-foreground", bgClass: "" },
    thinking: { label: t("agents.status.thinking"), dotClass: "bg-warning animate-pulse-dot", bgClass: "ring-1 ring-warning/20" },
    acting: { label: t("agents.status.acting"), dotClass: "bg-primary animate-pulse-dot", bgClass: "ring-1 ring-primary/20" },
    done: { label: t("agents.status.done"), dotClass: "bg-success", bgClass: "ring-1 ring-success/20" },
    error: { label: t("agents.status.error"), dotClass: "bg-destructive", bgClass: "ring-1 ring-destructive/20" },
  };

  const config = statusConfig[status];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
      className={`rounded-lg bg-card p-4 shadow-card transition-shadow duration-150 hover:shadow-card-hover ${config.bgClass}`}
    >
      <div className="flex items-start gap-3">
        <div className="rounded-md bg-muted p-2">
          <Icon className="h-4 w-4 text-foreground" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-semibold text-foreground truncate">{name}</h3>
            <div className="flex items-center gap-1.5 ml-auto shrink-0">
              <span className={`h-2 w-2 rounded-full ${config.dotClass}`} />
              <span className="text-xs text-muted-foreground">{config.label}</span>
            </div>
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">{description}</p>
          {lastAction && (
            <p className="text-xs text-muted-foreground mt-2 font-mono-code bg-muted rounded px-2 py-1 truncate">
              {lastAction}
            </p>
          )}
        </div>
      </div>
    </motion.div>
  );
};

export default AgentCard;
