import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, Plus, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import {
  AssignmentTestCase,
  GeneratedTestSet,
  TestFixture,
  getActiveGeneratedTestSet,
  getAssignmentTestCases,
  promoteGeneratedTests,
  replaceAssignmentTestCases,
  suggestAssignmentTestCases,
} from "@/services/api";

const ALLOWED_FIXTURE_SUFFIXES = new Set([".txt", ".csv", ".tsv", ".json"]);
const MAX_FIXTURE_FILES = 10;
const MAX_FIXTURE_FILE_BYTES = 64 * 1024;
const MAX_FIXTURE_CASE_BYTES = 256 * 1024;

interface AssignmentBrief {
  id: string;
  name: string;
  description?: string | null;
}

interface TestCaseEditorProps {
  assignment: AssignmentBrief;
  language: string;
  onSaved?: () => void;
}

type PromoteMode = "append" | "replace";

const emptyManualCase = (order: number): AssignmentTestCase => ({
  name: `Test ${order}`,
  stdin: "",
  expected_stdout: "",
  expected_exit_code: 0,
  visibility: "public",
  files: [],
  source: "manual",
  oracle: "teacher",
  display_order: order,
});

export function validateFixtureInput(
  name: string,
  content: string,
  existingFiles: TestFixture[],
): string | null {
  const trimmedName = name.trim();
  if (!trimmedName) {
    return "Fixture adi bos olamaz.";
  }
  if (trimmedName.includes("\\") || trimmedName.includes("\0")) {
    return "Fixture guvenli bir POSIX yolu kullanmali.";
  }
  if (trimmedName.startsWith("/") || trimmedName.includes("..")) {
    return "Fixture yolu veya uzantisi izin verilmiyor.";
  }
  const lowerName = trimmedName.toLowerCase();
  const allowed = Array.from(ALLOWED_FIXTURE_SUFFIXES).some((suffix) => lowerName.endsWith(suffix));
  if (!allowed) {
    return "Fixture yolu veya uzantisi izin verilmiyor.";
  }
  if (existingFiles.length >= MAX_FIXTURE_FILES) {
    return "Bir test en fazla 10 fixture dosyasi icerebilir.";
  }
  const fileBytes = new TextEncoder().encode(content).length;
  if (fileBytes > MAX_FIXTURE_FILE_BYTES) {
    return "Fixture 64 KiB sinirini asiyor.";
  }
  const totalBytes =
    existingFiles.reduce((sum, file) => sum + new TextEncoder().encode(file.content).length, 0) + fileBytes;
  if (totalBytes > MAX_FIXTURE_CASE_BYTES) {
    return "Test fixture toplami 256 KiB sinirini asiyor.";
  }
  return null;
}

const TestCaseEditor = ({ assignment, language, onSaved }: TestCaseEditorProps) => {
  const [testCases, setTestCases] = useState<AssignmentTestCase[]>([]);
  const [aiDrafts, setAiDrafts] = useState<AssignmentTestCase[]>([]);
  const [selectedDraftIds, setSelectedDraftIds] = useState<Set<string>>(new Set());
  const [generatedSet, setGeneratedSet] = useState<GeneratedTestSet | null>(null);
  const [selectedGeneratedIds, setSelectedGeneratedIds] = useState<Set<string>>(new Set());
  const [promoteMode, setPromoteMode] = useState<PromoteMode>("append");
  const [loading, setLoading] = useState(true);
  const [saveLoading, setSaveLoading] = useState(false);
  const [suggestLoading, setSuggestLoading] = useState(false);
  const [promoteLoading, setPromoteLoading] = useState(false);
  const [fixtureEditor, setFixtureEditor] = useState<{ caseIndex: number; name: string; content: string } | null>(
    null,
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [cases, activeSet] = await Promise.all([
        getAssignmentTestCases(assignment.id),
        getActiveGeneratedTestSet(assignment.id),
      ]);
      setTestCases(cases);
      setGeneratedSet(activeSet);
      setSelectedGeneratedIds(new Set());
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Testler yuklenemedi";
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, [assignment.id]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const addManualTestCase = () => {
    setTestCases((prev) => [...prev, emptyManualCase(prev.length + 1)]);
  };

  const updateTestCase = (index: number, field: keyof AssignmentTestCase, value: string | number) => {
    setTestCases((prev) =>
      prev.map((item, i) => (i === index ? { ...item, [field]: value } : item)),
    );
  };

  const removeTestCase = (index: number) => {
    setTestCases((prev) => prev.filter((_, i) => i !== index));
  };

  const requestAiTestSuggestions = async () => {
    if (suggestLoading) return;
    setSuggestLoading(true);
    try {
      const result = await suggestAssignmentTestCases(assignment.id);
      setAiDrafts(result.suggestions);
      setSelectedDraftIds(new Set());
      toast.success(
        language === "tr"
          ? `${result.verified_count} AI test taslagi hazir`
          : `${result.verified_count} AI draft suggestions ready`,
      );
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (language === "tr" ? "Test onerisi alinamadi" : "Could not fetch test suggestions");
      toast.error(msg);
    } finally {
      setSuggestLoading(false);
    }
  };

  const toggleDraftSelection = (draftId: string) => {
    setSelectedDraftIds((prev) => {
      const next = new Set(prev);
      if (next.has(draftId)) {
        next.delete(draftId);
      } else {
        next.add(draftId);
      }
      return next;
    });
  };

  const appendSelectedDrafts = () => {
    const selected = aiDrafts.filter((draft) => selectedDraftIds.has(String(draft.id ?? draft.name)));
    if (!selected.length) {
      toast.error(language === "tr" ? "En az bir taslak secin" : "Select at least one draft");
      return;
    }
    setTestCases((prev) => [
      ...prev,
      ...selected.map((draft, index) => ({
        ...draft,
        id: undefined,
        source: "manual" as const,
        oracle: "teacher" as const,
        generated_set_id: null,
        display_order: prev.length + index + 1,
      })),
    ]);
    setAiDrafts((prev) => prev.filter((draft) => !selectedDraftIds.has(String(draft.id ?? draft.name))));
    setSelectedDraftIds(new Set());
    toast.success(language === "tr" ? "Secili taslaklar eklendi" : "Selected drafts added");
  };

  const toggleGeneratedSelection = (caseId: string) => {
    setSelectedGeneratedIds((prev) => {
      const next = new Set(prev);
      if (next.has(caseId)) {
        next.delete(caseId);
      } else {
        next.add(caseId);
      }
      return next;
    });
  };

  const handlePromoteGenerated = async () => {
    if (promoteLoading || !generatedSet) return;
    const caseIds = Array.from(selectedGeneratedIds);
    if (!caseIds.length) {
      toast.error(language === "tr" ? "En az bir uretilen test secin" : "Select at least one generated test");
      return;
    }
    if (promoteMode === "replace") {
      const confirmed = window.confirm(
        language === "tr"
          ? "Mevcut testler silinip secili uretilen testlerle degistirilecek. Devam edilsin mi?"
          : "Existing tests will be replaced with the selected generated tests. Continue?",
      );
      if (!confirmed) return;
    }
    setPromoteLoading(true);
    try {
      const saved = await promoteGeneratedTests(assignment.id, generatedSet.id, {
        case_ids: caseIds,
        mode: promoteMode,
      });
      setTestCases(saved);
      setSelectedGeneratedIds(new Set());
      setGeneratedSet(null);
      onSaved?.();
      toast.success(language === "tr" ? "Uretilen testler aktarildi" : "Generated tests promoted");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (language === "tr" ? "Testler aktarilamadi" : "Could not promote tests");
      toast.error(msg);
    } finally {
      setPromoteLoading(false);
    }
  };

  const openFixtureEditor = (caseIndex: number) => {
    setFixtureEditor({ caseIndex, name: "", content: "" });
  };

  const saveFixture = () => {
    if (!fixtureEditor) return;
    const target = testCases[fixtureEditor.caseIndex];
    if (!target) return;
    const validationError = validateFixtureInput(fixtureEditor.name, fixtureEditor.content, target.files);
    if (validationError) {
      toast.error(validationError);
      return;
    }
    setTestCases((prev) =>
      prev.map((item, index) =>
        index === fixtureEditor.caseIndex
          ? {
              ...item,
              files: [...item.files, { name: fixtureEditor.name.trim(), content: fixtureEditor.content }],
            }
          : item,
      ),
    );
    setFixtureEditor(null);
  };

  const removeFixture = (caseIndex: number, fixtureIndex: number) => {
    setTestCases((prev) =>
      prev.map((item, index) =>
        index === caseIndex
          ? { ...item, files: item.files.filter((_, fileIndex) => fileIndex !== fixtureIndex) }
          : item,
      ),
    );
  };

  const saveTestCases = async () => {
    const invalid = testCases.find((row) => !row.name.trim());
    if (invalid) {
      toast.error(language === "tr" ? "Test adi bos olamaz" : "Test name cannot be empty");
      return;
    }
    for (const row of testCases) {
      for (const file of row.files) {
        const validationError = validateFixtureInput(file.name, file.content, []);
        if (validationError) {
          toast.error(`${row.name}: ${validationError}`);
          return;
        }
      }
    }
    if (saveLoading) return;
    setSaveLoading(true);
    try {
      const saved = await replaceAssignmentTestCases(
        assignment.id,
        testCases.map((row, index) => ({
          ...row,
          display_order: index + 1,
          expected_exit_code: Number(row.expected_exit_code ?? 0) || 0,
          files: row.files,
          source: "manual",
          oracle: "teacher",
        })),
      );
      setTestCases(saved);
      onSaved?.();
      toast.success(language === "tr" ? "Testler kaydedildi" : "Tests saved");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : (language === "tr" ? "Testler kaydedilemedi" : "Tests could not be saved");
      toast.error(msg);
    } finally {
      setSaveLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
        Testler yukleniyor...
      </div>
    );
  }

  return (
    <div className="space-y-4 p-5">
      <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-muted/20 p-3">
        <div className="space-y-1">
          <p className="text-xs font-medium text-foreground">HackerRank Testleri</p>
          <p className="text-[11px] text-muted-foreground">
            Public testler ogrenciye gorunur; hidden testler calisir ama girdi/cikti gizlenir.
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <button
            type="button"
            onClick={addManualTestCase}
            className="flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-foreground hover:bg-muted/50"
          >
            <Plus className="h-4 w-4" /> Manuel Test Ekle
          </button>
          <button
            type="button"
            onClick={requestAiTestSuggestions}
            disabled={suggestLoading}
            className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {suggestLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            AI Test Oner
          </button>
        </div>
      </div>

      {aiDrafts.length > 0 && (
        <div className="space-y-2 rounded-xl border border-dashed border-primary/40 bg-primary/5 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-medium text-foreground">AI taslaklari (henuz kaydedilmedi)</p>
            <button
              type="button"
              onClick={appendSelectedDrafts}
              className="rounded-lg border border-border px-2 py-1 text-xs font-medium hover:bg-muted/50"
            >
              Secili Taslaklari Ekle
            </button>
          </div>
          <div className="space-y-1.5">
            {aiDrafts.map((draft) => {
              const draftKey = String(draft.id ?? draft.name);
              return (
                <label key={draftKey} className="flex items-center gap-2 rounded-lg border border-border bg-card p-2 text-xs">
                  <input
                    type="checkbox"
                    aria-label={draft.name}
                    checked={selectedDraftIds.has(draftKey)}
                    onChange={() => toggleDraftSelection(draftKey)}
                    className="h-4 w-4 rounded"
                  />
                  <span className="font-medium">{draft.name}</span>
                  <span className="text-muted-foreground">{draft.visibility}</span>
                </label>
              );
            })}
          </div>
        </div>
      )}

      {generatedSet && (
        <div className="space-y-2 rounded-xl border border-border bg-muted/10 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-xs font-medium text-foreground">Aktif uretilen test seti (v{generatedSet.version})</p>
              <p className="text-[11px] text-muted-foreground">
                {generatedSet.provider}/{generatedSet.model} · {generatedSet.difficulty}
              </p>
            </div>
            <div className="flex items-center gap-2 text-xs">
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name="promote-mode"
                  checked={promoteMode === "append"}
                  onChange={() => setPromoteMode("append")}
                />
                Ekle modu
              </label>
              <label className="flex items-center gap-1">
                <input
                  type="radio"
                  name="promote-mode"
                  aria-label="Degistir modu"
                  checked={promoteMode === "replace"}
                  onChange={() => setPromoteMode("replace")}
                />
                Degistir modu
              </label>
            </div>
          </div>
          <div className="space-y-1.5">
            {generatedSet.cases.map((row) => (
              <label key={row.id ?? row.name} className="flex items-center gap-2 rounded-lg border border-border bg-card p-2 text-xs">
                <input
                  type="checkbox"
                  aria-label={row.name}
                  checked={selectedGeneratedIds.has(String(row.id))}
                  onChange={() => toggleGeneratedSelection(String(row.id))}
                  className="h-4 w-4 rounded"
                />
                <span className="font-medium">{row.name}</span>
                <span className="text-muted-foreground">{row.visibility}</span>
              </label>
            ))}
          </div>
          <button
            type="button"
            onClick={handlePromoteGenerated}
            disabled={promoteLoading}
            className="rounded-lg bg-secondary px-3 py-1.5 text-sm font-medium hover:bg-secondary/80 disabled:opacity-50"
          >
            {promoteLoading ? (
              <Loader2 className="inline h-4 w-4 animate-spin" />
            ) : promoteMode === "replace" ? (
              "Uretilen Testleri Degistir"
            ) : (
              "Uretilen Testleri Ekle"
            )}
          </button>
        </div>
      )}

      <div className="space-y-2.5">
        {testCases.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border py-8 text-center text-xs text-muted-foreground">
            Kayitli test yok.
          </p>
        ) : (
          testCases.map((row, index) => (
            <div key={row.id || `case-${index}`} className="space-y-2 rounded-xl border border-border bg-card p-3">
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={row.name}
                  onChange={(e) => updateTestCase(index, "name", e.target.value)}
                  className="min-w-0 flex-1 rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  placeholder="Test adi"
                />
                <select
                  value={row.visibility}
                  onChange={(e) => updateTestCase(index, "visibility", e.target.value as AssignmentTestCase["visibility"])}
                  className="rounded-lg border border-input bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                >
                  <option value="public">public</option>
                  <option value="hidden">hidden</option>
                </select>
                <button
                  type="button"
                  aria-label="Testi sil"
                  onClick={() => removeTestCase(index)}
                  className="text-muted-foreground hover:text-destructive"
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </div>
              <div className="grid gap-2 md:grid-cols-2">
                <textarea
                  value={row.stdin}
                  onChange={(e) => updateTestCase(index, "stdin", e.target.value)}
                  placeholder="Girdi (stdin)"
                  rows={3}
                  className="rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <textarea
                  value={row.expected_stdout}
                  onChange={(e) => updateTestCase(index, "expected_stdout", e.target.value)}
                  placeholder="Beklenen cikti"
                  rows={3}
                  className="rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <span>Exit code</span>
                <input
                  type="number"
                  value={row.expected_exit_code ?? 0}
                  onChange={(e) => updateTestCase(index, "expected_exit_code", parseInt(e.target.value, 10) || 0)}
                  className="w-20 rounded-lg border border-input bg-background px-2 py-1 text-center text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <span className="ml-auto">Kaynak: {row.source}</span>
              </div>
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-foreground">Fixture dosyalari</p>
                  <button
                    type="button"
                    onClick={() => openFixtureEditor(index)}
                    className="text-xs text-primary hover:underline"
                  >
                    Fixture Ekle
                  </button>
                </div>
                {row.files.length === 0 ? (
                  <p className="text-[11px] text-muted-foreground">Fixture yok (.txt, .csv, .tsv, .json)</p>
                ) : (
                  row.files.map((file, fileIndex) => (
                    <div key={`${file.name}-${fileIndex}`} className="flex items-center justify-between rounded border border-border px-2 py-1 text-xs">
                      <span className="font-mono">{file.name}</span>
                      <button
                        type="button"
                        onClick={() => removeFixture(index, fileIndex)}
                        className="text-muted-foreground hover:text-destructive"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {fixtureEditor && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md space-y-3 rounded-xl border border-border bg-background p-4 shadow-xl">
            <p className="text-sm font-medium">Fixture ekle</p>
            <input
              type="text"
              value={fixtureEditor.name}
              onChange={(e) => setFixtureEditor({ ...fixtureEditor, name: e.target.value })}
              placeholder="ornek: data/input.csv"
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm"
            />
            <textarea
              value={fixtureEditor.content}
              onChange={(e) => setFixtureEditor({ ...fixtureEditor, content: e.target.value })}
              placeholder="Fixture icerigi"
              rows={4}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 font-mono text-xs"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setFixtureEditor(null)}
                className="rounded-lg border border-border px-3 py-1.5 text-sm"
              >
                Iptal
              </button>
              <button
                type="button"
                onClick={saveFixture}
                className="rounded-lg bg-primary px-3 py-1.5 text-sm text-primary-foreground"
              >
                Fixture Kaydet
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex items-center justify-between border-t border-border pt-4">
        <p className="text-xs text-muted-foreground">{testCases.length} test senaryosu</p>
        <button
          type="button"
          onClick={saveTestCases}
          disabled={saveLoading}
          className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {saveLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
          Testleri Kaydet
        </button>
      </div>
    </div>
  );
};

export default TestCaseEditor;
