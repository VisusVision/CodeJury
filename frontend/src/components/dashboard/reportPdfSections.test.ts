import { describe, expect, test } from "vitest";

import { buildPdfReportSectionsHtml } from "./reportPdfSections";

describe("buildPdfReportSectionsHtml", () => {
  test("renders summary, weaknesses and resource cards", () => {
    const html = buildPdfReportSectionsHtml({
      summary: "Kod calisiyor ama odev beklentisiyle tam uyumlu degil.",
      strengths: ["CSV okuma dogru."],
      weaknesses: ["Odevde istenen CLI akisi eksik."],
      recommendations: ["Komut satiri argumanlarini ekleyin."],
      resourceRecommendations: [
        {
          title: "Python argparse",
          url: "https://docs.python.org/3/library/argparse.html",
          reason: "CLI arguman eksigini tamamlamak icin.",
          resourceType: "docs",
          priority: "high",
        },
      ],
    });

    expect(html).toContain("Genel Değerlendirme");
    expect(html).toContain("Geliştirilmesi Gereken Yönler");
    expect(html).toContain("Öğrenci İçin Kaynak Önerileri");
    expect(html).toContain("Python argparse");
    expect(html).toContain("https://docs.python.org/3/library/argparse.html");
  });

  test("renders resource cards with stretch layout styles for stable PDF alignment", () => {
    const html = buildPdfReportSectionsHtml({
      summary: "",
      strengths: [],
      weaknesses: [],
      recommendations: [],
      resourceRecommendations: [
        {
          title: "Uzun baslikli kaynak",
          url: "https://example.com/really/long/path/that/should/wrap/cleanly/in/pdf/output",
          reason: "Kart icerigi farkli uzunluklarda olsa da alt satirlar hizali kalmali.",
          resourceType: "tutorial",
          priority: "medium",
        },
      ],
    });

    expect(html).toContain("align-items:stretch");
    expect(html).toContain("height:100%;box-sizing:border-box;display:flex;flex-direction:column");
    expect(html).toContain("overflow-wrap:anywhere");
  });

  test("omits optional sections when arrays are empty", () => {
    const html = buildPdfReportSectionsHtml({
      summary: "",
      strengths: [],
      weaknesses: [],
      recommendations: [],
      resourceRecommendations: [],
    });

    expect(html).not.toContain("Öğrenci İçin Kaynak Önerileri");
    expect(html).not.toContain("Güçlü Yönler");
  });
});
