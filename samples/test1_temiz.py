from datetime import datetime, timedelta

def randevulari_listele(dosya_yolu):
    bugun = datetime.today().date()
    uc_gun_sonra = bugun + timedelta(days=3)

    try:
        with open(dosya_yolu, "r", encoding="utf-8") as dosya:
            randevular = dosya.readlines()

        print("3 gün içindeki randevular:")

        for randevu in randevular:
            bilgiler = randevu.strip().split(",")

            if len(bilgiler) == 3:
                isim = bilgiler[0].strip()
                tarih_metni = bilgiler[1].strip()
                aciklama = bilgiler[2].strip()

                randevu_tarihi = datetime.strptime(tarih_metni, "%Y-%m-%d").date()

                if bugun <= randevu_tarihi <= uc_gun_sonra:
                    print(f"{isim} - {randevu_tarihi} - {aciklama}")

    except FileNotFoundError:
        print("Dosya bulunamadı.")
    except ValueError:
        print("Tarih formatı hatalı. Tarih YYYY-AA-GG formatında olmalıdır.")


randevulari_listele("randevular.txt")