import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { fetchHealth, registerTeacher } from "@/services/api";
import { useAuth } from "../auth/AuthContext";
import { GraduationCap, User, BookOpen } from "lucide-react";
import { useTranslation, LanguageToggle } from "@/i18n/LanguageContext";

type Tab = "student" | "teacher";

const getErrorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

const Login = () => {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("student");

  // Student state
  const [studentNo, setStudentNo] = useState("");
  const [studentPassword, setStudentPassword] = useState("");

  // Teacher state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const navigate = useNavigate();
  const { loginStudent, loginTeacher } = useAuth();

  useEffect(() => {
    void fetchHealth().then((health) => {
      setDemoMode(Boolean(health?.demo_mode));
    });
  }, []);

  const handleStudentLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!studentNo.trim() || !studentPassword.trim()) {
      setError(t("login.studentNotFound"));
      return;
    }
    setLoading(true);
    try {
      await loginStudent(studentNo.trim(), studentPassword.trim());
      navigate("/courses");
    } catch (err) {
      console.error(err);
      setError(getErrorMessage(err, t("login.studentNotFound")));
    } finally {
      setLoading(false);
    }
  };

  const handleTeacherLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!email.trim() || !password.trim()) {
      setError(t("login.networkError"));
      return;
    }
    setLoading(true);
    try {
      if (isSignUp) {
        if (!firstName.trim() || !lastName.trim()) {
          setError(t("login.networkError"));
          setLoading(false);
          return;
        }
        await registerTeacher({
          first_name: firstName.trim(),
          last_name: lastName.trim(),
          email: email.trim(),
          password: password.trim(),
        });
        setError(t("common.success") + "! " + t("login.loginLink"));
        setIsSignUp(false);
      } else {
        await loginTeacher(email.trim(), password.trim());
        navigate("/faculty/dashboard");
      }
    } catch (err: unknown) {
      console.error(err);
      setError(getErrorMessage(err, t("login.networkError")));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4 relative">
      {/* Language Toggle - top right */}
      <div className="absolute top-4 right-4 z-10">
        <LanguageToggle />
      </div>

      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-8">
          <div className="h-12 w-12 rounded-xl bg-primary flex items-center justify-center mb-3">
            <GraduationCap className="h-6 w-6 text-primary-foreground" />
          </div>
          <h1 className="text-xl font-bold text-foreground">{t("login.title")}</h1>
          <p className="text-sm text-muted-foreground mt-1">{t("login.subtitle")}</p>
        </div>

        {demoMode && (
          <div className="mb-6 rounded-lg border border-primary/20 bg-primary/5 px-3 py-3 text-xs text-muted-foreground space-y-2">
            <p className="font-semibold text-foreground">{t("login.demoModeTitle")}</p>
            <p>{t("login.demoModeHint")}</p>
            <div className="space-y-1 font-mono text-[11px]">
              <p>
                <span className="text-foreground/80">{t("login.demoTeacher")}:</span> demo@agentgrade.local / demo123
              </p>
              <p>
                <span className="text-foreground/80">{t("login.demoStudent")}:</span> 20240001 / 11111111111
              </p>
            </div>
            <div className="flex flex-wrap gap-2 pt-1">
              <button
                type="button"
                onClick={() => {
                  setTab("student");
                  setStudentNo("20240001");
                  setStudentPassword("11111111111");
                  setError("");
                }}
                className="rounded-md border border-border bg-background px-2 py-1 text-[11px] hover:bg-muted/50"
              >
                {t("login.demoFillStudent")}
              </button>
              <button
                type="button"
                onClick={() => {
                  setTab("teacher");
                  setEmail("demo@agentgrade.local");
                  setPassword("demo123");
                  setError("");
                }}
                className="rounded-md border border-border bg-background px-2 py-1 text-[11px] hover:bg-muted/50"
              >
                {t("login.demoFillTeacher")}
              </button>
            </div>
          </div>
        )}

        {/* Tabs */}
        <div className="flex rounded-lg border border-border bg-muted p-1 mb-6">
          <button
            onClick={() => { setTab("student"); setError(""); }}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-md text-sm font-medium transition-all ${
              tab === "student"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <User className="h-4 w-4" />
            {t("login.studentTab")}
          </button>
          <button
            onClick={() => { setTab("teacher"); setError(""); }}
            className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-md text-sm font-medium transition-all ${
              tab === "teacher"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <BookOpen className="h-4 w-4" />
            {t("login.teacherTab")}
          </button>
        </div>

        {/* Student Form */}
        {tab === "student" && (
          <form onSubmit={handleStudentLogin} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">{t("login.studentNo")}</label>
              <input
                type="text"
                value={studentNo}
                onChange={(e) => setStudentNo(e.target.value)}
                placeholder={t("login.studentNoPlaceholder")}
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">{t("login.password")}</label>
              <input
                type="password"
                value={studentPassword}
                onChange={(e) => setStudentPassword(e.target.value)}
                placeholder="•••••••••••"
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {error && (
              <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-lg">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
            >
              {loading ? t("login.loggingIn") : t("login.loginButton")}
            </button>

            <button
              type="button"
              tabIndex={-1}
              aria-hidden="true"
              className="w-full text-sm opacity-0 pointer-events-none"
            >
              {t("login.noAccount")} {t("login.registerLink")}
            </button>
          </form>
        )}

        {/* Teacher Form */}
        {tab === "teacher" && (
          <form onSubmit={handleTeacherLogin} className="space-y-4">
            {isSignUp && (
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">{t("login.firstName")}</label>
                  <input
                    type="text"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1.5">{t("login.lastName")}</label>
                  <input
                    type="text"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
            )}

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">{t("login.email")}</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t("login.emailPlaceholder")}
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">{t("login.password")}</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="•••••••••••"
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>

            {error && (
              <p className="text-sm text-destructive bg-destructive/10 px-3 py-2 rounded-lg">{error}</p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
            >
              {loading ? t("login.loggingIn") : isSignUp ? t("login.registerButton") : t("login.loginButton")}
            </button>

            <button
              type="button"
              onClick={() => { setIsSignUp(!isSignUp); setError(""); }}
              className="w-full text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              {isSignUp ? `${t("login.hasAccount")} ${t("login.loginLink")}` : `${t("login.noAccount")} ${t("login.registerLink")}`}
            </button>
          </form>
        )}
      </div>
    </div>
  );
};

export default Login;
