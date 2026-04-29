import { useState, useEffect } from "react";
import { toast } from "sonner";
import { Mail, Lock, Save } from "lucide-react";
import { updateTeacherEmail, updateTeacherPassword } from "@/services/api";

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

const SettingsPanel = ({ teacher, onTeacherUpdate }: SettingsPanelProps) => {
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
      sessionStorage.setItem("teacher", JSON.stringify(updated));
      setCurrentEmail(updated.email);
      toast.success("E-posta başarıyla güncellendi.");
      setNewEmail("");
    } catch (err: any) {
      toast.error(err.message || "E-posta güncellenemedi");
    } finally {
      setSavingEmail(false);
    }
  };

  const handlePasswordChange = async () => {
    if (!newPassword || !confirmPassword) return;
    if (newPassword !== confirmPassword) {
      toast.error("Şifreler eşleşmiyor");
      return;
    }
    if (newPassword.length < 6) {
      toast.error("Şifre en az 6 karakter olmalı");
      return;
    }
    try {
      setSavingPassword(true);
      await updateTeacherPassword(teacher.id, {
        current_password: currentPassword || undefined,
        new_password: newPassword,
      });
      toast.success("Şifre başarıyla güncellendi");
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: any) {
      toast.error(err.message || "Şifre güncellenemedi");
    } finally {
      setSavingPassword(false);
    }
  };

  return (
    <>
      <h1 className="text-2xl font-bold tracking-tight text-foreground mb-1">Ayarlar</h1>
      <p className="text-sm text-muted-foreground mb-5">E-posta ve şifre ayarlarınızı güncelleyin.</p>

      <div className="grid gap-4 max-w-lg">
        {/* Email */}
        <div className="p-4 rounded-xl border border-border bg-card space-y-3">
          <div className="flex items-center gap-2 text-foreground font-semibold text-sm">
            <Mail className="h-4 w-4 text-primary" />
            E-posta Değiştir
          </div>
          <div className="text-xs text-muted-foreground">
            Mevcut e-posta: <span className="font-medium text-foreground">{currentEmail}</span>
          </div>
          <input
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            placeholder="Yeni e-posta adresi"
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={handleEmailChange}
            disabled={savingEmail || !newEmail.trim()}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {savingEmail ? "Kaydediliyor..." : "E-postayı Güncelle"}
          </button>
        </div>

        {/* Password */}
        <div className="p-4 rounded-xl border border-border bg-card space-y-3">
          <div className="flex items-center gap-2 text-foreground font-semibold text-sm">
            <Lock className="h-4 w-4 text-primary" />
            Şifre Değiştir
          </div>
          <input
            type="password"
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            placeholder="Mevcut şifre (opsiyonel)"
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="Yeni şifre"
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <input
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            placeholder="Yeni şifre (tekrar)"
            className="w-full px-3 py-1.5 rounded-lg border border-input bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
          <button
            onClick={handlePasswordChange}
            disabled={savingPassword || !newPassword || !confirmPassword}
            className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all disabled:opacity-50"
          >
            <Save className="h-3.5 w-3.5" />
            {savingPassword ? "Kaydediliyor..." : "Şifreyi Güncelle"}
          </button>
        </div>
      </div>
    </>
  );
};

export default SettingsPanel;
