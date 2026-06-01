import { useRef, useEffect, useCallback } from "react";
import { FileCode } from "lucide-react";

export interface CodeAnnotation {
  line: number;
  severity: "error" | "warning" | "info" | "success";
  message: string;
  agent?: string;
}

interface CodeEditorProps {
  fileName: string;
  content: string;
  annotations?: CodeAnnotation[];
  highlightedLine?: number | null;
}

const severityLineClass: Record<string, string> = {
  error: "bg-destructive/15 border-l-2 border-destructive",
  warning: "bg-warning/10 border-l-2 border-warning",
  info: "bg-primary/5 border-l-2 border-primary/40",
  success: "bg-success/5 border-l-2 border-success/40",
};

const CodeEditor = ({ fileName, content, annotations = [], highlightedLine }: CodeEditorProps) => {
  const lines = content.split("\n");
  const containerRef = useRef<HTMLDivElement>(null);
  const lineRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const setLineRef = useCallback((lineNum: number, el: HTMLDivElement | null) => {
    if (el) lineRefs.current.set(lineNum, el);
    else lineRefs.current.delete(lineNum);
  }, []);

  // Build annotation map
  const annotationMap = new Map<number, CodeAnnotation[]>();
  annotations.forEach((a) => {
    const arr = annotationMap.get(a.line) || [];
    arr.push(a);
    annotationMap.set(a.line, arr);
  });

  // Get highest severity for a line
  const getLineSeverity = (lineNum: number): string | null => {
    const anns = annotationMap.get(lineNum);
    if (!anns) return null;
    if (anns.some((a) => a.severity === "error")) return "error";
    if (anns.some((a) => a.severity === "warning")) return "warning";
    if (anns.some((a) => a.severity === "info")) return "info";
    return "success";
  };

  // Scroll to highlighted line
  useEffect(() => {
    if (highlightedLine && containerRef.current) {
      const el = lineRefs.current.get(highlightedLine);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, [highlightedLine]);

  return (
    <div className="flex h-full min-w-0 flex-col rounded-xl overflow-hidden shadow-card">
      <div className="flex items-center gap-2 px-4 py-2.5 bg-card border-b border-border shrink-0">
        <FileCode className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium text-foreground">{fileName}</span>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">{lines.length} satır</span>
      </div>
      <div
        ref={containerRef}
        className="terminal-bg min-h-0 flex-1 overflow-auto font-mono-code text-xs leading-relaxed"
      >
        {lines.map((line, i) => {
          const lineNum = i + 1;
          const severity = getLineSeverity(lineNum);
          const isHighlighted = highlightedLine === lineNum;
          const lineAnns = annotationMap.get(lineNum);

          return (
            <div
              key={i}
              ref={(el) => setLineRef(lineNum, el)}
            >
              <div
                className={`flex px-4 py-px transition-colors duration-200 ${
                  severity ? severityLineClass[severity] : ""
                } ${isHighlighted ? "ring-1 ring-primary/50 bg-primary/10" : ""}`}
              >
                <span className="select-none text-muted-foreground/30 w-10 text-right pr-4 shrink-0 tabular-nums">
                  {lineNum}
                </span>
                <span className="min-w-max text-terminal-foreground whitespace-pre">{line || " "}</span>
              </div>
              {lineAnns?.map((a, j) => (
                <div key={j} className="flex min-w-max pl-14 pr-4 py-0.5 border-l-2 border-primary/20">
                  <span className={`text-[11px] ${
                    a.severity === "error" ? "text-destructive" :
                    a.severity === "warning" ? "text-warning" :
                    a.severity === "success" ? "text-success" : "text-primary"
                  }`}>
                    ↳ {a.agent ? `[${a.agent}] ` : ""}{a.message}
                  </span>
                </div>
              ))}
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default CodeEditor;
