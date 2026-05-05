"""API konfigurasyon istemcisi - uygun cozum."""

from __future__ import annotations

import os
import urllib.request


def base_url_from_env() -> str:
    value = os.environ.get("API_URL", "https://example.com").strip()
    if not value.startswith(("http://", "https://")):
        raise ValueError("API_URL http veya https ile baslamali")
    return value.rstrip("/")


def fetch_status(path: str = "/health") -> int:
    url = f"{base_url_from_env()}{path}"
    with urllib.request.urlopen(url, timeout=5) as response:
        return int(response.status)


if __name__ == "__main__":
    # Smoke run dis aga baglanmadan basarili olabilsin; fetch_status() fonksiyonu
    # testlerde veya gercek kullanimda verilen URL icin cagrilir.
    print(base_url_from_env())
