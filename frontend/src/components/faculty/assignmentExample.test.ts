import { describe, expect, test } from "vitest";
import { buildAssignmentExample, descriptionWithExample, exampleBody } from "./assignmentExample";
import { splitAssignmentDescription } from "@/lib/assignmentDescription";

describe("buildAssignmentExample", () => {
  test("creates a log-specific example instead of a generic file note", () => {
    const example = buildAssignmentExample(
      "Sistem Log Ozetleme Araci",
      "Bir log dosyasini okuyup seviye bazli ozet cikaracak CLI araci gelistirin. Bozuk satirlari raporlayin.",
    );

    expect(example).toContain("ornek_log.txt");
    expect(example).toContain("Beklenen konsol ciktisi");
    expect(example).toContain("Bozuk satir");
  });

  test("creates an API example using assignment nouns", () => {
    const example = buildAssignmentExample(
      "Kutuphanede Odunc Takip API",
      "FastAPI ile kitap, uye ve odunc kaydi icin ekleme listeleme ve iade endpointleri yazin.",
    );

    expect(example).toContain("/books");
    expect(example).toContain("/loans");
    expect(example).toContain("404");
  });

  test("does not use generic items placeholders for API examples", () => {
    const example = buildAssignmentExample(
      "Randevu Takip API",
      "Doktor, hasta ve randevu kayitlari icin REST endpointleri yazin. Uygun olmayan saatlerde acik hata donsun.",
    );

    expect(example).not.toContain("/items");
    expect(example).not.toContain("Ornek Kayit");
    expect(example).toContain("/randevular");
    expect(example).toContain("hasta");
  });

  test("creates an OOP example with concrete objects", () => {
    const example = buildAssignmentExample(
      "Kitap Kutuphanesi Sistemi",
      "Kitap, uye ve kutuphane siniflariyla OOP tabanli bir odunc alma-iade sistemi yazin.",
    );

    expect(example).toContain("Kitap");
    expect(example).toContain("Uye");
    expect(example).toContain("stok: 0");
  });

  test("creates a data/math example from domain terms", () => {
    const example = buildAssignmentExample(
      "Titrasyon ve pH Olcum Analizi",
      "Kimya laboratuvari icin titrasyon ve pH olcumlerini CSV dosyasindan okuyup raporlayan uygulama yazin.",
    );

    expect(example).toContain("ph_olcumleri.csv");
    expect(example).toContain("pH");
    expect(example).toContain("Beklenen rapor");
  });

  test("stores edited example output under a dedicated example output heading", () => {
    const description = descriptionWithExample(
      "Log dosyasini analiz eden CLI yazin.",
      "INFO: 1\nERROR: 2",
    );

    expect(description).toBe("Log dosyasini analiz eden CLI yazin.\n\nOrnek Cikti:\nINFO: 1\nERROR: 2");
  });

  test("does not append a duplicate generic example section", () => {
    const description = "Kisa odev.\n\nOrnek: Var olan ornek.";

    expect(descriptionWithExample(description, "Ornek: Yeni ornek.")).toBe(description);
  });

  test("does not duplicate an existing example output section", () => {
    const description = descriptionWithExample(
      "CSV raporu uretin.\n\nOrnek Cikti:\nToplam: 3",
      "Toplam: 4",
    );

    expect(description).toBe("CSV raporu uretin.\n\nOrnek Cikti:\nToplam: 3");
  });

  test("student assignment split recognizes example output headings", () => {
    const result = splitAssignmentDescription("API olusturun.\n\nOrnek Cikti:\nGET /items -> 200 []");

    expect(result.body).toBe("API olusturun.");
    expect(result.expectedOutput).toBe("GET /items -> 200 []");
  });

  test("strips example headings for display", () => {
    expect(exampleBody("Örnek: Beklenen cikti:\nSonuc: basarili")).toBe("Beklenen cikti:\nSonuc: basarili");
    expect(exampleBody("Ornek Cikti:\nSonuc: basarili")).toBe("Sonuc: basarili");
  });
});
