import { useEffect, useRef, useState } from "react";
import { X, Send, Sparkles, Pencil, Check, ThumbsUp, ThumbsDown, CalendarIcon, Clock, BookOpen, Loader2 } from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { format } from "date-fns";
import { tr as trLocale } from "date-fns/locale";
import { enUS as enLocale } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { createAssignment, fetchAssignmentSuggestions, generateAssignmentExample, type AssignmentSuggestion, type AssignmentDifficulty } from "@/services/api";
import { toast } from "sonner";
import { useTranslation } from "@/i18n/LanguageContext";
import { buildAssignmentExample, descriptionWithExample, exampleBody } from "./assignmentExample";

interface Course { id: string; name: string; code: string; class_year?: number | null }
interface Props {
  open: boolean;
  onClose: () => void;
  courses: Course[];
  teacherId: string;
  onCreated: () => void;
}

type Step =
  | "greet"
  | "askHint"
  | "pickDifficulty"
  | "loadingSuggestions"
  | "pickSuggestion"
  | "rateDesc"
  | "askDate"
  | "askTime"
  | "confirm"
  | "done";

interface ChatMsg {
  id: string;
  from: "bot" | "user";
  text?: string;
  node?: React.ReactNode;
}

const formatCourseHint = (course: Course | null, hint: string) => {
  const trimmed = hint.trim();
  const parts: string[] = [];
  if (course) {
    parts.push(`${course.name} (${course.code})`);
    if (course.class_year) {
      parts.push(`${course.class_year}.sinif`);
    }
  }
  if (trimmed) {
    parts.push(trimmed);
  }
  return parts.join(", ");
};

const detectDomain = (raw: string): string | null => {
  const h = (raw || "").toLowerCase();
  if (/(sınıf|sinif|class|nesne|oop|kalıtım|kalitim|miras|encapsulation|arayüz|arayuz)/.test(h)) return "oop";
  if (/(ağaç|agac|liste|linked|kuyruk|stack|yığın|yigin|hash|graf|heap|bst)/.test(h)) return "ds";
  if (/(matematik|matem|math|sayısal|sayisal|matris|vektör|vektor|polinom|integral|türev|turev|denklem)/.test(h)) return "math";
  if (/(fizik|physics|simülasyon|simulasyon|kinematik|dinamik)/.test(h)) return "physics";
  if (/(web|rest|api|fastapi|flask|django|http|frontend|backend)/.test(h)) return "web";
  if (/(oyun|game|pygame|labirent)/.test(h)) return "game";
  if (/(yapay zeka|yapay zekâ|machine learning|\bml\b|veri bilimi|regresyon|sınıflandırma|siniflandirma|kümeleme|kumeleme)/.test(h)) return "ml";
  return null;
};

const commentaryForHint = (hint: string): string => {
  const domain = detectDomain(hint);
  switch (domain) {
    case "oop":
      return "Tamamdır, **OOP** odaklı 5 öneri çıkardım. Her biri sınıflar, kalıtım veya kompozisyon üzerine. Beğendiğini seçebilir ya da daha spesifik yazabilirsin (örn. 'banka hesabı sınıfı', 'oyun karakteri kalıtımı').";
    case "ds":
      return "Veri yapıları için 5 öneri hazır. İstersen yapı adını yazıp daha da daraltabilirsin (örn. 'AVL ağacı', 'çift yönlü bağlı liste').";
    case "math":
      return "Matematik üzerine programlama önerileri çıkardım. Daha spesifik istersen yazabilirsin (örn. 'matris çarpımı', 'sayısal türev', 'denklem çözücü').";
    case "physics":
      return "Fizik simülasyonu önerileri burada. Daraltmak için yazabilirsin (örn. 'sarkaç', 'eğik atış').";
    case "web":
      return "Mini servis/API önerileri çıkardım. Hangi domain — kütüphane, blog, görev listesi? Yazarsan yenilerim.";
    case "game":
      return "Oyun mekaniklerine yönelik 5 öneri. Tür belirtirsen daraltırım (örn. 'platform', 'bulmaca', 'yılan').";
    case "ml":
      return "Veri bilimi/ML önerilerini hazırladım. Veri seti veya algoritma yazarsan daraltırım (örn. 'iris sınıflandırma', 'k-means kümeleme').";
    default:
      return `"${hint}" için 5 öneri çıkardım. Beğendiğini seç ya da konuyu daraltıp tekrar yaz — hatırlıyorum.`;
  }
};

const normalizeLongText = (raw: string) => raw.replace(/\s+/g, " ").trim();

const isDetailedAssignmentBrief = (raw: string) => {
  const text = normalizeLongText(raw).toLowerCase();
  const words = text.match(/[\p{L}\p{N}_]+/gu) ?? [];
  const hits = [
    "yaz",
    "geliştir",
    "gelistir",
    "oluştur",
    "olustur",
    "tasarla",
    "uygula",
    "teslim",
    "rapor",
    "test",
    "hata",
    "kenar",
    "dosya",
    "api",
    "endpoint",
    "sınıf",
    "sinif",
    "fonksiyon",
    "metot",
  ].filter((token) => text.includes(token)).length;
  return words.length >= 22 && hits >= 2;
};

const titleFromLongBrief = (raw: string, language: string = "tr") => {
  const firstLine = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) ?? raw;
  const cleaned = firstLine
    .replace(/^(başlık|baslik|ödev|odev)\s*[:-]\s*/i, "")
    .replace(/^(öğrenciler|ogrenciler|öğrenci|ogrenci)\s+/i, "")
    .split(/[.!?]\s+/)[0]
    .trim();
  if (!cleaned) return language === "tr" ? "Yeni Ödev" : "New Assignment";
  return cleaned.length > 90 ? `${cleaned.slice(0, 87).trim()}...` : cleaned;
};

const AssignmentChatbot = ({ open, onClose, courses, teacherId, onCreated }: Props) => {
  const { t, language } = useTranslation();
  const dateLocale = language === "tr" ? trLocale : enLocale;
  void teacherId;
  const [step, setStep] = useState<Step>("greet");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [course, setCourse] = useState<Course | null>(null);
  const [hintInput, setHintInput] = useState("");
  const [hintMemo, setHintMemo] = useState("");
  const [difficultyLevel, setDifficultyLevel] = useState<AssignmentDifficulty | null>(null);
  const [suggestions, setSuggestions] = useState<AssignmentSuggestion[]>([]);
  const [selectedSuggestionId, setSelectedSuggestionId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [assignmentExample, setAssignmentExample] = useState("");
  const [assignmentExampleLoading, setAssignmentExampleLoading] = useState(false);
  const [assignmentExampleTouched, setAssignmentExampleTouched] = useState(false);
  const suggestionsInFlightRef = useRef(false);
  const [editingDesc, setEditingDesc] = useState(false);
  const [date, setDate] = useState<Date | undefined>();
  const [time, setTime] = useState("23:59");
  const [submitting, setSubmitting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const addMsg = (m: Omit<ChatMsg, "id">) =>
    setMessages((prev) => [...prev, { ...m, id: crypto.randomUUID() }]);

  useEffect(() => {
    if (open && messages.length === 0) {
      addMsg({ from: "bot", text: t("chatbot.greet") });
      addMsg({
        from: "bot",
        node: (
          <div className="flex flex-wrap gap-2 mt-1">
            {courses.length === 0 ? (
              <span className="text-xs text-muted-foreground italic">{t("chatbot.noCourses")}</span>
            ) : (
              courses.map((c) => (
                <button
                  key={c.id}
                  onClick={() => handleCourseSelect(c)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-all hover:scale-105"
                >
                  <BookOpen className="h-3 w-3" />
                  {c.name} <span className="opacity-60">({c.code}) - {c.class_year ? `${c.class_year}. ${t("chatbot.classLabel")}` : t("chatbot.general")}</span>
                </button>
              ))
            )}
          </div>
        ),
      });
    }
    if (!open) {
      setTimeout(() => {
        setStep("greet");
        setMessages([]);
        setCourse(null);
        setHintInput("");
        setHintMemo("");
        setDifficultyLevel(null);
        setSuggestions([]);
        setSelectedSuggestionId(null);
        setTitle("");
        setDescription("");
        setAssignmentExample("");
        setAssignmentExampleLoading(false);
        setAssignmentExampleTouched(false);
        setEditingDesc(false);
        setDate(undefined);
        setTime("23:59");
      }, 300);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, suggestions, description, step]);

  useEffect(() => {
    if (!open || !title.trim() || !description.trim()) {
      if (!assignmentExampleTouched) {
        setAssignmentExample("");
      }
      setAssignmentExampleLoading(false);
      return;
    }

    if (assignmentExampleTouched) {
      setAssignmentExampleLoading(false);
      return;
    }

    const fallback = buildAssignmentExample(title, description);
    setAssignmentExample(fallback);
    let cancelled = false;
    setAssignmentExampleLoading(true);
    const timer = window.setTimeout(() => {
      generateAssignmentExample({
        assignment_title: title,
        assignment_description: description,
        course_hint: formatCourseHint(course, ""),
      })
        .then((result) => {
          if (!cancelled && result.example?.trim()) {
            setAssignmentExample(result.example);
          }
        })
        .catch(() => {
          if (!cancelled) {
            setAssignmentExample(fallback);
          }
        })
        .finally(() => {
          if (!cancelled) {
            setAssignmentExampleLoading(false);
          }
        });
    }, 450);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, title, description, assignmentExampleTouched]);

  const handleCourseSelect = (c: Course) => {
    setCourse(c);
    addMsg({ from: "user", text: `${c.name} (${c.code}) - ${c.class_year ? `${c.class_year}. ${t("chatbot.classLabel")}` : t("chatbot.general")}` });
    addMsg({
      from: "bot",
      text: t("chatbot.topicPrompt"),
    });
    setStep("askHint");
  };

  const loadSuggestions = async (hint: string, difficulty: AssignmentDifficulty, preferFresh = false) => {
    if (suggestionsInFlightRef.current) return;
    suggestionsInFlightRef.current = true;
    setStep("loadingSuggestions");
    setSuggestions([]);
    setSelectedSuggestionId(null);
    addMsg({ from: "bot", text: t("chatbot.fetchingSuggestions") });
    try {
      const fullHint = formatCourseHint(course, hint);
      const { suggestions: list } = await fetchAssignmentSuggestions(
        fullHint || undefined,
        5,
        difficulty,
        preferFresh,
        language,
      );
      setSuggestions(list);
      if (!list.length) {
        addMsg({ from: "bot", text: t("chatbot.noSuggestions") });
        setStep("pickSuggestion");
        return;
      }
      addMsg({ from: "bot", text: commentaryForHint(hint) });
      setStep("pickSuggestion");
    } catch (e) {
      const msg = e instanceof Error ? e.message : t("assignments.loadError");
      toast.error(msg);
      addMsg({ from: "bot", text: `${t("common.error")}: ${msg}.` });
      setStep("pickSuggestion");
    } finally {
      suggestionsInFlightRef.current = false;
    }
  };

  const handleDifficultyPick = (d: AssignmentDifficulty) => {
    setDifficultyLevel(d);
    const label = d === "easy" ? `🟢 ${t("chatbot.easy")}` : d === "medium" ? `🟡 ${t("chatbot.medium")}` : `🔴 ${t("chatbot.hard")}`;
    addMsg({ from: "user", text: label });
    void loadSuggestions(hintMemo, d);
  };

  const handleHintSubmit = () => {
    const text = hintInput.trim();
    if (!text) return;
    addMsg({ from: "user", text });
    setHintInput("");

    const previous = hintMemo.trim();
    let nextHint: string;
    if (!previous) {
      nextHint = text;
    } else if (previous.toLowerCase().includes(text.toLowerCase()) || text.toLowerCase().includes(previous.toLowerCase())) {
      nextHint = text;
    } else {
      nextHint = `${previous}, ${text}`;
      addMsg({
        from: "bot",
        text:
          difficultyLevel != null
            ? `${language === "tr" ? "İpucunu güncelliyorum" : "Updating hint"}: "${nextHint}". ${t("chatbot.preparing")}`
            : `${language === "tr" ? "İpucunu güncelliyorum" : "Updating hint"}: "${nextHint}". ${language === "tr" ? "Tekrar zorluk seçin." : "Pick difficulty again."}`,
      });
    }
    setHintMemo(nextHint);

    if (!difficultyLevel) {
      addMsg({
        from: "bot",
        text: t("chatbot.difficultyPrompt"),
      });
      setStep("pickDifficulty");
      return;
    }
    void loadSuggestions(nextHint, difficultyLevel);
  };

  const refreshSuggestions = () => {
    addMsg({ from: "user", text: t("chatbot.newSuggestions") });
    addMsg({ from: "bot", text: t("chatbot.newSuggestionsMsg") });
    void loadSuggestions(hintMemo, difficultyLevel ?? "medium", true);
  };

  const handlePickSuggestion = (s: AssignmentSuggestion) => {
    setSelectedSuggestionId(s.id);
    setAssignmentExampleTouched(false);
    setTitle(s.title);
    setDescription(s.description);
    addMsg({ from: "user", text: `${language === "tr" ? "Seçtim" : "Selected"}: ${s.title}` });
    addMsg({
      from: "bot",
      text: `${language === "tr" ? "Güzel seçim!" : "Great choice!"} "${s.title}" ${language === "tr" ? "detaylarını aşağıda hazırladım. Başlığı veya metni düzenleyebilir, beğenirsen onaylayıp tarihe geçebilirsin. Beğenmezsen listeye dönüp başka birini seçebilirsin." : "details are ready below. You can edit the title or description, approve it if you like, or go back to the list."}`,
    });
    setEditingDesc(false);
    setStep("rateDesc");
  };

  const handleRateDesc = (good: boolean) => {
    if (good) {
      addMsg({ from: "user", text: t("chatbot.liked") });
      addMsg({ from: "bot", text: t("chatbot.likedMsg") });
      setStep("askDate");
    } else {
      addMsg({ from: "user", text: t("chatbot.disliked") });
      addMsg({
        from: "bot",
        text: t("chatbot.dislikedMsg"),
      });
      setSelectedSuggestionId(null);
      setStep("pickSuggestion");
    }
  };

  const handleBackToList = () => {
    setSelectedSuggestionId(null);
    addMsg({ from: "bot", text: t("chatbot.dislikedMsg") });
    setStep("pickSuggestion");
  };

  const handleDatePick = (d: Date | undefined) => {
    if (!d) return;
    setDate(d);
    addMsg({ from: "user", text: format(d, "dd MMM yyyy", { locale: dateLocale }) });
    addMsg({ from: "bot", text: t("chatbot.selectTime") });
    setStep("askTime");
  };

  const handleTimeConfirm = () => {
    addMsg({ from: "user", text: time });
    const dueLabel = `${format(date!, "dd MMM yyyy", { locale: dateLocale })} - ${time}`;
    addMsg({
      from: "bot",
      text: `${t("chatbot.confirmCreate")}\n\n• ${t("chatbot.course")}: ${course?.name}${course?.class_year ? ` (${course.class_year}. ${t("chatbot.classLabel")})` : ""}\n• ${t("chatbot.titleLabel")}: ${title}\n• ${t("chatbot.deadline")}: ${dueLabel}`,
    });
    setStep("confirm");
  };

  const handleConfirm = async (yes: boolean) => {
    if (!yes) {
      addMsg({ from: "user", text: t("chatbot.noConfirm") });
      addMsg({ from: "bot", text: t("chatbot.noCancelMsg") });
      setStep("done");
      return;
    }
    if (!course || !date) {
      toast.error("Eksik bilgi");
      return;
    }
    addMsg({ from: "user", text: t("chatbot.yesConfirm") });
    addMsg({ from: "bot", text: t("chatbot.securityCheck") });
    setSubmitting(true);
    try {
      const [h, m] = time.split(":").map(Number);
      const d = new Date(date);
      d.setHours(h, m, 0, 0);
      const normalizedTitle = (title || "Yeni Ödev").replace(/\b\w+/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
      await createAssignment({
        name: normalizedTitle,
        description: descriptionWithExample(description, exampleBody(assignmentExample).trim() || buildAssignmentExample(normalizedTitle, description)),
        course_id: course.id,
        due_date: d.toISOString(),
      });
      toast.success(t("chatbot.createdSuccessShort"));
      addMsg({ from: "bot", text: t("chatbot.createdSuccess") });
      setStep("done");
      onCreated();
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Bir hata oluştu";
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 w-[420px] max-w-[calc(100vw-2rem)] h-[640px] max-h-[calc(100vh-3rem)] flex flex-col rounded-2xl border border-border bg-card shadow-2xl animate-scale-in overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-primary via-primary to-purple-600 text-primary-foreground">
        <div className="flex items-center gap-2.5">
          <div className="text-2xl drop-shadow-md">🤖</div>
          <div>
            <p className="text-sm font-semibold leading-tight">{t("chatbot.title")}</p>
            <p className="text-[10px] opacity-80 flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> {t("chatbot.online")}
            </p>
          </div>
        </div>
        <button onClick={onClose} className="p-1 rounded-md hover:bg-white/15 transition-colors">
          <X className="h-4 w-4" />
        </button>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4 space-y-3 bg-muted/30">
        {messages.map((m) => (
          <div key={m.id} className={cn("flex animate-fade-in", m.from === "user" ? "justify-end" : "justify-start")}>
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm whitespace-pre-wrap",
                m.from === "user"
                  ? "bg-primary text-primary-foreground rounded-br-sm"
                  : "bg-card border border-border text-foreground rounded-bl-sm shadow-sm",
              )}
            >
              {m.text}
              {m.node}
            </div>
          </div>
        ))}

        {step === "pickDifficulty" && (
          <div className="flex justify-start animate-fade-in">
            <div className="max-w-[92%] w-full rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm p-3 space-y-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                <Sparkles className="h-3 w-3 text-primary" /> {t("chatbot.difficultyTitle")}
              </p>
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  onClick={() => handleDifficultyPick("easy")}
                  className="w-full text-left rounded-xl border border-emerald-500/35 bg-emerald-500/10 px-3 py-2.5 hover:bg-emerald-500/15 transition-colors"
                >
                  <span className="text-xs font-semibold text-emerald-800 dark:text-emerald-200">{t("chatbot.easy")}</span>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                    {t("chatbot.easyDesc")}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => handleDifficultyPick("medium")}
                  className="w-full text-left rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 hover:bg-amber-500/15 transition-colors"
                >
                  <span className="text-xs font-semibold text-amber-900 dark:text-amber-100">{t("chatbot.medium")}</span>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                    {t("chatbot.mediumDesc")}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => handleDifficultyPick("hard")}
                  className="w-full text-left rounded-xl border border-red-500/35 bg-red-500/10 px-3 py-2.5 hover:bg-red-500/15 transition-colors"
                >
                  <span className="text-xs font-semibold text-red-900 dark:text-red-100">{t("chatbot.hard")}</span>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                    {t("chatbot.hardDesc")}
                  </p>
                </button>
              </div>
            </div>
          </div>
        )}

        {step === "loadingSuggestions" && (
          <div className="flex justify-start animate-fade-in">
            <div className="rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm px-3.5 py-2 text-xs text-muted-foreground flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> {t("chatbot.preparing")}
            </div>
          </div>
        )}

        {step === "pickSuggestion" && suggestions.length > 0 && (
          <div className="flex justify-start animate-fade-in">
            <div className="max-w-[92%] w-full rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-primary" /> {t("chatbot.aiSuggestions")}
                </span>
                <button
                  onClick={refreshSuggestions}
                  className="text-[10px] font-medium text-primary hover:underline"
                >
                  {t("chatbot.refreshSuggestions")}
                </button>
              </div>
              <div className="divide-y divide-border max-h-[320px] overflow-y-auto">
                {suggestions.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => handlePickSuggestion(s)}
                    className={cn(
                      "w-full text-left px-3 py-2 hover:bg-muted/40 transition-colors space-y-1",
                      selectedSuggestionId === s.id ? "bg-primary/5" : "",
                    )}
                  >
                    <p className="text-xs font-semibold text-foreground leading-snug">{s.title}</p>
                    {s.summary && (
                      <p className="text-[11px] text-muted-foreground leading-relaxed">{s.summary}</p>
                    )}
                  </button>
                ))}
              </div>
            </div>
          </div>
        )}

        {step === "rateDesc" && description && (
          <div className="flex justify-start animate-fade-in">
            <div className="max-w-[92%] w-full rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-primary" /> {t("chatbot.selectedAssignment")} {editingDesc ? `· ${t("chatbot.editing")}` : ""}
                </span>
              </div>
              <div className="px-3 pt-2">
                {editingDesc ? (
                  <input
                    autoFocus
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder={t("chatbot.assignmentTitle")}
                    className="w-full px-2 py-1 text-xs font-semibold rounded border border-primary/40 bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                ) : (
                  <p className="text-xs font-semibold text-foreground">{title}</p>
                )}
              </div>
              {editingDesc ? (
                <div className="space-y-2 px-3 pt-2">
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={8}
                    placeholder={t("chatbot.assignmentDesc")}
                    className="w-full px-2 py-2 text-xs rounded border border-primary/40 bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y"
                  />
                  <div className="rounded-lg border border-primary/20 bg-primary/5 px-2.5 py-2">
                    <div className="mb-1.5 flex items-center gap-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">Örnek Çıktı</p>
                      {assignmentExampleLoading && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
                    </div>
                    <textarea
                      value={exampleBody(assignmentExample)}
                      onChange={(e) => {
                        setAssignmentExampleTouched(true);
                        setAssignmentExample(e.target.value);
                      }}
                      rows={5}
                      placeholder={language === "tr" ? "Programın üretmesi beklenen konsol çıktısı, dosya raporu veya API yanıt örneği..." : "Expected console output, file report, or API response example..."}
                      className="w-full resize-y rounded-md border border-primary/20 bg-background px-2 py-2 text-xs leading-relaxed text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                    />
                  </div>
                </div>
              ) : (
                <div className="px-3 py-2 space-y-2">
                  <p className="text-xs text-foreground leading-relaxed whitespace-pre-wrap">{description}</p>
                  <div className="rounded-lg border border-primary/20 bg-primary/5 px-2.5 py-2">
                    <div className="flex items-center gap-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">Örnek Çıktı</p>
                      {assignmentExampleLoading && <Loader2 className="h-3 w-3 animate-spin text-primary" />}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap text-xs text-foreground leading-relaxed">{exampleBody(assignmentExample)}</p>
                  </div>
                </div>
              )}
              {!editingDesc ? (
                <div className="flex gap-2 px-3 pb-3 pt-1">
                  <button
                    onClick={() => handleRateDesc(true)}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-600 text-xs font-medium hover:bg-emerald-500/25 transition-colors"
                  >
                    <ThumbsUp className="h-3 w-3" /> {t("chatbot.approve")}
                  </button>
                  <button
                    onClick={() => setEditingDesc(true)}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-colors"
                  >
                    <Pencil className="h-3 w-3" /> {t("chatbot.editBtn")}
                  </button>
                  <button
                    onClick={handleBackToList}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-muted text-foreground text-xs font-medium hover:bg-muted/70 transition-colors"
                  >
                    <ThumbsDown className="h-3 w-3" /> {t("chatbot.backToList")}
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 px-3 pb-3 pt-1">
                  <button
                    onClick={() => {
                      setEditingDesc(false);
                      addMsg({ from: "bot", text: t("chatbot.editSaved") });
                    }}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500 text-white text-xs font-medium hover:brightness-110 transition-all"
                  >
                    <Check className="h-3 w-3" /> {t("chatbot.finishEdit")}
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {step === "askDate" && (
          <div className="flex justify-start animate-fade-in">
            <div className="rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm p-2">
              <Popover>
                <PopoverTrigger asChild>
                  <button className="flex items-center gap-2 px-3 py-2 rounded-lg bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-colors">
                    <CalendarIcon className="h-3.5 w-3.5" />
                    {date ? format(date, "dd MMM yyyy", { locale: dateLocale }) : t("chatbot.selectDate")}
                  </button>
                </PopoverTrigger>
                <PopoverContent className="w-auto p-0" align="start">
                  <Calendar
                    mode="single"
                    selected={date}
                    onSelect={handleDatePick}
                    disabled={(d) => d < new Date(new Date().setHours(0, 0, 0, 0))}
                    initialFocus
                    className={cn("p-3 pointer-events-auto")}
                  />
                </PopoverContent>
              </Popover>
            </div>
          </div>
        )}

        {step === "askTime" && (
          <div className="flex justify-start animate-fade-in">
            <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm p-2">
              <div className="flex items-center gap-1.5 px-2 py-1.5 rounded-lg border border-input">
                <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                <input
                  type="time"
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                  className="bg-transparent text-foreground text-xs focus:outline-none w-20"
                />
              </div>
              <button
                onClick={handleTimeConfirm}
                className="px-3 py-1.5 rounded-lg bg-primary text-primary-foreground text-xs font-medium hover:brightness-110 transition-all"
              >
                {t("common.continue")}
              </button>
            </div>
          </div>
        )}

        {step === "confirm" && (
          <div className="flex justify-start gap-2 animate-fade-in pl-1">
            <button
               disabled={submitting}
              onClick={() => handleConfirm(true)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500 text-white text-xs font-medium hover:brightness-110 transition-all disabled:opacity-60"
            >
              <Check className="h-3 w-3" /> {submitting ? t("chatbot.creating") : t("chatbot.yesConfirmBtn")}
            </button>
            <button
               disabled={submitting}
              onClick={() => handleConfirm(false)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-muted text-foreground text-xs font-medium hover:bg-muted/80 transition-colors"
            >
              <X className="h-3 w-3" /> {t("chatbot.noConfirm")}
            </button>
          </div>
        )}
      </div>

      {(step === "askHint" || step === "pickSuggestion" || step === "rateDesc") && (
        <div className="border-t border-border p-3 bg-card">
          {step !== "askHint" && hintMemo && (
            <div className="mb-2 flex items-center gap-2 text-[11px] text-muted-foreground">
              <span className="px-2 py-0.5 rounded-full bg-muted">{t("chatbot.currentHint")}: {hintMemo}</span>
              <button
                type="button"
                onClick={() => {
                  setHintMemo("");
                  setDifficultyLevel(null);
                   setSuggestions([]);
                  setSelectedSuggestionId(null);
                  addMsg({ from: "bot", text: t("chatbot.resetHintMsg") });
                  setStep("askHint");
                }}
                className="text-[11px] text-primary hover:underline"
              >
                {t("chatbot.resetHint")}
              </button>
            </div>
          )}
          <div className="flex items-end gap-2">
            <textarea
              autoFocus
              value={hintInput}
              onChange={(e) => setHintInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleHintSubmit();
                }
              }}
               placeholder={
                step === "askHint"
                  ? t("chatbot.hintPlaceholder")
                  : t("chatbot.hintNarrowPlaceholder")
              }
              rows={hintInput.length > 120 ? 4 : 2}
              className="flex-1 max-h-32 resize-y px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
             <button
              onClick={handleHintSubmit}
              className="p-2 rounded-lg bg-primary text-primary-foreground hover:brightness-110 transition-all"
              title={t("chatbot.send")}
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}

      {step === "done" && (
        <div className="border-t border-border p-3 bg-card">
           <button
            onClick={onClose}
            className="w-full px-3 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all"
          >
            {t("common.close")}
          </button>
        </div>
      )}
    </div>
  );
};

export default AssignmentChatbot;
