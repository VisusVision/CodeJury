"""CSV/rapor export odevi - uygun cozum."""

from __future__ import annotations

import csv
from pathlib import Path


def summarize_scores(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    for row in rows:
        name = row.get("name", "").strip()
        score_text = row.get("score", "0").strip() or "0"
        score = int(score_text)
        summary.append(
            {
                "name": name,
                "score": str(score),
                "status": "passed" if score >= 60 else "failed",
            }
        )
    return summary


def export_report(rows: list[dict[str, str]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "score", "status"])
        writer.writeheader()
        writer.writerows(summarize_scores(rows))


if __name__ == "__main__":
    export_report(
        [{"name": "Ayse", "score": "88"}, {"name": "Mehmet", "score": "42"}],
        Path("report.csv"),
    )
    print("report.csv yazildi")
