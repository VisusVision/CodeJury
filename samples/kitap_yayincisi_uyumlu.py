"""
Uygun ornek: KitapYayincisi sinifi, kitap/kutuphane iliskileri, kalitim ve bilesim.
"""


class Kurum:
    def __init__(self, ad: str):
        self.ad = ad

    def tanit(self) -> str:
        return self.ad


class Kitap:
    def __init__(self, isbn: str, baslik: str, yazar: str, yayinci_adi: str):
        self.isbn = isbn
        self.baslik = baslik
        self.yazar = yazar
        self.yayinci_adi = yayinci_adi

    def __repr__(self) -> str:
        return f"{self.baslik} ({self.yayinci_adi})"


class Kutuphane(Kurum):
    def __init__(self, ad: str):
        super().__init__(ad)
        self.kitaplar: list[Kitap] = []

    def kitap_ekle(self, kitap: Kitap) -> None:
        if kitap.isbn not in {k.isbn for k in self.kitaplar}:
            self.kitaplar.append(kitap)

    def yayincinin_kitaplari(self, yayinci_adi: str) -> list[Kitap]:
        return [kitap for kitap in self.kitaplar if kitap.yayinci_adi == yayinci_adi]


class KitapYayincisi(Kurum):
    def __init__(self, ad: str):
        super().__init__(ad)
        self.kendi_kitaplari: list[Kitap] = []
        self.diger_yayincilardan_alinanlar: list[Kitap] = []
        self.iliskili_kutuphaneler: list[Kutuphane] = []
        self.iliskili_yayincilar: list["KitapYayincisi"] = []

    def kitap_yayinla(self, isbn: str, baslik: str, yazar: str) -> Kitap:
        kitap = Kitap(isbn, baslik, yazar, self.ad)
        self.kendi_kitaplari.append(kitap)
        return kitap

    def yayinci_ile_iliskilendir(self, yayinci: "KitapYayincisi") -> None:
        if yayinci is self:
            raise ValueError("Yayinci kendisiyle iliskilendirilemez")
        if yayinci not in self.iliskili_yayincilar:
            self.iliskili_yayincilar.append(yayinci)

    def kutuphane_ile_iliskilendir(self, kutuphane: Kutuphane) -> None:
        if kutuphane not in self.iliskili_kutuphaneler:
            self.iliskili_kutuphaneler.append(kutuphane)

    def baska_yayincidan_kitap_al(self, yayinci: "KitapYayincisi", isbn: str) -> Kitap:
        self.yayinci_ile_iliskilendir(yayinci)
        for kitap in yayinci.kendi_kitaplari:
            if kitap.isbn == isbn:
                if kitap not in self.diger_yayincilardan_alinanlar:
                    self.diger_yayincilardan_alinanlar.append(kitap)
                return kitap
        raise ValueError("Istenen kitap yayincida bulunamadi")

    def kutuphanelerden_kendi_kitaplarini_getir(self) -> list[Kitap]:
        bulunanlar: dict[str, Kitap] = {}
        for kutuphane in self.iliskili_kutuphaneler:
            for kitap in kutuphane.yayincinin_kitaplari(self.ad):
                bulunanlar[kitap.isbn] = kitap
        return list(bulunanlar.values())

    def rapor_olustur(self) -> str:
        return (
            f"{self.ad}: {len(self.kendi_kitaplari)} kendi kitap, "
            f"{len(self.diger_yayincilardan_alinanlar)} alinan kitap, "
            f"{len(self.iliskili_kutuphaneler)} iliskili kutuphane"
        )


def main() -> None:
    yayinci_a = KitapYayincisi("Bilge Yayincilik")
    yayinci_b = KitapYayincisi("Akademi Yayinevi")
    merkez = Kutuphane("Merkez Kutuphanesi")

    algoritma = yayinci_a.kitap_yayinla("978-100", "Algoritma Temelleri", "A. Demir")
    veri = yayinci_b.kitap_yayinla("978-200", "Veri Yapilari", "B. Kaya")

    merkez.kitap_ekle(algoritma)
    merkez.kitap_ekle(veri)
    yayinci_a.kutuphane_ile_iliskilendir(merkez)
    yayinci_a.baska_yayincidan_kitap_al(yayinci_b, "978-200")

    print(yayinci_a.rapor_olustur())
    print("Kutuphanelerdeki kendi kitaplari:", yayinci_a.kutuphanelerden_kendi_kitaplarini_getir())


if __name__ == "__main__":
    main()
