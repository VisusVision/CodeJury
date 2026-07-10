import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Mail, Lock, Save } from "lucide-react";
import { updateTeacherEmail, updateTeacherPassword } from "@/services/api";
import { useTranslation } from "@/i18n/LanguageContext";
import { useAuth } from "../../auth/AuthContext";

interface Teacher {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
}

interface SettingsPanelProps {
  teacher: Teacher;
  onTeacherUpdate: (teacher: Teacher) => void;
}

const getErrorMessage = (error: unknown, fallback: string) =>
  error instanceof Error ? error.message : fallback;

const SettingsPanel = ({ teacher, onTeacherUpdate }: SettingsPanelProps) => {
  const { t } = useTranslation();
  const { refreshSession } = useAuth();
  const [currentEmail, setCurrentEmail] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingEmail, setSavingEmail] = useState(false);
  const [savingPassword, setSavingPassword] = useState(false);

  useEffect(() => {
    setCurrentEmail(teacher.email || "");
  }, [teacher.email]);

  const handleEmailChange = async () => {
    if (!newEmail.trim()) return;
    try {
      setSavingEmail(true);
      const updated = await updateTeacherEmail(teacher.id, newEmail.trim());
      onTeacherUpdate(updated);
      void refreshSession();
      setCurrentEmail(updated.email);
      toast.success(t("faculty.settings.emailUpdateSuccess"));
      setNewEmail("");
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, t("faculty.settings.emailUpdateError")));
    } finally {
      setSavingEmail(false);
    }
  };

  const handlePasswordChange = async () => {
    if (!currentPassword.trim()) {
      toast.error(t("faculty.settings.currentPasswordRequired"));
      return;
    }
    if (!newPassword.trim() || !confirmPassword.trim()) {
      toast.error(t("faculty.settings.fillAllFields"));
      return;
    }
    if (newPassword !== confirmPassword) {
      toast.error(t("faculty.settings.passwordMismatch"));
      return;
    }
    if (newPassword.length < 6) {
      toast.error(t("faculty.settings.passwordTooShort"));
      return;
    }
    try {
      setSavingPassword(true);
      await updateTeacherPassword(teacher.id, {
        current_password: currentPassword.trim(),
        new_password: newPassword,
      });
      toast.success(t("faculty.settings.passwordUpdateSuccess"));
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: unknown) {
      toast.error(getErrorMessage(err, t("faculty.settings.passwordUpdateError")));
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <div className="grid gap-4 max-w-lg mt-4">
        {/* Email */}
        <div className="p-4 rounded-xl border border-border bg-card space-y-3">
          <div className="flex items-center gap-2 text-foreground font-semibold text-sm">
            <Mail className="h-4 w-4 text-primary" />
            {t("faculty.settings.changeEmail")}
          </div>
          <div className="text-xs text-muted-foreground">
            {t("faculty.settings.currentEmail")}: <span className="font-medium text-foreground">{currentEmail}</span>
          </div>
          <input
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder={t("faculty.settings.newEmailPlaceholder")}
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={handleEmailChange}
            disabled={savingEmail || !newEmail.trim()}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {savingEmail ? t("common.saving") || "Kaydediliyor..." : t("faculty.settings.updateEmailBtn")}
          </button>
        </div>

        {/* Password */}
        <div className="p-4 rounded-xl border border-border bg-card space-y-3">
          <div className="flex items-center gap-2 text-foreground font-semibold text-sm">
            <Lock className="h-4 w-4 text-primary" />
            {t("faculty.settings.changePassword")}
          </div>
          <input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            placeholder={t("faculty.settings.currentPasswordPlaceholder")}
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder={t("faculty.settings.newPasswordPlaceholder")}
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder={t("faculty.settings.confirmPasswordPlaceholder")}
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={handlePasswordChange}
            disabled={savingPassword || !currentPassword.trim() || !newPassword || !confirmPassword}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {savingPassword ? t("common.saving") || "Kaydediliyor..." : t("faculty.settings.updatePasswordBtn")}
          </button>
        </div>
    </div>
  );
};

export default SettingsPanel;
