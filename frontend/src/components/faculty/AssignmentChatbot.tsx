import { useEffect, useRef, useState } from "react";
import { X, Send, Sparkles, Pencil, Check, ThumbsUp, ThumbsDown, CalendarIcon, Clock, BookOpen, Loader2 } from "lucide-react";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { format } from "date-fns";
import { tr } from "date-fns/locale";
import { cn } from "@/lib/utils";
import { createAssignment, fetchAssignmentSuggestions, type AssignmentSuggestion, type AssignmentDifficulty } from "@/services/api";
import { toast } from "sonner";

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

const titleFromLongBrief = (raw: string) => {
  const firstLine = raw
    .split(/\r?\n/)
    .map((line) => line.trim())
    .find(Boolean) ?? raw;
  const cleaned = firstLine
    .replace(/^(başlık|baslik|ödev|odev)\s*[:\-]\s*/i, "")
    .replace(/^(öğrenciler|ogrenciler|öğrenci|ogrenci)\s+/i, "")
    .split(/[.!?]\s+/)[0]
    .trim();
  if (!cleaned) return "Yeni Ödev";
  return cleaned.length > 90 ? `${cleaned.slice(0, 87).trim()}...` : cleaned;
};

const AssignmentChatbot = ({ open, onClose, courses, teacherId, onCreated }: Props) => {
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
  const [editingDesc, setEditingDesc] = useState(false);
  const [date, setDate] = useState<Date | undefined>();
  const [time, setTime] = useState("23:59");
  const [submitting, setSubmitting] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const addMsg = (m: Omit<ChatMsg, "id">) =>
    setMessages((prev) => [...prev, { ...m, id: crypto.randomUUID() }]);

  useEffect(() => {
    if (open && messages.length === 0) {
      addMsg({ from: "bot", text: "Merhaba! 👋 Hangi derse ödev oluşturmak istersiniz?" });
      addMsg({
        from: "bot",
        node: (
          <div className="flex flex-wrap gap-2 mt-1">
            {courses.length === 0 ? (
              <span className="text-xs text-muted-foreground italic">Henüz ders eklenmemiş.</span>
            ) : (
              courses.map((c) => (
                <button
                  key={c.id}
                  onClick={() => handleCourseSelect(c)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-all hover:scale-105"
                >
                  <BookOpen className="h-3 w-3" />
                  {c.name} <span className="opacity-60">({c.code}) - {c.class_year ? `${c.class_year}. sınıf` : "Genel"}</span>
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

  const handleCourseSelect = (c: Course) => {
    setCourse(c);
    addMsg({ from: "user", text: `${c.name} (${c.code}) - ${c.class_year ? `${c.class_year}. sınıf` : "Genel"}` });
    addMsg({
      from: "bot",
      text: 'Harika seçim! 🎯 Hangi konu üzerinde çalışmak istersiniz? (örn. matematik, linked list). Konuyu yazdıktan sonra **kolay / orta / zor** seçmenizi isteyeceğim.',
    });
    setStep("askHint");
  };

  const loadSuggestions = async (hint: string, difficulty: AssignmentDifficulty, preferFresh = false) => {
    setStep("loadingSuggestions");
    setSuggestions([]);
    setSelectedSuggestionId(null);
    addMsg({ from: "bot", text: "Sizin için yapay zekâdan ödev önerileri alıyorum... ✨" });
    try {
      const fullHint = formatCourseHint(course, hint);
      const { suggestions: list } = await fetchAssignmentSuggestions(
        fullHint || undefined,
        5,
        difficulty,
        preferFresh,
      );
      setSuggestions(list);
      if (!list.length) {
        addMsg({ from: "bot", text: "Üzgünüm, öneri üretemedim. İpucunuzu biraz daha detaylandırır mısınız?" });
        setStep("pickSuggestion");
        return;
      }
      addMsg({ from: "bot", text: commentaryForHint(hint) });
      setStep("pickSuggestion");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Öneriler alınamadı";
      toast.error(msg);
      addMsg({ from: "bot", text: `Bir sorun oluştu: ${msg}. Tekrar deneyebilirsiniz.` });
      setStep("pickSuggestion");
    }
  };

  const handleDifficultyPick = (d: AssignmentDifficulty) => {
    setDifficultyLevel(d);
    const label = d === "easy" ? "🟢 Kolay" : d === "medium" ? "🟡 Orta" : "🔴 Zor";
    addMsg({ from: "user", text: label });
    void loadSuggestions(hintMemo, d);
  };

  const handleHintSubmit = () => {
    const text = hintInput.trim();
    if (!text) return;
    addMsg({ from: "user", text });
    setHintInput("");

    if (!hintMemo.trim() && isDetailedAssignmentBrief(text)) {
      const draftTitle = titleFromLongBrief(text);
      const draftDescription = normalizeLongText(text);
      setHintMemo(draftTitle);
      setDifficultyLevel(null);
      setSuggestions([]);
      setSelectedSuggestionId("direct-brief");
      setTitle(draftTitle);
      setDescription(draftDescription);
      setEditingDesc(false);
      addMsg({
        from: "bot",
        text:
          "Uzun metni doğrudan ödev taslağı olarak anladım. Başlık ve açıklamayı hazırladım; istersen düzenleyebilir, uygunsa tarihe geçebiliriz.",
      });
      setStep("rateDesc");
      return;
    }

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
            ? `İpucunu güncelliyorum: "${nextHint}". Yeni öneriler hazırlanıyor…`
            : `İpucunu güncelliyorum: "${nextHint}". Tekrar zorluk seçin.`,
      });
    }
    setHintMemo(nextHint);

    if (!difficultyLevel) {
      addMsg({
        from: "bot",
        text:
          "**Zorluk düzeyi:** Kolay seçersen gerçekten kısıtlı bir ödev (tek dosya / birkaç kısa fonksiyon) üretilir; orta tipik bir ödev; zor çok parçalı ve daha seçici kabul kriterleri ister. Aşağıdan birini seçin.",
      });
      setStep("pickDifficulty");
      return;
    }
    void loadSuggestions(nextHint, difficultyLevel);
  };

  const refreshSuggestions = () => {
    addMsg({ from: "user", text: "🔁 Yeni öneriler" });
    addMsg({ from: "bot", text: "Aynı ipucu ve zorlukla yeni 5 öneri hazırlıyorum…" });
    void loadSuggestions(hintMemo, difficultyLevel ?? "medium", true);
  };

  const handlePickSuggestion = (s: AssignmentSuggestion) => {
    setSelectedSuggestionId(s.id);
    setTitle(s.title);
    setDescription(s.description);
    addMsg({ from: "user", text: `Seçtim: ${s.title}` });
    addMsg({
      from: "bot",
      text: `Güzel seçim! "${s.title}" detaylarını aşağıda hazırladım. Başlığı veya metni düzenleyebilir, beğenirsen onaylayıp tarihe geçebilirsin. Beğenmezsen listeye dönüp başka birini seçebilirsin.`,
    });
    setEditingDesc(false);
    setStep("rateDesc");
  };

  const handleRateDesc = (good: boolean) => {
    if (good) {
      addMsg({ from: "user", text: "👍 Beğendim" });
      addMsg({ from: "bot", text: "Süper! Şimdi ödevin son teslim tarihini seçelim. 📅" });
      setStep("askDate");
    } else {
      addMsg({ from: "user", text: "👎 Bu olmadı" });
      addMsg({
        from: "bot",
        text: "Tamam, listeye geri dönüyorum. Başka bir öneri seçebilir veya altta yeni bir konu yazıp listeyi yenileyebilirsin.",
      });
      setSelectedSuggestionId(null);
      setStep("pickSuggestion");
    }
  };

  const handleBackToList = () => {
    setSelectedSuggestionId(null);
    addMsg({ from: "bot", text: "Listeye döndüm. İstersen başka bir öneri seç ya da altta yeni ipucu yaz." });
    setStep("pickSuggestion");
  };

  const handleDatePick = (d: Date | undefined) => {
    if (!d) return;
    setDate(d);
    addMsg({ from: "user", text: format(d, "dd MMM yyyy", { locale: tr }) });
    addMsg({ from: "bot", text: "Şimdi son teslim saatini belirleyin. ⏰" });
    setStep("askTime");
  };

  const handleTimeConfirm = () => {
    addMsg({ from: "user", text: time });
    const dueLabel = `${format(date!, "dd MMM yyyy", { locale: tr })} - ${time}`;
    addMsg({
      from: "bot",
      text: `Tamamdır! 📋 Aşağıdaki ödevi oluşturmak istediğinizi onaylıyor musunuz?\n\n• Ders: ${course?.name}${course?.class_year ? ` (${course.class_year}. sınıf)` : ""}\n• Başlık: ${title}\n• Son Teslim: ${dueLabel}`,
    });
    setStep("confirm");
  };

  const handleConfirm = async (yes: boolean) => {
    if (!yes) {
      addMsg({ from: "user", text: "❌ Hayır" });
      addMsg({ from: "bot", text: "Anladım, ödev oluşturulmadı. İstediğinizde tekrar başlayabilirsiniz. 👋" });
      setStep("done");
      return;
    }
    if (!course || !date) {
      toast.error("Eksik bilgi");
      return;
    }
    addMsg({ from: "user", text: "✅ Evet, onaylıyorum" });
    addMsg({ from: "bot", text: "Ödev Güvenlik Ajanı kayıt öncesi son kontrolü yapıyor..." });
    setSubmitting(true);
    try {
      const [h, m] = time.split(":").map(Number);
      const d = new Date(date);
      d.setHours(h, m, 0, 0);
      await createAssignment({
        name: title || "Yeni Ödev",
        description,
        course_id: course.id,
        due_date: d.toISOString(),
      });
      toast.success("Ödev oluşturuldu! 🎉");
      addMsg({ from: "bot", text: "Ödev başarıyla oluşturuldu! 🎉 Listede görebilirsiniz." });
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
            <p className="text-sm font-semibold leading-tight">Ödev Asistanı</p>
            <p className="text-[10px] opacity-80 flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" /> AI ile çevrimiçi
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
                <Sparkles className="h-3 w-3 text-primary" /> Zorluk
              </p>
              <div className="flex flex-col gap-2">
                <button
                  type="button"
                  onClick={() => handleDifficultyPick("easy")}
                  className="w-full text-left rounded-xl border border-emerald-500/35 bg-emerald-500/10 px-3 py-2.5 hover:bg-emerald-500/15 transition-colors"
                >
                  <span className="text-xs font-semibold text-emerald-800 dark:text-emerald-200">Kolay</span>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                    Küçük kapsam — birkaç kısa fonksiyon, basit matematik/tekrar kodu (örn. factorial, küçük N).
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => handleDifficultyPick("medium")}
                  className="w-full text-left rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-2.5 hover:bg-amber-500/15 transition-colors"
                >
                  <span className="text-xs font-semibold text-amber-900 dark:text-amber-100">Orta</span>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                    Tipik homework — birkaç modül fonksiyon veya küçük sınıf yapısı, biraz veri yapısı veya nümerik adım.
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => handleDifficultyPick("hard")}
                  className="w-full text-left rounded-xl border border-red-500/35 bg-red-500/10 px-3 py-2.5 hover:bg-red-500/15 transition-colors"
                >
                  <span className="text-xs font-semibold text-red-900 dark:text-red-100">Zor</span>
                  <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                    Çok parçalı — kenar örnekler, ek senaryolar, karşılaştırmalı yöntem veya daha ağır algoritma beklentisi.
                  </p>
                </button>
              </div>
            </div>
          </div>
        )}

        {step === "loadingSuggestions" && (
          <div className="flex justify-start animate-fade-in">
            <div className="rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm px-3.5 py-2 text-xs text-muted-foreground flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" /> Öneriler hazırlanıyor…
            </div>
          </div>
        )}

        {step === "pickSuggestion" && suggestions.length > 0 && (
          <div className="flex justify-start animate-fade-in">
            <div className="max-w-[92%] w-full rounded-2xl rounded-bl-sm border border-border bg-card shadow-sm overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 bg-muted/50 border-b border-border">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground flex items-center gap-1">
                  <Sparkles className="h-3 w-3 text-primary" /> AI Önerileri
                </span>
                <button
                  onClick={refreshSuggestions}
                  className="text-[10px] font-medium text-primary hover:underline"
                >
                  Yeniden öner
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
                  <Sparkles className="h-3 w-3 text-primary" /> Seçilen ödev {editingDesc ? "· Düzenleniyor" : ""}
                </span>
              </div>
              <div className="px-3 pt-2">
                {editingDesc ? (
                  <input
                    autoFocus
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="Ödev başlığı"
                    className="w-full px-2 py-1 text-xs font-semibold rounded border border-primary/40 bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                ) : (
                  <p className="text-xs font-semibold text-foreground">{title}</p>
                )}
              </div>
              {editingDesc ? (
                <div className="px-3 pt-2">
                  <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={8}
                    placeholder="Ödev açıklaması — istediğin gibi düzenleyebilirsin"
                    className="w-full px-2 py-2 text-xs rounded border border-primary/40 bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring resize-y"
                  />
                </div>
              ) : (
                <p className="px-3 py-2 text-xs text-foreground leading-relaxed whitespace-pre-wrap">{description}</p>
              )}
              {!editingDesc ? (
                <div className="flex gap-2 px-3 pb-3 pt-1">
                  <button
                    onClick={() => handleRateDesc(true)}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500/15 text-emerald-600 text-xs font-medium hover:bg-emerald-500/25 transition-colors"
                  >
                    <ThumbsUp className="h-3 w-3" /> İyi, devam
                  </button>
                  <button
                    onClick={() => setEditingDesc(true)}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-primary/10 text-primary text-xs font-medium hover:bg-primary/20 transition-colors"
                  >
                    <Pencil className="h-3 w-3" /> Düzenle
                  </button>
                  <button
                    onClick={handleBackToList}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-muted text-foreground text-xs font-medium hover:bg-muted/70 transition-colors"
                  >
                    <ThumbsDown className="h-3 w-3" /> Listeye dön
                  </button>
                </div>
              ) : (
                <div className="flex gap-2 px-3 pb-3 pt-1">
                  <button
                    onClick={() => {
                      setEditingDesc(false);
                      addMsg({ from: "bot", text: "Düzenleme kaydedildi. Hazırsan onaylayabilirsin." });
                    }}
                    className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-lg bg-emerald-500 text-white text-xs font-medium hover:brightness-110 transition-all"
                  >
                    <Check className="h-3 w-3" /> Düzenlemeyi bitir
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
                    {date ? format(date, "dd MMM yyyy", { locale: tr }) : "Tarih seçin"}
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
                Devam
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
              <Check className="h-3 w-3" /> {submitting ? "Oluşturuluyor..." : "Evet, onayla"}
            </button>
            <button
              disabled={submitting}
              onClick={() => handleConfirm(false)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg bg-muted text-foreground text-xs font-medium hover:bg-muted/80 transition-colors"
            >
              <X className="h-3 w-3" /> Hayır
            </button>
          </div>
        )}
      </div>

      {(step === "askHint" || step === "pickSuggestion" || step === "rateDesc") && (
        <div className="border-t border-border p-3 bg-card">
          {step !== "askHint" && hintMemo && (
            <div className="mb-2 flex items-center gap-2 text-[11px] text-muted-foreground">
              <span className="px-2 py-0.5 rounded-full bg-muted">Mevcut ipucu: {hintMemo}</span>
              <button
                type="button"
                onClick={() => {
                  setHintMemo("");
                  setDifficultyLevel(null);
                  setSuggestions([]);
                  setSelectedSuggestionId(null);
                  addMsg({ from: "bot", text: "İpucunu sıfırladım. Yeni baştan konu yaz, lütfen." });
                  setStep("askHint");
                }}
                className="text-[11px] text-primary hover:underline"
              >
                Sıfırla
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
                  ? "Konu, anahtar kelime veya uzun ödev açıklaması yazın..."
                  : "Daraltmak için yaz (örn. 'matris çarpımı', 'AVL ağacı')..."
              }
              rows={hintInput.length > 120 ? 4 : 2}
              className="flex-1 max-h-32 resize-y px-3 py-2 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
            <button
              onClick={handleHintSubmit}
              className="p-2 rounded-lg bg-primary text-primary-foreground hover:brightness-110 transition-all"
              title="Gönder"
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
            Kapat
          </button>
        </div>
      )}
    </div>
  );
};

export default AssignmentChatbot;
