import { useCallback, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, FileCode, X, CheckCircle } from "lucide-react";
import { useTranslation } from "@/i18n/LanguageContext";

interface UploadedFile {
  name: string;
  size: number;
  type: string;
  content: string;
}

interface FileUploadZoneProps {
  onFilesUploaded: (files: UploadedFile[]) => void;
  uploadedFiles: UploadedFile[];
  onRemoveFile: (name: string) => void;
  compact?: boolean;
  disableRemove?: boolean;
}

const FileUploadZone = ({ onFilesUploaded, uploadedFiles, onRemoveFile, compact, disableRemove }: FileUploadZoneProps) => {
  const { t } = useTranslation();
  const [isDragging, setIsDragging] = useState(false);

  const handleDrag = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDragIn = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragOut = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const processFiles = useCallback((fileList: FileList) => {
    const files = Array.from(fileList);
    const readers = files.map(
      (file) =>
        new Promise<UploadedFile>((resolve) => {
          const reader = new FileReader();
          reader.onload = (e) => {
            resolve({
              name: file.name,
              size: file.size,
              type: file.type,
              content: e.target?.result as string,
            });
          };
          reader.readAsText(file);
        })
    );
    Promise.all(readers).then(onFilesUploaded);
  }, [onFilesUploaded]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.files?.length) {
      processFiles(e.dataTransfer.files);
    }
  }, [processFiles]);

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) {
      processFiles(e.target.files);
    }
  }, [processFiles]);

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  };

  if (compact) {
    return (
      <motion.label
        htmlFor="file-upload-compact"
        onDragEnter={handleDragIn}
        onDragLeave={handleDragOut}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        className={`flex items-center justify-center gap-2 px-4 py-2 cursor-pointer transition-colors duration-150 ${
          isDragging
            ? "bg-primary/5 text-primary"
            : "bg-muted/30 hover:bg-muted/50 text-muted-foreground hover:text-foreground"
        }`}
      >
        <Upload className="h-3.5 w-3.5 shrink-0" />
        <span className="text-xs font-medium">{t("workspace.dropHere")} {t("workspace.orClick")}</span>
        <input
          id="file-upload-compact"
          type="file"
          className="hidden"
          multiple
          accept=".py,.js,.ts,.jsx,.tsx,.c,.cpp,.h,.hpp,.java,.json,.go,.rs,.rb,.php,.cs"
          onChange={handleFileInput}
        />
      </motion.label>
    );
  }

  return (
    <div className="space-y-3">
      <motion.label
        htmlFor="file-upload"
        onDragEnter={handleDragIn}
        onDragLeave={handleDragOut}
        onDragOver={handleDrag}
        onDrop={handleDrop}
        whileHover={{ scale: 1.005 }}
        className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-10 cursor-pointer transition-colors duration-150 ease-smooth ${
          isDragging
            ? "border-primary bg-primary/5"
            : "border-border bg-muted/30 hover:border-primary/50 hover:bg-muted/50"
        }`}
      >
        <div className="rounded-full bg-card p-3 shadow-card mb-3">
          <Upload className={`h-5 w-5 transition-colors duration-150 ${isDragging ? "text-primary" : "text-muted-foreground"}`} />
        </div>
        <p className="text-sm font-medium text-foreground">{t("workspace.dropHere")}</p>
        <p className="text-xs text-muted-foreground mt-1">{t("workspace.supportedFormats")}: Python, JS, C++, Java, JSON ({t("workspace.maxSize")}: 10MB)</p>
        <input
          id="file-upload"
          type="file"
          className="hidden"
          multiple
          accept=".py,.js,.ts,.jsx,.tsx,.c,.cpp,.h,.hpp,.java,.json,.go,.rs,.rb,.php,.cs"
          onChange={handleFileInput}
        />
      </motion.label>

      <AnimatePresence>
        {uploadedFiles.map((file) => (
          <motion.div
            key={file.name}
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.15, ease: [0.25, 0.1, 0.25, 1] }}
            className="flex items-center gap-3 rounded-lg bg-card p-3 shadow-card"
          >
            <FileCode className="h-4 w-4 text-primary shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{file.name}</p>
              <p className="text-xs text-muted-foreground">{formatSize(file.size)}</p>
            </div>
            <CheckCircle className="h-4 w-4 text-success shrink-0" />
            <button
              onClick={() => onRemoveFile(file.name)}
              disabled={disableRemove}
              className={`rounded-md p-1 transition-colors duration-150 ${
                disableRemove
                  ? "text-muted-foreground/40 cursor-not-allowed"
                  : "text-muted-foreground hover:text-destructive hover:bg-destructive/10"
              }`}
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

export default FileUploadZone;
