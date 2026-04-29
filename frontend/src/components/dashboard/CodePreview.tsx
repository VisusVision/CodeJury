import { FileCode } from "lucide-react";

interface CodePreviewProps {
  fileName: string;
  content: string;
}

const CodePreview = ({ fileName, content }: CodePreviewProps) => {
  const lines = content.split("\n");

  return (
    <div className="rounded-xl overflow-hidden shadow-card">
      <div className="flex items-center gap-2 px-4 py-2.5 bg-card border-b border-border">
        <FileCode className="h-4 w-4 text-primary" />
        <span className="text-sm font-medium text-foreground">{fileName}</span>
        <span className="ml-auto text-xs text-muted-foreground tabular-nums">{lines.length} satır</span>
      </div>
      <div className="terminal-bg p-4 max-h-[60vh] overflow-auto font-mono-code text-xs leading-relaxed">
        {lines.map((line, i) => (
          <div key={i} className="flex">
            <span className="select-none text-muted-foreground/30 w-10 text-right pr-4 shrink-0 tabular-nums">
              {i + 1}
            </span>
            <span className="text-terminal-foreground whitespace-pre">{line || " "}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

export default CodePreview;
