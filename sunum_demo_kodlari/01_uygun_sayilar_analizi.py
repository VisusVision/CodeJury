from pathlib import Path
from statistics import mean, median


GIRIS_DOSYASI = "sayilar.txt"
CIKIS_DOSYASI = "sonuc.txt"


def oku_sayilar(dosya_adi=GIRIS_DOSYASI):
    yol = Path(dosya_adi)
    if not yol.exists():
        print(f"Hata: {dosya_adi} dosyasi bulunamadi.")
        return None

    sayilar = []
    for satir_no, satir in enumerate(yol.read_text(encoding="utf-8").splitlines(), start=1):
        deger = satir.strip()
        if not deger:
            continue
        try:
            sayilar.append(int(deger))
        except ValueError:
            print(f"Uyari: {satir_no}. satir atlandi: {deger}")
    return sayilar


def tek_sayilari_bul(sayilar):
    return [sayi for sayi in sayilar if sayi % 2 != 0]


def istatistik_hesapla(tek_sayilar):
    return {
        "adet": len(tek_sayilar),
        "ortalama": mean(tek_sayilar),
        "medyan": median(tek_sayilar),
    }


def rapor_olustur(sayilar):
    if not sayilar:
        return "Gecerli sayi bulunamadi.\n"

    tek_sayilar = tek_sayilari_bul(sayilar)
    if not tek_sayilar:
        return "Tek sayi bulunamadi.\n"

    istatistik = istatistik_hesapla(tek_sayilar)
    satirlar = [
        "Tek Sayi Analiz Raporu",
        f"Toplam gecerli sayi adedi: {len(sayilar)}",
        f"Tek sayi adedi: {istatistik['adet']}",
        "Tek sayilar: " + ", ".join(str(sayi) for sayi in tek_sayilar),
        f"Ortalama: {istatistik['ortalama']:.2f}",
        f"Medyan: {istatistik['medyan']:.2f}",
    ]
    return "\n".join(satirlar) + "\n"


def rapor_yaz(rapor, dosya_adi=CIKIS_DOSYASI):
    Path(dosya_adi).write_text(rapor, encoding="utf-8")


def test_senaryolari():
    assert tek_sayilari_bul([10, 7, -3, 0, 5]) == [7, -3, 5]
    assert "Gecerli sayi bulunamadi" in rapor_olustur([])
    assert "Tek sayi bulunamadi" in rapor_olustur([2, 4, 8])


def main():
    sayilar = oku_sayilar()
    if sayilar is None:
        return
    rapor = rapor_olustur(sayilar)
    rapor_yaz(rapor)
    print(rapor)


if __name__ == "__main__":
    main()
