def hesap_makinesi():
    sayi1 = float(input("Birinci sayıyı girin: "))
    sayi2 = float(input("İkinci sayıyı girin: "))

    print("1 - Toplama")
    print("2 - Çıkarma")
    print("3 - Çarpma")
    print("4 - Bölme")

    secim = input("İşlem seçin: ")

    if secim == "1":
        sonuc = sayi1 + sayi2
        print("Sonuç:", sonuc)

    elif secim == "2":
        sonuc = sayi1 - sayi2
        print("Sonuç:", sonuc)

    elif secim == "3":
        sonuc = sayi1 * sayi2
        print("Sonuç:", sonuc)

    elif secim == "4":
        if sayi2 != 0:
            sonuc = sayi1 / sayi2
            print("Sonuç:", sonuc)
        else:
            print("Bir sayı sıfıra bölünemez.")

    else:
        print("Geçersiz seçim.")


hesap_makinesi()