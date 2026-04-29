"""
Ikili Agac Algoritmalari Odevi
Ogrenci: Ornek Ogrenci
"""


class Dugum:
    def __init__(self, deger):
        self.deger = deger
        self.sol = None
        self.sag = None


class IkiliAramAgaci:
    def __init__(self):
        self.kok = None

    def ekle(self, deger):
        if self.kok is None:
            self.kok = Dugum(deger)
        else:
            self._ekle_recursive(self.kok, deger)

    def _ekle_recursive(self, dugum, deger):
        if deger < dugum.deger:
            if dugum.sol is None:
                dugum.sol = Dugum(deger)
            else:
                self._ekle_recursive(dugum.sol, deger)
        else:
            if dugum.sag is None:
                dugum.sag = Dugum(deger)
            else:
                self._ekle_recursive(dugum.sag, deger)

    def ara(self, deger):
        return self._ara_recursive(self.kok, deger)

    def _ara_recursive(self, dugum, deger):
        if dugum is None:
            return False
        if deger == dugum.deger:
            return True
        elif deger < dugum.deger:
            return self._ara_recursive(dugum.sol, deger)
        else:
            return self._ara_recursive(dugum.sag, deger)

    def inorder(self):
        sonuc = []
        self._inorder_recursive(self.kok, sonuc)
        return sonuc

    def _inorder_recursive(self, dugum, sonuc):
        if dugum is not None:
            self._inorder_recursive(dugum.sol, sonuc)
            sonuc.append(dugum.deger)
            self._inorder_recursive(dugum.sag, sonuc)

    def preorder(self):
        sonuc = []
        self._preorder_recursive(self.kok, sonuc)
        return sonuc

    def _preorder_recursive(self, dugum, sonuc):
        if dugum is not None:
            sonuc.append(dugum.deger)
            self._preorder_recursive(dugum.sol, sonuc)
            self._preorder_recursive(dugum.sag, sonuc)

    def postorder(self):
        sonuc = []
        self._postorder_recursive(self.kok, sonuc)
        return sonuc

    def _postorder_recursive(self, dugum, sonuc):
        if dugum is not None:
            self._postorder_recursive(dugum.sol, sonuc)
            self._postorder_recursive(dugum.sag, sonuc)
            sonuc.append(dugum.deger)

    def yukseklik(self):
        return self._yukseklik_recursive(self.kok)

    def _yukseklik_recursive(self, dugum):
        if dugum is None:
            return 0
        sol_yukseklik = self._yukseklik_recursive(dugum.sol)
        sag_yukseklik = self._yukseklik_recursive(dugum.sag)
        return 1 + max(sol_yukseklik, sag_yukseklik)

    def minimum(self):
        if self.kok is None:
            return None
        dugum = self.kok
        while dugum.sol is not None:
            dugum = dugum.sol
        return dugum.deger

    def maksimum(self):
        if self.kok is None:
            return None
        dugum = self.kok
        while dugum.sag is not None:
            dugum = dugum.sag
        return dugum.deger

    def dugum_sayisi(self):
        return self._dugum_sayisi_recursive(self.kok)

    def _dugum_sayisi_recursive(self, dugum):
        if dugum is None:
            return 0
        return 1 + self._dugum_sayisi_recursive(dugum.sol) + self._dugum_sayisi_recursive(dugum.sag)

    def seviye_gezintisi(self):
        if self.kok is None:
            return []
        sonuc = []
        kuyruk = [self.kok]
        while kuyruk:
            dugum = kuyruk.pop(0)
            sonuc.append(dugum.deger)
            if dugum.sol:
                kuyruk.append(dugum.sol)
            if dugum.sag:
                kuyruk.append(dugum.sag)
        return sonuc


if __name__ == "__main__":
    agac = IkiliAramAgaci()

    degerler = [50, 30, 70, 20, 40, 60, 80, 10, 25, 35, 45]
    for d in degerler:
        agac.ekle(d)

    print("Inorder:", agac.inorder())
    print("Preorder:", agac.preorder())
    print("Postorder:", agac.postorder())
    print("Seviye gezintisi:", agac.seviye_gezintisi())
    print("Yukseklik:", agac.yukseklik())
    print("Dugum sayisi:", agac.dugum_sayisi())
    print("Minimum:", agac.minimum())
    print("Maksimum:", agac.maksimum())
    print("Ara 40:", agac.ara(40))
    print("Ara 99:", agac.ara(99))
