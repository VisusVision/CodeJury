def main():
    sayilar = [1, 2, 3, 4, 5]
    tek_sayilar = [sayi for sayi in sayilar if sayi % 2 == 1]
    print("Tek sayilar:", tek_sayilar)


if __name__ == "__main__":
    main(
