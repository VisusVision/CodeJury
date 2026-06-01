const fold = (raw: string) =>
  raw
    .toLowerCase()
    .replaceAll("ç", "c")
    .replaceAll("ğ", "g")
    .replaceAll("ı", "i")
    .replaceAll("ö", "o")
    .replaceAll("ş", "s")
    .replaceAll("ü", "u")
    .replaceAll("Ã§", "c")
    .replaceAll("ÄŸ", "g")
    .replaceAll("Ä±", "i")
    .replaceAll("Ã¶", "o")
    .replaceAll("ÅŸ", "s")
    .replaceAll("Ã¼", "u");

const hasAny = (blob: string, tokens: string[]) => tokens.some((token) => blob.includes(token));
const hasStandalonePh = (blob: string) => /(^|[^a-z0-9])ph([^a-z0-9]|$)/.test(blob);
const apiDomain = (blob: string) => {
  if (hasAny(blob, ["randevu", "doktor", "hasta"])) {
    return {
      collection: "randevular",
      entity: "randevu",
      sample: "{\"id\": 1, \"hasta\": \"Ayse Yilmaz\", \"doktor\": \"Dr. Kaya\", \"saat\": \"10:30\"}",
      missing: "Randevu bulunamadi",
      invalid: "Secilen saat uygun degil",
    };
  }
  if (hasAny(blob, ["sikayet", "mahalle", "oncelik"])) {
    return {
      collection: "sikayetler",
      entity: "sikayet",
      sample: "{\"id\": 1, \"mahalle\": \"Merkez\", \"kategori\": \"yol\", \"oncelik\": \"yuksek\"}",
      missing: "Sikayet bulunamadi",
      invalid: "Kategori zorunludur",
    };
  }
  if (hasAny(blob, ["fatura", "kdv", "kalem"])) {
    return {
      collection: "faturalar",
      entity: "fatura",
      sample: "{\"id\": 1, \"ara_toplam\": 250.0, \"kdv\": 50.0, \"genel_toplam\": 300.0}",
      missing: "Fatura bulunamadi",
      invalid: "Tutar sifirdan buyuk olmalidir",
    };
  }
  return {
    collection: "kayitlar",
    entity: "kayit",
    sample: "{\"id\": 1, \"durum\": \"olusturuldu\"}",
    missing: "Kayit bulunamadi",
    invalid: "Zorunlu alan eksik",
  };
};

const EXAMPLE_OUTPUT_HEADING = /^\s*(?:Ornek|Örnek|Ã–rnek)\s+(?:Cikti|Çıktı|Ã‡Ä±ktÄ±)\s*:\s*/i;
const GENERIC_EXAMPLE_HEADING = /^\s*(?:Ornek|Örnek|Ã–rnek)\s*:\s*/i;

const exampleBlock = (body: string) => `Örnek: ${body.trim()}`;

export const exampleBody = (example: string) =>
  example
    .replace(EXAMPLE_OUTPUT_HEADING, "")
    .replace(GENERIC_EXAMPLE_HEADING, "")
    .trim();

export const buildAssignmentExample = (assignmentTitle: string, assignmentDescription: string) => {
  const source = `${assignmentTitle} ${assignmentDescription}`;
  const blob = fold(source);

  if (hasAny(blob, ["log", "gunluk"])) {
    return exampleBlock(
      [
        "Girdi dosyasi `ornek_log.txt`:",
        "2026-05-09 10:00 INFO Uygulama basladi",
        "2026-05-09 10:02 ERROR Veritabani baglantisi koptu",
        "2026-05-09 10:05 WARNING Disk alani azaldi",
        "bozuk_satir",
        "",
        "Beklenen konsol ciktisi:",
        "INFO: 1",
        "WARNING: 1",
        "ERROR: 1",
        "Bozuk satir: 1",
        "Hata satirlari: 2",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["kutuphane", "kitap", "uye", "odunc", "iade"]) && hasAny(blob, ["api", "endpoint", "fastapi", "rest"])) {
    return exampleBlock(
      [
        "Ornek istek akisi:",
        "POST /books -> {\"id\": 1, \"title\": \"1984\", \"available\": true}",
        "POST /members -> {\"id\": 1001, \"name\": \"Ayse Yilmaz\"}",
        "POST /loans -> {\"book_id\": 1, \"member_id\": 1001, \"status\": \"borrowed\"}",
        "POST /returns -> {\"book_id\": 1, \"status\": \"returned\"}",
        "",
        "Hata ornegi:",
        "POST /loans book_id=999 -> 404 {\"detail\": \"Kitap bulunamadi\"}",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["api", "endpoint", "rest", "fastapi", "flask", "django"])) {
    const domain = apiDomain(blob);
    return exampleBlock(
      [
        "Kucuk API deneme senaryosu:",
        `POST /${domain.collection} -> 201 ${domain.sample}`,
        `GET /${domain.collection} -> 200 [${domain.sample}]`,
        `GET /${domain.collection}/1 -> 200 ${domain.sample}`,
        "",
        "Hata durumu:",
        `GET /${domain.collection}/999 -> 404 {"detail": "${domain.missing}"}`,
        `POST /${domain.collection} gecersiz ${domain.entity} -> 400 {"detail": "${domain.invalid}"}`,
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["titrasyon", "olcum", "olcumleri", "kimya"]) || hasStandalonePh(blob)) {
    return exampleBlock(
      [
        "Girdi `ph_olcumleri.csv`:",
        "numune_id,titrasyon_ml,pH",
        "N1,12.4,6.8",
        "N2,14.1,7.2",
        "N3,11.9,gecersiz",
        "",
        "Beklenen rapor:",
        "Gecerli olcum: 2",
        "Ortalama pH: 7.00",
        "En dusuk/en yuksek pH: 6.80 / 7.20",
        "Uyari: N3 satirinda pH sayisal degil.",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["csv", "json", "dosya", "rapor"])) {
    return exampleBlock(
      [
        "Kucuk girdi dosyasi:",
        "id,ad,deger",
        "1,Ada,85",
        "2,Emir,92",
        "3,BosDeger,",
        "",
        "Beklenen cikti:",
        "Basarili kayit sayisi: 2",
        "Hesaplanan ortalama: 88.50",
        "Atlanan satirlar: 3. satirda deger eksik",
        "Program komutu: python main.py --input girdi.csv --output rapor.txt",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["kutuphane", "kitap", "uye", "odunc", "iade"]) && hasAny(blob, ["sinif", "oop", "nesne", "class"])) {
    return exampleBlock(
      [
        "Ornek nesne akisi:",
        "Kitap('1984', stok=1), Uye('1001', 'Ayse') ve Kutuphane() olusturulur.",
        "Ayse 1984 kitabini odunc alir -> sonuc: 'Odunc verildi', stok: 0",
        "Ayni kitap ikinci kez istenir -> sonuc: 'Kitap stokta yok'",
        "Kitap iade edilir -> sonuc: 'Iade alindi', stok: 1",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["sinif", "oop", "nesne", "class", "kalitim"])) {
    return exampleBlock(
      [
        "Ornek calisma senaryosu:",
        "Iki gecerli nesne olusturulur ve temel metotlar sirayla cagrilir.",
        "Beklenen konsol ciktisi:",
        "Kayit olusturuldu: #1",
        "Durum guncellendi: aktif",
        "Gecersiz deger denemesi -> ValueError: zorunlu alan bos olamaz",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["ikili arama agaci", "bst", "agac"])) {
    return exampleBlock(
      [
        "Girdi: 8, 3, 10, 1, 6 degerleri agaca eklenir.",
        "Beklenen inorder cikti: 1, 3, 6, 8, 10",
        "search(6) -> true",
        "search(7) -> false",
        "Bos agacta silme denemesi -> 'Agac bos' uyarisi",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["graf", "bfs", "dfs"])) {
    return exampleBlock(
      [
        "Graf kenarlari: A-B, A-C, B-D",
        "BFS(A) beklenen ziyaret sirasi: A, B, C, D",
        "DFS(A) beklenen ziyaret sirasi: A, B, D, C",
        "Baslangic dugumu X verilirse -> 'Dugum bulunamadi' hatasi",
      ].join("\n"),
    );
  }

  if (hasAny(blob, ["algoritma", "liste", "stack", "queue", "kuyruk", "yigin"])) {
    return exampleBlock(
      [
        "Girdi: [4, 2, 2, 9]",
        "Beklenen ara adimlar raporlanir: okunan eleman, veri yapisinin guncel hali, uretilen sonuc.",
        "Beklenen final cikti: tekrarli degerler korunarak sonuc listesi uretilir.",
        "Kenar durum: bos girdi -> bos sonuc ve 'islem yapilacak veri yok' mesaji",
      ].join("\n"),
    );
  }

  return exampleBlock(
    [
      "Basarili senaryo:",
      "Odevde istenen en kucuk anlamli girdiyle program calistirilir ve beklenen cikti ekranda veya dosyada gosterilir.",
      "",
      "Beklenen cikti formati:",
      "Sonuc: basarili",
      "Islenen kayit: 2",
      "Uyari/Hata: yok",
      "",
      "Hata senaryosu:",
      "Eksik veya gecersiz girdi verildiginde program acik bir hata mesaji uretir ve kapanmadan devam eder.",
    ].join("\n"),
  );
};

export const descriptionWithExample = (assignmentDescription: string, example: string) => {
  const description = assignmentDescription.trim();
  const cleanedExample = exampleBody(example);
  if (
    /(^|\n)\s*(Ornek|Örnek|Ã–rnek)\s+(Cikti|Çıktı|Ã‡Ä±ktÄ±)\s*:/i.test(description)
    || /(^|\n)\s*(Ornek|Örnek|Ã–rnek)\s*:/i.test(description)
  ) {
    return description;
  }
  if (!cleanedExample) {
    return description;
  }
  return [description, `Ornek Cikti:\n${cleanedExample}`].filter(Boolean).join("\n\n").trim();
};
