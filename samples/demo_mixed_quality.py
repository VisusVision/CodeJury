"""
Demo: BST / recursion degil — basit JSON + sozluk islemleri.
Panelde bu dosyayi yukleyip analiz et; guvenlik / standart / karmasiklik farkli davranmali.
"""

import json

# Guvenlik acisindan kotu ornek (gercek projede env / vault kullan)
API_SECRET = "hardcoded_demo_key_do_not_ship"

# Type hints yok, kisa isim — standart ajanı uyari uretebilir


def pct(part, whole):
    return round(100.0 * part / max(whole, 1), 1)


def load_rows(raw):
    return json.loads(raw)


def bucket_by_category(rows):
    out = {}
    for r in rows:
        cat = r.get("cat", "misc")
        out.setdefault(cat, []).append(r.get("amount", 0))
    return out


def totals_per_cat(buckets):
    return {k: sum(v) for k, v in buckets.items()}


def top_category(totals):
    if not totals:
        return None, 0
    items = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    return items[0]


# Bilerek uzun satir — satir uzunlugu / okunabilirlik uyarısı icin
SAMPLE = '[{"cat":"gida","amount":42},{"cat":"gida","amount":13},{"cat":"ulasim","amount":99},{"cat":"eglence","amount":7},{"cat":"ulasim","amount":11}]'


def main():
    rows = load_rows(SAMPLE)
    buckets = bucket_by_category(rows)
    totals = totals_per_cat(buckets)
    name, amt = top_category(totals)
    share = pct(amt, sum(totals.values()))
    print(f"top={name} total={amt} share_pct={share} secret_len={len(API_SECRET)}")


if __name__ == "__main__":
    main()
