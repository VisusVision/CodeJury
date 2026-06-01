import { describe, expect, test } from "vitest";
import { splitAssignmentDescription } from "./assignmentDescription";

describe("splitAssignmentDescription", () => {
  test("separates expected output from the assignment body", () => {
    const result = splitAssignmentDescription(
      [
        "Dosyadan ogrenci notlarini okuyun.",
        "Ortalama ve harf notu hesaplayin.",
        "",
        "Beklenen cikti:",
        "Ortalama: 82.50",
        "Harf notu: BA",
      ].join("\n"),
    );

    expect(result.body).toBe("Dosyadan ogrenci notlarini okuyun.\nOrtalama ve harf notu hesaplayin.");
    expect(result.expectedOutput).toBe("Ortalama: 82.50\nHarf notu: BA");
  });

  test("supports English expected output headings", () => {
    const result = splitAssignmentDescription("Build the CLI.\n\nExpected output:\nOK: 2 rows");

    expect(result.body).toBe("Build the CLI.");
    expect(result.expectedOutput).toBe("OK: 2 rows");
  });

  test("supports example output headings", () => {
    const result = splitAssignmentDescription("Rapor API'si yazin.\n\nOrnek Cikti:\nGET /rapor -> 200");

    expect(result.body).toBe("Rapor API'si yazin.");
    expect(result.expectedOutput).toBe("GET /rapor -> 200");
  });

  test("supports Turkish expected output headings with dotted characters", () => {
    const result = splitAssignmentDescription("CLI olusturun.\n\nBeklenen çıktı:\nTamam: 2 satir");

    expect(result.body).toBe("CLI olusturun.");
    expect(result.expectedOutput).toBe("Tamam: 2 satir");
  });

  test("supports uppercase Turkish expected output headings with indentation", () => {
    const result = splitAssignmentDescription("Rapor olusturun.\n\n  BEKLENEN ÇIKTI:\nToplam: 3");

    expect(result.body).toBe("Rapor olusturun.");
    expect(result.expectedOutput).toBe("Toplam: 3");
  });

  test("keeps expected output formatting intact", () => {
    const result = splitAssignmentDescription(
      "CSV dosyasini isleyin.\n\nBeklenen çıktı:\nSatir 1: OK\n  - detay korunur\nSatir 2: HATA",
    );

    expect(result.expectedOutput).toBe("Satir 1: OK\n  - detay korunur\nSatir 2: HATA");
  });

  test("moves console output sections into the expected output panel", () => {
    const result = splitAssignmentDescription(
      [
        "Kullanicidan bir log dosyasini okutun.",
        "Parola karmasikligini analiz edin.",
        "Konsol çıktısı: Parola Analizi Sonuçları:",
        "Parola1: 12345678 (Uzunluk: 8, Karmaşıklık: Düşük)",
        "Parola2: Admin!2023 (Uzunluk: 11, Karmaşıklık: Yüksek)",
      ].join("\n"),
    );

    expect(result.body).toBe("Kullanicidan bir log dosyasini okutun.\nParola karmasikligini analiz edin.");
    expect(result.expectedOutput).toBe(
      "Parola Analizi Sonuçları:\nParola1: 12345678 (Uzunluk: 8, Karmaşıklık: Düşük)\nParola2: Admin!2023 (Uzunluk: 11, Karmaşıklık: Yüksek)",
    );
  });

  test("keeps the full description when no expected output section exists", () => {
    const result = splitAssignmentDescription("Kisa odev aciklamasi.");

    expect(result.body).toBe("Kisa odev aciklamasi.");
    expect(result.expectedOutput).toBeNull();
  });
});
