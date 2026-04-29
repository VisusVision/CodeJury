import { FileCode, FolderOpen, Settings, BookOpen, X } from "lucide-react";

interface UploadedFile {
  name: string;
  size: number;
}

interface ProjectSidebarProps {
  files: UploadedFile[];
  activeFile: string | null;
  onSelectFile: (name: string) => void;
  onRemoveFile: (name: string) => void;
}

const ProjectSidebar = ({ files, activeFile, onSelectFile, onRemoveFile }: ProjectSidebarProps) => {
  return (
    <aside className="flex flex-col h-full bg-sidebar">
      <div className="p-5 pb-4">
        <div className="flex items-center gap-2 mb-1">
          <div className="h-6 w-6 rounded-md bg-primary flex items-center justify-center">
            <span className="text-xs font-bold text-primary-foreground">A</span>
          </div>
          <h1 className="text-sm font-bold text-foreground tracking-tight">Agent Studio</h1>
        </div>
        <p className="text-xs text-muted-foreground mt-1">Çoklu Ajan Kod İnceleme Sistemi</p>
      </div>

      <nav className="flex-1 px-3 space-y-0.5">
        <div className="px-2 py-2">
          <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Proje Dosyaları</span>
        </div>

        {files.length === 0 ? (
          <div className="px-2 py-6 text-center">
            <FolderOpen className="h-5 w-5 text-muted-foreground/40 mx-auto mb-2" />
            <p className="text-xs text-muted-foreground/60">Henüz dosya yüklenmedi</p>
          </div>
        ) : (
          files.map((file) => (
            <div
              key={file.name}
              className={`group flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm transition-colors duration-150 ease-smooth ${
                activeFile === file.name
                  ? "bg-card shadow-card text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/50"
              }`}
            >
              <button
                onClick={() => onSelectFile(file.name)}
                className="flex items-center gap-2 flex-1 min-w-0"
              >
                <FileCode className="h-4 w-4 text-primary shrink-0" />
                <span className="truncate">{file.name}</span>
              </button>
              <button
                onClick={(e) => { e.stopPropagation(); onRemoveFile(file.name); }}
                className="opacity-0 group-hover:opacity-100 rounded-md p-0.5 text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all duration-150"
                title="Dosyayı kaldır"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))
        )}
      </nav>

      <div className="p-3 space-y-0.5 border-t border-border/50">
        <button className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors duration-150">
          <BookOpen className="h-4 w-4" />
          <span>Dokümantasyon</span>
        </button>
        <button className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors duration-150">
          <Settings className="h-4 w-4" />
          <span>Ayarlar</span>
        </button>
      </div>
    </aside>
  );
};

export default ProjectSidebar;
