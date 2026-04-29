"""
Kutuphane odevi — uygun ornek: Kitap, Uye, Kutuphane siniflari, odunc/iade.
"""


class Kitap:
    def __init__(self, isbn: str, baslik: str, yazar: str):
        self.isbn = isbn
        self.baslik = baslik
        self.yazar = yazar
        self.oduncte = False

    def __repr__(self) -> str:
        return f"Kitap({self.baslik!r}, {self.yazar!r})"


class Uye:
    def __init__(self, uye_no: str, ad: str):
        self.uye_no = uye_no
        self.ad = ad
        self.odunc_kitaplar: list[Kitap] = []
        self._limit = 3

    def odunc_alabilir_mi(self) -> bool:
        return len(self.odunc_kitaplar) < self._limit


class Kutuphane:
    def __init__(self):
        self._kitaplar: dict[str, Kitap] = {}
        self._uyeler: dict[str, Uye] = {}

    def kitap_ekle(self, kitap: Kitap) -> None:
        if kitap.isbn in self._kitaplar:
            raise ValueError("Bu ISBN zaten kayitli")
        self._kitaplar[kitap.isbn] = kitap

    def uye_ekle(self, uye: Uye) -> None:
        if uye.uye_no in self._uyeler:
            raise ValueError("Bu uye numarasi zaten var")
        self._uyeler[uye.uye_no] = uye

    def odunc_ver(self, isbn: str, uye_no: str) -> None:
        kitap = self._kitaplar.get(isbn)
        uye = self._uyeler.get(uye_no)
        if kitap is None:
            raise ValueError("Kitap bulunamadi")
        if uye is None:
            raise ValueError("Uye bulunamadi")
        if kitap.oduncte:
            raise ValueError("Kitap baskasinda")
        if not uye.odunc_alabilir_mi():
            raise ValueError("Odunc limiti dolu")
        kitap.oduncte = True
        uye.odunc_kitaplar.append(kitap)

    def iade_al(self, isbn: str, uye_no: str) -> None:
        kitap = self._kitaplar.get(isbn)
        uye = self._uyeler.get(uye_no)
        if kitap is None or uye is None:
            raise ValueError("Kayit bulunamadi")
        if kitap not in uye.odunc_kitaplar:
            raise ValueError("Bu uyede bu kitap yok")
        kitap.oduncte = False
        uye.odunc_kitaplar.remove(kitap)


def main() -> None:
    k = Kutuphane()
    k.kitap_ekle(Kitap("978-1", "Algoritmalar", "CLRS"))
    k.kitap_ekle(Kitap("978-2", "Python", "Lutz"))
    u = Uye("U001", "Ayse")
    k.uye_ekle(u)
    k.odunc_ver("978-1", "U001")
    print("Odunc sonrasi:", u.odunc_kitaplar)
    k.iade_al("978-1", "U001")
    print("Iade sonrasi:", u.odunc_kitaplar)


if __name__ == "__main__":
    main()
