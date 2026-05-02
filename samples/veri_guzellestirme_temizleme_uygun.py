"""
Veri Guzellestirme ve Temizleme odevi icin uygun ornek cozum.

Bu dosya dis bagimlilik kullanmadan mini bir JSON API sunar:
- SQLite tablosu olusturur.
- POST /clean ile ham veriyi temizler ve kaydeder.
- PUT /beautify ile mevcut kaydi daha okunabilir hale getirir.
- Hatali isteklerde JSON hata mesaji ve konsol logu uretir.

Calistirma:
    python samples/veri_guzellestirme_temizleme_uygun.py

Ornek:
    POST http://127.0.0.1:8080/clean
    {"text": "  mERhaba\\n\\n   dunya!!!  "}

    PUT http://127.0.0.1:8080/beautify
    {"id": 1}
"""

from __future__ import annotations

import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


DB_PATH = Path(__file__).with_name("clean_data.sqlite3")
HOST = "127.0.0.1"
PORT = 8080


def init_database() -> None:
    """Verilerin saklanacagi SQLite tablosunu hazirlar."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                cleaned_text TEXT NOT NULL,
                beautified_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def clean_text(text: str) -> str:
    """Gereksiz bosluklari, kontrol karakterlerini ve tekrar eden satirlari temizler."""
    without_control_chars = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    normalized_lines = [re.sub(r"\s+", " ", line).strip() for line in without_control_chars.splitlines()]
    non_empty_lines = [line for line in normalized_lines if line]
    return "\n".join(non_empty_lines)


def beautify_text(text: str) -> str:
    """Temizlenmis metni daha okunabilir cumlelere donusturur."""
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""

    sentences = re.split(r"(?<=[.!?])\s+", compact)
    beautified: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        sentence = sentence[0].upper() + sentence[1:]
        if sentence[-1] not in ".!?":
            sentence += "."
        beautified.append(sentence)
    return " ".join(beautified)


def insert_cleaned_record(raw_text: str, cleaned_text: str) -> int:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "INSERT INTO records (raw_text, cleaned_text) VALUES (?, ?)",
            (raw_text, cleaned_text),
        )
        conn.commit()
        return int(cursor.lastrowid)


def update_beautified_record(record_id: int, beautified_text: str) -> bool:
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            UPDATE records
            SET beautified_text = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (beautified_text, record_id),
        )
        conn.commit()
        return cursor.rowcount > 0


def get_cleaned_text(record_id: int) -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT cleaned_text FROM records WHERE id = ?",
            (record_id,),
        ).fetchone()
    return None if row is None else str(row[0])


class DataApiHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            raise ValueError("Istek govdesi bos olamaz.")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Gecerli JSON gonderilmelidir.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON govdesi nesne tipinde olmalidir.")
        return payload

    def do_POST(self) -> None:
        if self.path != "/clean":
            self._send_json(404, {"error": "Endpoint bulunamadi."})
            return

        try:
            payload = self._read_json_body()
            raw_text = payload.get("text")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise ValueError("'text' alani bos olmayan bir metin olmalidir.")

            cleaned = clean_text(raw_text)
            record_id = insert_cleaned_record(raw_text, cleaned)
            print(f"[INFO] Veri temizlendi ve kaydedildi: id={record_id}")
            self._send_json(201, {"id": record_id, "cleaned_text": cleaned})
        except ValueError as exc:
            print(f"[WARN] Temizleme istegi reddedildi: {exc}")
            self._send_json(400, {"error": str(exc)})
        except sqlite3.Error as exc:
            print(f"[ERROR] SQLite temizleme hatasi: {exc}")
            self._send_json(500, {"error": "Veri tabani hatasi olustu."})

    def do_PUT(self) -> None:
        if self.path != "/beautify":
            self._send_json(404, {"error": "Endpoint bulunamadi."})
            return

        try:
            payload = self._read_json_body()
            record_id = int(payload.get("id", 0))
            if record_id <= 0:
                raise ValueError("'id' pozitif bir sayi olmalidir.")

            cleaned_text = get_cleaned_text(record_id)
            if cleaned_text is None:
                self._send_json(404, {"error": "Kayit bulunamadi."})
                return

            beautified = beautify_text(cleaned_text)
            update_beautified_record(record_id, beautified)
            print(f"[INFO] Veri guzellestirildi: id={record_id}")
            self._send_json(200, {"id": record_id, "beautified_text": beautified})
        except (TypeError, ValueError) as exc:
            print(f"[WARN] Guzellestirme istegi reddedildi: {exc}")
            self._send_json(400, {"error": str(exc)})
        except sqlite3.Error as exc:
            print(f"[ERROR] SQLite guzellestirme hatasi: {exc}")
            self._send_json(500, {"error": "Veri tabani hatasi olustu."})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[HTTP] {self.address_string()} - {format % args}")


def run_server() -> None:
    init_database()
    server = HTTPServer((HOST, PORT), DataApiHandler)
    print(f"[INFO] Veri API calisiyor: http://{HOST}:{PORT}")
    print("[INFO] POST /clean ve PUT /beautify endpointleri hazir.")
    server.serve_forever()


if __name__ == "__main__":
    run_server()
