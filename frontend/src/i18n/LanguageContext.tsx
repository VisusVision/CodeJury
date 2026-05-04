import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from "react";
import trDict from "./tr.json";
import enDict from "./en.json";

// ─── Types ───
export type Language = "tr" | "en";

type Dict = Record<string, unknown>;

interface LanguageContextValue {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string) => string;
}

// ─── Helpers ───
const STORAGE_KEY = "codejury_lang";

const dictionaries: Record<Language, Dict> = { tr: trDict as unknown as Dict, en: enDict as unknown as Dict };

function resolveKey(dict: Dict, key: string): string {
  const parts = key.split(".");
  let current: unknown = dict;
  for (const part of parts) {
    if (current && typeof current === "object" && part in (current as Record<string, unknown>)) {
      current = (current as Record<string, unknown>)[part];
    } else {
      return key; // fallback to key itself
    }
  }
  return typeof current === "string" ? current : key;
}

// ─── Context ───
const LanguageContext = createContext<LanguageContextValue | null>(null);

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === "en" || stored === "tr") return stored;
    } catch {
      // ignore
    }
    return "tr";
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, language);
    } catch {
      // ignore
    }
    document.documentElement.lang = language;
  }, [language]);

  const setLanguage = useCallback((lang: Language) => {
    setLanguageState(lang);
  }, []);

  const t = useCallback(
    (key: string): string => resolveKey(dictionaries[language], key),
    [language],
  );

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
}

export function useTranslation() {
  const ctx = useContext(LanguageContext);
  if (!ctx) throw new Error("useTranslation must be used within LanguageProvider");
  return ctx;
}

// ─── Toggle Component ───
export function LanguageToggle({ className = "" }: { className?: string }) {
  const { language, setLanguage } = useTranslation();

  return (
    <div className={`inline-flex items-center rounded-full border border-border bg-card/80 backdrop-blur-sm p-0.5 text-xs font-medium shadow-sm ${className}`}>
      <button
        type="button"
        onClick={() => setLanguage("tr")}
        className={`px-2.5 py-1 rounded-full transition-all duration-200 ${
          language === "tr"
            ? "bg-primary text-primary-foreground shadow-sm"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        TR
      </button>
      <button
        type="button"
        onClick={() => setLanguage("en")}
        className={`px-2.5 py-1 rounded-full transition-all duration-200 ${
          language === "en"
            ? "bg-primary text-primary-foreground shadow-sm"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        EN
      </button>
    </div>
  );
}
