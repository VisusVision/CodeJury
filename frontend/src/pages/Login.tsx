import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { loginStudent, loginTeacher, registerTeacher } from "@/services/api";
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
  const [tcNo, setTcNo] = useState("");

  // Teacher state
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [isSignUp, setIsSignUp] = useState(false);
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleStudentLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!studentNo.trim() || !tcNo.trim()) {
      setError(t("login.studentNotFound"));
      return;
    }
    setLoading(true);
    try {
      const student = await loginStudent(studentNo.trim(), tcNo.trim());
      if (!student) {
        setError(t("login.studentNotFound"));
        setLoading(false);
        return;
      }
      sessionStorage.setItem("student", JSON.stringify(student));
      navigate("/courses");
    } catch (err) {
      console.error(err);
      setError(t("login.networkError"));
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
        const teacher = await loginTeacher(email.trim(), password.trim());
        sessionStorage.setItem("teacher", JSON.stringify(teacher));
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
                placeholder="Örn: 2021001"
                className="w-full px-3 py-2.5 rounded-lg border border-input bg-background text-foreground text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-foreground mb-1.5">{t("login.tcNo")}</label>
              <input
                type="password"
                value={tcNo}
                onChange={(e) => setTcNo(e.target.value)}
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
                placeholder="ornek@universite.edu.tr"
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
