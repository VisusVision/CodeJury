import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  createStudent,
  deleteStudent,
  getStudents,
  importStudentsCsv,
  updateStudent,
  type Department,
  type Student,
} from "@/services/api";
import {
  FileUp,
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Loader2,
  Pencil,
  Plus,
  Search,
  Trash2,
  Upload,
  Users,
  X,
} from "lucide-react";

interface StudentsPanelProps {
  departments: Department[];
}

interface StudentFormState {
  student_no: string;
  tc_no: string;
  first_name: string;
  last_name: string;
  department_id: string;
  class_year: string;
}

type SortKey = "student_no" | "tc_no" | "name" | "department" | "class_year";

const emptyForm = (): StudentFormState => ({
  student_no: "",
  tc_no: "",
  first_name: "",
  last_name: "",
  department_id: "",
  class_year: "",
});

const normalize = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .replace(/ç/g, "c")
    .replace(/ğ/g, "g")
    .replace(/ı/g, "i")
    .replace(/ö/g, "o")
    .replace(/ş/g, "s")
    .replace(/ü/g, "u")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();

const extractDetailMessage = (error: unknown) => {
  const raw = error instanceof Error ? error.message : String(error);
  const detailIndex = raw.indexOf(": ");
  const payload = detailIndex >= 0 ? raw.slice(detailIndex + 2) : raw;
  try {
    const parsed = JSON.parse(payload) as { detail?: unknown };
    if (typeof parsed.detail === "string") {
      return parsed.detail;
    }
  } catch {
    // ignore parsing errors and use raw text
  }
  return payload;
};

const STUDENTS_PER_PAGE = 10;

const StudentsPanel = ({ departments }: StudentsPanelProps) => {
  const [students, setStudents] = useState<Student[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState("");
  const [manualForm, setManualForm] = useState<StudentFormState>(emptyForm());
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [editingStudent, setEditingStudent] = useState<Student | null>(null);
  const [deletingStudent, setDeletingStudent] = useState<Student | null>(null);
  const [editForm, setEditForm] = useState<StudentFormState>(emptyForm());
  const [currentPage, setCurrentPage] = useState(1);
  const [sortKey, setSortKey] = useState<SortKey>("student_no");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");

  const loadStudents = async () => {
    try {
      setRefreshing(true);
      const rows = await getStudents();
      setStudents(rows);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Öğrenci listesi yüklenemedi");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    void loadStudents();
  }, []);

  useEffect(() => {
    if (!editingStudent) {
      setEditForm(emptyForm());
      return;
    }
    setEditForm({
      student_no: editingStudent.student_no,
      tc_no: editingStudent.tc_no,
      first_name: editingStudent.first_name,
      last_name: editingStudent.last_name,
      department_id: editingStudent.department_id || "",
      class_year: editingStudent.class_year ? String(editingStudent.class_year) : "",
    });
  }, [editingStudent]);

  const departmentLookup = useMemo(() => {
    const map = new Map<string, Department>();
    departments.forEach((department) => map.set(department.id, department));
    return map;
  }, [departments]);

  const filteredStudents = useMemo(() => {
    const query = normalize(search);
    if (!query) return students;
    return students.filter((student) => {
      const department = student.department_name || departmentLookup.get(student.department_id || "")?.name || "";
      return [student.student_no, student.tc_no, student.first_name, student.last_name, department, student.class_year]
        .map((value) => normalize(String(value)))
        .some((value) => value.includes(query));
    });
  }, [departmentLookup, search, students]);

  const sortedStudents = useMemo(() => {
    const getSortValue = (student: Student) => {
      if (sortKey === "student_no") return student.student_no;
      if (sortKey === "tc_no") return student.tc_no;
      if (sortKey === "name") return `${student.first_name} ${student.last_name}`;
      if (sortKey === "class_year") return String(student.class_year || 0);
      return student.department_name || departmentLookup.get(student.department_id || "")?.name || "";
    };

    return [...filteredStudents].sort((left, right) => {
      const comparison = getSortValue(left).localeCompare(getSortValue(right), "tr", {
        numeric: true,
        sensitivity: "base",
      });
      return sortDirection === "asc" ? comparison : -comparison;
    });
  }, [departmentLookup, filteredStudents, sortDirection, sortKey]);

  useEffect(() => {
    setCurrentPage(1);
  }, [search]);

  const totalPages = Math.max(1, Math.ceil(filteredStudents.length / STUDENTS_PER_PAGE));

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [currentPage, totalPages]);

  const paginatedStudents = useMemo(() => {
    const start = (currentPage - 1) * STUDENTS_PER_PAGE;
    return sortedStudents.slice(start, start + STUDENTS_PER_PAGE);
  }, [currentPage, sortedStudents]);

  const resetManualForm = () => setManualForm(emptyForm());

  const validateForm = (form: StudentFormState) => {
    if (!form.student_no.trim() || !form.tc_no.trim() || !form.first_name.trim() || !form.last_name.trim()) {
      return "Tüm alanlar zorunludur";
    }
    if (!form.department_id.trim()) {
      return "Bölüm seçimi zorunludur";
    }
    if (!form.class_year.trim()) {
      return "Sınıf seçimi zorunludur";
    }
    return "";
  };

  const parseClassYear = (value: string) => (value.trim() ? Number(value) : null);

  const handleManualCreate = async () => {
    const validationError = validateForm(manualForm);
    if (validationError) {
      toast.error(validationError);
      return;
    }

    try {
      await createStudent({
        student_no: manualForm.student_no.trim(),
        tc_no: manualForm.tc_no.trim(),
        first_name: manualForm.first_name.trim(),
        last_name: manualForm.last_name.trim(),
        department_id: manualForm.department_id,
        class_year: parseClassYear(manualForm.class_year),
      });
      toast.success("Öğrenci eklendi");
      resetManualForm();
      await loadStudents();
    } catch (error) {
      const detail = extractDetailMessage(error);
      if (detail.toLowerCase().includes("zaten kayıtlı")) {
        toast.error("Aynı öğrenci zaten kayıtlı.");
        return;
      }
      toast.error(detail || "Öğrenci eklenemedi");
    }
  };

  const handleImportCsv = async () => {
    if (!csvFile) {
      toast.error("Lütfen bir CSV dosyası seçin");
      return;
    }

    try {
      setImporting(true);
      const result = await importStudentsCsv(csvFile);
      if (result.created.length > 0) {
        toast.success(`${result.created.length} öğrenci eklendi`);
      }
      if (result.skipped.length > 0) {
        toast.info(`${result.skipped.length} satır kaydedilmedi.`);
      }
      setCsvFile(null);
      await loadStudents();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "CSV yükleme başarısız");
    } finally {
      setImporting(false);
    }
  };

  const handleSaveEdit = async () => {
    if (!editingStudent) return;
    const validationError = validateForm(editForm);
    if (validationError) {
      toast.error(validationError);
      return;
    }

    try {
      await updateStudent(editingStudent.id, {
        student_no: editForm.student_no.trim(),
        tc_no: editForm.tc_no.trim(),
        first_name: editForm.first_name.trim(),
        last_name: editForm.last_name.trim(),
        department_id: editForm.department_id,
        class_year: parseClassYear(editForm.class_year),
      });
      toast.success("Öğrenci güncellendi");
      setEditingStudent(null);
      await loadStudents();
    } catch (error) {
      const detail = extractDetailMessage(error);
      if (detail.toLowerCase().includes("zaten kayıtlı")) {
        toast.error("Aynı öğrenci zaten kayıtlı.");
        return;
      }
      toast.error(detail || "Öğrenci güncellenemedi");
    }
  };

  const handleDeleteStudent = async () => {
    if (!deletingStudent) return;
    try {
      await deleteStudent(deletingStudent.id);
      toast.success("Öğrenci silindi");
      setDeletingStudent(null);
      await loadStudents();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Öğrenci silinemedi");
    }
  };

  const tableDepartmentName = (student: Student) =>
    student.department_name || departmentLookup.get(student.department_id || "")?.name || "—";

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(key);
    setSortDirection("asc");
  };

  const renderSortHeader = (label: string, key: SortKey) => (
    <button
      type="button"
      onClick={() => handleSort(key)}
      className="flex w-full items-center gap-1 text-left text-xs font-semibold text-foreground transition-colors hover:text-primary focus:outline-none"
    >
      <span className="whitespace-nowrap">{label}</span>
      <ChevronsUpDown
        className={`h-3.5 w-3.5 shrink-0 ${sortKey === key ? "text-primary" : "text-muted-foreground"}`}
      />
    </button>
  );

  return (
    <div className="flex h-full min-h-0 flex-col gap-3 overflow-hidden">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Öğrenciler</h1>
        <p className="text-sm text-muted-foreground">Öğrenci ekleyin ve mevcut kayıtları yönetin.</p>
      </div>

      <div className="grid shrink-0 gap-2.5 lg:grid-cols-[1.05fr_0.75fr]">
        <div className="rounded-xl border border-border bg-card p-3 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Plus className="h-4 w-4 text-primary" />
            Öğrenci Ekle
          </div>

            <div className="grid gap-2 sm:grid-cols-2">
            <input
              type="text"
              value={manualForm.student_no}
              onChange={(e) => setManualForm((current) => ({ ...current, student_no: e.target.value }))}
              placeholder="Öğrenci no"
              className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <input
              type="text"
              value={manualForm.tc_no}
              onChange={(e) => setManualForm((current) => ({ ...current, tc_no: e.target.value }))}
              placeholder="TC kimlik no"
              className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <input
              type="text"
              value={manualForm.first_name}
              onChange={(e) => setManualForm((current) => ({ ...current, first_name: e.target.value }))}
              placeholder="Ad"
              className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <input
              type="text"
              value={manualForm.last_name}
              onChange={(e) => setManualForm((current) => ({ ...current, last_name: e.target.value }))}
              placeholder="Soyad"
              className="w-full rounded-lg border border-input bg-background px-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <select
              value={manualForm.department_id}
              onChange={(e) => setManualForm((current) => ({ ...current, department_id: e.target.value }))}
              className="h-9 min-w-0 rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Bölüm seçin</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>

            <div className="flex items-center gap-2 w-full">
              <select
                value={manualForm.class_year}
                onChange={(e) => setManualForm((current) => ({ ...current, class_year: e.target.value }))}
                className="flex-1 h-9 min-w-0 rounded-lg border border-input bg-background px-3 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">Sınıf seçin</option>
                <option value="1">1. sınıf</option>
                <option value="2">2. sınıf</option>
                <option value="3">3. sınıf</option>
                <option value="4">4. sınıf</option>
              </select>
              <button
                onClick={handleManualCreate}
                className="inline-flex h-9 min-w-0 items-center justify-center rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground transition-all hover:brightness-110"
              >
                Kaydet
              </button>
            </div>
          </div>
        </div>

        <div className="rounded-xl border border-border bg-card p-3 space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold text-foreground">
            <Upload className="h-4 w-4 text-primary" />
            CSV ile Ekle
          </div>
          <p className="text-xs text-muted-foreground leading-relaxed">
            ogrenci no, tc, ad, soyad, bolum, sinif. Bölüm adı mevcut bölümlerle, sınıf 1-4 arasında olmalıdır.
          </p>
          <div className="flex items-center gap-2 rounded-lg border border-dashed border-border bg-background px-3 py-2">
            <FileUp className="h-4 w-4 text-muted-foreground" />
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setCsvFile(e.target.files?.[0] || null)}
              className="w-full text-sm text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary file:px-3 file:py-1.5 file:text-sm file:font-medium file:text-primary-foreground hover:file:brightness-110"
            />
          </div>
          <button
            onClick={handleImportCsv}
            disabled={!csvFile || importing}
            className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {importing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Upload className="h-4 w-4" />}
            {importing ? "Yükleniyor..." : "CSV Yükle"}
          </button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-border bg-card">
        <div className="flex shrink-0 flex-col gap-2 border-b border-border p-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Mevcut Öğrenciler</h2>
            <p className="text-xs text-muted-foreground">
              {students.length} kayıt{refreshing ? " güncelleniyor..." : ""}
            </p>
          </div>
          <div className="relative w-full sm:max-w-[17rem]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Öğrenci ara"
              className="w-full rounded-lg border border-input bg-background pl-9 pr-3 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Yükleniyor...
          </div>
        ) : filteredStudents.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <Users className="h-6 w-6 opacity-40" />
            <p>Henüz öğrenci eklenmemiş.</p>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-b-xl">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{renderSortHeader("Öğrenci No", "student_no")}</TableHead>
                  <TableHead>{renderSortHeader("TC", "tc_no")}</TableHead>
                  <TableHead>{renderSortHeader("Ad Soyad", "name")}</TableHead>
                  <TableHead>{renderSortHeader("Sınıf", "class_year")}</TableHead>
                  <TableHead>{renderSortHeader("Bölüm", "department")}</TableHead>
                  <TableHead className="text-right"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {paginatedStudents.map((student) => (
                  <TableRow key={student.id}>
                    <TableCell className="py-2">
                      <p className="font-medium text-foreground">{student.student_no}</p>
                    </TableCell>
                    <TableCell className="py-2 text-muted-foreground">{student.tc_no}</TableCell>
                    <TableCell className="py-2">
                      <div>
                        <p className="font-medium text-foreground">{student.first_name} {student.last_name}</p>
                      </div>
                    </TableCell>
                    <TableCell className="py-2 text-muted-foreground">
                      {student.class_year ? `${student.class_year}. sınıf` : "—"}
                    </TableCell>
                    <TableCell className="py-2">
                      <Badge variant="outline" className="rounded-full">
                        {tableDepartmentName(student)}
                      </Badge>
                    </TableCell>
                    <TableCell className="py-2">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => setEditingStudent(student)}
                          className="inline-flex items-center gap-1 rounded-lg bg-accent px-3 py-1 text-xs font-medium text-accent-foreground transition-colors hover:bg-accent/80"
                        >
                          <Pencil className="h-3.5 w-3.5" /> Düzenle
                        </button>
                        <button
                          onClick={() => setDeletingStudent(student)}
                          className="inline-flex items-center gap-1 rounded-lg px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                        >
                          <Trash2 className="h-3.5 w-3.5" /> Sil
                        </button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>

            <div className="mt-auto flex shrink-0 items-center justify-between border-t border-border px-3 py-2.5">
              <p className="text-xs text-muted-foreground">
                Sayfa {currentPage} / {totalPages}
              </p>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                  disabled={currentPage === 1}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                {Array.from({ length: totalPages }, (_, index) => index + 1).map((page) => (
                  <button
                    key={page}
                    type="button"
                    onClick={() => setCurrentPage(page)}
                    className={`inline-flex h-8 min-w-8 items-center justify-center rounded-md px-2 text-xs font-medium transition-colors ${
                      page === currentPage
                        ? "bg-primary text-primary-foreground"
                        : "border border-border text-muted-foreground hover:bg-muted/60"
                    }`}
                  >
                    {page}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setCurrentPage((prev) => Math.min(totalPages, prev + 1))}
                  disabled={currentPage === totalPages}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-border text-muted-foreground transition-colors hover:bg-muted/60 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          </div>
        )}
      </div>

      <Dialog open={Boolean(editingStudent)} onOpenChange={(open) => !open && setEditingStudent(null)}>
        <DialogContent className="sm:max-w-md py-3 px-4">
          <DialogHeader>
            <DialogTitle>Öğrenci Düzenle</DialogTitle>
          </DialogHeader>

            <div className="grid gap-2 sm:grid-cols-2">
            <input
              type="text"
              value={editForm.student_no}
              onChange={(e) => setEditForm((current) => ({ ...current, student_no: e.target.value }))}
              placeholder="Öğrenci no"
              className="w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <input
              type="text"
              value={editForm.tc_no}
              onChange={(e) => setEditForm((current) => ({ ...current, tc_no: e.target.value }))}
              placeholder="TC kimlik no"
              className="w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <input
              type="text"
              value={editForm.first_name}
              onChange={(e) => setEditForm((current) => ({ ...current, first_name: e.target.value }))}
              placeholder="Ad"
              className="w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <input
              type="text"
              value={editForm.last_name}
              onChange={(e) => setEditForm((current) => ({ ...current, last_name: e.target.value }))}
              placeholder="Soyad"
              className="w-full rounded-lg border border-input bg-background px-2 py-1.5 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            />
            
          </div>
          <div className="grid gap-1 sm:grid-cols-2 sm:items-end -mt-1">
            <select
              value={editForm.class_year}
              onChange={(e) => setEditForm((current) => ({ ...current, class_year: e.target.value }))}
              className="h-8 w-full rounded-lg border border-input bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Sınıf seçin</option>
              <option value="1">1. sınıf</option>
              <option value="2">2. sınıf</option>
              <option value="3">3. sınıf</option>
              <option value="4">4. sınıf</option>
            </select>

            <select
              value={editForm.department_id}
              onChange={(e) => setEditForm((current) => ({ ...current, department_id: e.target.value }))}
              className="h-8 w-full rounded-lg border border-input bg-background px-2 text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            >
              <option value="">Bölüm seçin</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </select>
          </div>

          <div className="flex items-center justify-end gap-2 mt-0">
            <button
              type="button"
              onClick={() => setEditingStudent(null)}
              className="inline-flex h-8 min-w-0 items-center justify-center gap-1 rounded-lg border border-border px-2 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
            >
              <X className="h-4 w-4" /> Vazgeç
            </button>
            <button
              type="button"
              onClick={handleSaveEdit}
              className="inline-flex h-8 min-w-0 items-center justify-center gap-1 rounded-lg bg-primary px-2 text-xs font-medium text-primary-foreground transition-all hover:brightness-110"
            >
              <Pencil className="h-4 w-4" /> Kaydet
            </button>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={Boolean(deletingStudent)} onOpenChange={(open) => !open && setDeletingStudent(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Öğrenci Kaydını Sil</DialogTitle>
          </DialogHeader>

          <p className="text-sm text-muted-foreground">
            {deletingStudent ? `"${deletingStudent.first_name} ${deletingStudent.last_name}" kaydini silmek istiyor musunuz?` : ""}
          </p>

          <DialogFooter className="gap-2 sm:gap-0">
            <button
              type="button"
              onClick={() => setDeletingStudent(null)}
              className="inline-flex items-center justify-center gap-2 rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/50 hover:text-foreground"
            >
              <X className="h-4 w-4" /> Vazgeç
            </button>
            <button
              type="button"
              onClick={handleDeleteStudent}
              className="inline-flex items-center justify-center gap-2 rounded-lg bg-destructive px-4 py-2 text-sm font-medium text-destructive-foreground transition-all hover:brightness-110"
            >
              <Trash2 className="h-4 w-4" /> Sil
            </button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

    </div>
  );
};

export default StudentsPanel;
