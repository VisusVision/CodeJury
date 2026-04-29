"""
Kitap Kutuphane Yonetim Sistemi
Kullanicilar kitaplari sorgulayabilir, kiralayabilir ve geri verebilir.
"""

from datetime import datetime, timedelta


class Kitap:
    """Kutuphanedeki bir kitabi temsil eder."""

    def __init__(self, kitap_id: int, ad: str, yazar: str, yayinevi: str):
        self.kitap_id = kitap_id
        self.ad = ad
        self.yazar = yazar
        self.yayinevi = yayinevi
        self.durum = "musait"

    def durum_guncelle(self, yeni_durum: str) -> None:
        """Kitabin durumunu gunceller (musait / kirada / kayip)."""
        gecerli_durumlar = {"musait", "kirada", "kayip"}
        if yeni_durum not in gecerli_durumlar:
            raise ValueError(f"Gecersiz durum: {yeni_durum}")
        self.durum = yeni_durum

    def __str__(self) -> str:
        return f"[{self.kitap_id}] {self.ad} - {self.yazar} ({self.durum})"


class Kullanici:
    """Kutuphaneden kitap kiralayan bir kullaniciyi temsil eder."""

    def __init__(self, kullanici_id: int, ad: str, soyad: str):
        self.kullanici_id = kullanici_id
        self.ad = ad
        self.soyad = soyad
        self.kiraladiklari: list[Kitap] = []

    def kirala(self, kitap: Kitap) -> "Kiralama":
        """Bir kitabi kullanici adina kiralar ve Kiralama kaydi dondurur."""
        if kitap.durum != "musait":
            raise RuntimeError(f"'{kitap.ad}' su anda kiralanamaz (durum: {kitap.durum}).")
        kitap.durum_guncelle("kirada")
        self.kiraladiklari.append(kitap)
        return Kiralama(self, kitap)

    def geri_ver(self, kitap: Kitap) -> None:
        """Kullanicinin kiraladigi kitabi geri verir."""
        if kitap not in self.kiraladiklari:
            raise RuntimeError(f"{self.ad}, '{kitap.ad}' kitabini kiralamamis.")
        self.kiraladiklari.remove(kitap)
        kitap.durum_guncelle("musait")

    def __str__(self) -> str:
        return f"{self.ad} {self.soyad} (id={self.kullanici_id})"


class Kiralama:
    """Bir kullanici ile bir kitap arasindaki kiralama islemini temsil eder."""

    def __init__(self, kullanici: Kullanici, kitap: Kitap, gun: int = 14):
        self.kullanici = kullanici
        self.kitap = kitap
        self.kiralama_tarihi = datetime.now()
        self.son_teslim_tarihi = self.kiralama_tarihi + timedelta(days=gun)

    def gecikti_mi(self) -> bool:
        """Teslim tarihinin gecip gecmedigini kontrol eder."""
        return datetime.now() > self.son_teslim_tarihi

    def __str__(self) -> str:
        return (
            f"{self.kullanici.ad} -> '{self.kitap.ad}' "
            f"(teslim: {self.son_teslim_tarihi.strftime('%d.%m.%Y')})"
        )


class Kutuphane:
    """Tum kitaplari ve kullanicilari yoneten ana sinif."""

    def __init__(self, ad: str):
        self.ad = ad
        self.kitaplar: list[Kitap] = []
        self.kullanicilar: list[Kullanici] = []
        self.kiralamalar: list[Kiralama] = []

    def kitap_ekle(self, kitap: Kitap) -> None:
        self.kitaplar.append(kitap)

    def kullanici_ekle(self, kullanici: Kullanici) -> None:
        self.kullanicilar.append(kullanici)

    def kitap_sorgula(self, anahtar: str) -> list[Kitap]:
        """Ad veya yazara gore kitap arar."""
        anahtar = anahtar.lower()
        return [
            k for k in self.kitaplar
            if anahtar in k.ad.lower() or anahtar in k.yazar.lower()
        ]

    def kiralama_yap(self, kullanici: Kullanici, kitap: Kitap) -> Kiralama:
        kayit = kullanici.kirala(kitap)
        self.kiralamalar.append(kayit)
        return kayit


if __name__ == "__main__":
    kutuphane = Kutuphane("Merkez Kutuphane")

    k1 = Kitap(1, "Suc ve Ceza", "Dostoyevski", "Iletisim")
    k2 = Kitap(2, "1984", "George Orwell", "Can")
    k3 = Kitap(3, "Kurk Mantolu Madonna", "Sabahattin Ali", "YKY")
    for k in (k1, k2, k3):
        kutuphane.kitap_ekle(k)

    u1 = Kullanici(101, "Ayse", "Yilmaz")
    u2 = Kullanici(102, "Mehmet", "Demir")
    kutuphane.kullanici_ekle(u1)
    kutuphane.kullanici_ekle(u2)

    print("Arama 'orwell':", [str(k) for k in kutuphane.kitap_sorgula("orwell")])

    kayit = kutuphane.kiralama_yap(u1, k2)
    print("Yeni kiralama:", kayit)
    print("k2 durum:", k2.durum)

    u1.geri_ver(k2)
    print("Iade sonrasi k2 durum:", k2.durum)

    try:
        u2.geri_ver(k1)
    except RuntimeError as e:
        print("Beklenen hata:", e)
