class Playlist:
    def __init__(self, ad):
        self.ad = ad
        self.sarkilar = []

    def sarki_ekle(self, sanatci, baslik, sure):
        self.sarkilar.append({"sanatci": sanatci, "baslik": baslik, "sure": sure})

    def toplam_sure(self):
        return sum(sarki["sure"] for sarki in self.sarkilar)

    def yazdir(self):
        print(f"Playlist: {self.ad}")
        for sira, sarki in enumerate(self.sarkilar, start=1):
            print(f"{sira}. {sarki['sanatci']} - {sarki['baslik']}")
        print(f"Toplam sure: {self.toplam_sure()} dakika")


def main():
    liste = Playlist("Aksam Sunumu")
    liste.sarki_ekle("Sanatci A", "Baslangic", 3)
    liste.sarki_ekle("Sanatci B", "Final", 4)
    liste.yazdir()


if __name__ == "__main__":
    main()

