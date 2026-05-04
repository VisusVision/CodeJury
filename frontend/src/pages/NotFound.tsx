import { useNavigate } from "react-router-dom";
import { useTranslation } from "@/i18n/LanguageContext";

const NotFound = () => {
  const navigate = useNavigate();
  const { t } = useTranslation();

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-foreground mb-2">404</h1>
        <p className="text-muted-foreground mb-4">{t("notFound.message")}</p>
        <button
          onClick={() => navigate("/login")}
          className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:brightness-110 transition-all"
        >
          {t("notFound.backHome")}
        </button>
      </div>
    </div>
  );
};

export default NotFound;
