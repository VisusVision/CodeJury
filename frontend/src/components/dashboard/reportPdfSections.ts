interface ResourceRecommendation {
  title: string;
  url: string;
  reason: string;
  resourceType: "docs" | "tutorial" | "video" | "practice";
  priority: "high" | "medium";
}

interface PdfSectionInput {
  summary: string;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  resourceRecommendations: ResourceRecommendation[];
  language?: string;
}

const escapeHtml = (value: string) =>
  value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

const LABELS = {
  tr: {
    summary: "Genel Değerlendirme",
    strengths: "Güçlü Yönler",
    weaknesses: "Geliştirilmesi Gereken Yönler",
    recommendations: "Yapılacaklar / Öneriler",
    resources: "Öğrenci İçin Kaynak Önerileri",
    open: "Kaynağı aç",
    priorityHigh: "Yüksek Öncelik",
    priorityMedium: "Orta Öncelik",
  },
  en: {
    summary: "Overall Evaluation",
    strengths: "Strengths",
    weaknesses: "Areas to Improve",
    recommendations: "Next Steps",
    resources: "Recommended Resources",
    open: "Open resource",
    priorityHigh: "High Priority",
    priorityMedium: "Medium Priority",
  },
} as const;

function buildListSection(title: string, items: string[], accent: string): string {
  if (!items.length) return "";
  return `
    <div style="margin-top:10px;">
      <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">${title}</h2>
      <ul style="margin:0;padding-left:18px;color:#374151;font-size:11px;line-height:1.5;">
        ${items.map((item) => `<li style="margin:0 0 4px 0;"><span style="color:${accent};font-weight:600;">•</span> ${escapeHtml(item)}</li>`).join("")}
      </ul>
    </div>
  `;
}

export function buildPdfReportSectionsHtml({
  summary,
  strengths,
  weaknesses,
  recommendations,
  resourceRecommendations,
  language = "tr",
}: PdfSectionInput): string {
  const copy = language === "en" ? LABELS.en : LABELS.tr;
  const summarySection = summary.trim()
    ? `
      <div style="margin-top:10px;">
        <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">${copy.summary}</h2>
        <div style="padding:10px 12px;border-radius:10px;background:#f3f4f6;color:#1f2937;font-size:11px;line-height:1.55;">
          ${escapeHtml(summary)}
        </div>
      </div>
    `
    : "";

  const resourcesSection = resourceRecommendations.length
    ? `
      <div style="margin-top:10px;">
        <h2 style="font-size:13px;font-weight:800;color:#111827;margin:0 0 6px 0;">${copy.resources}</h2>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          ${resourceRecommendations.map((item) => `
            <div style="border:1px solid #dbeafe;border-radius:10px;background:#f8fbff;padding:10px;">
              <div style="display:flex;justify-content:space-between;gap:6px;align-items:flex-start;">
                <div style="font-size:11px;font-weight:800;color:#111827;line-height:1.35;">${escapeHtml(item.title)}</div>
                <div style="font-size:9px;font-weight:700;color:${item.priority === "high" ? "#b45309" : "#1d4ed8"};white-space:nowrap;">
                  ${item.priority === "high" ? copy.priorityHigh : copy.priorityMedium}
                </div>
              </div>
              <div style="font-size:10px;color:#2563eb;margin-top:4px;word-break:break-all;">${escapeHtml(item.url)}</div>
              <div style="font-size:11px;color:#374151;line-height:1.45;margin-top:6px;">${escapeHtml(item.reason)}</div>
              <div style="font-size:10px;color:#6b7280;margin-top:6px;">${escapeHtml(copy.open)} • ${escapeHtml(item.resourceType)}</div>
            </div>
          `).join("")}
        </div>
      </div>
    `
    : "";

  return [
    summarySection,
    buildListSection(copy.strengths, strengths, "#059669"),
    buildListSection(copy.weaknesses, weaknesses, "#dc2626"),
    buildListSection(copy.recommendations, recommendations, "#1d4ed8"),
    resourcesSection,
  ].join("");
}
