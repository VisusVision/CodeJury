"""Parse soak terminal log for analysis."""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts" / "qa" / "soak" / "terminal_51840.txt"


def main() -> None:
    if not LOG.exists():
        # fallback to cursor terminals path
        alt = Path(r"C:\Users\EMRE\.cursor\projects\c-Users-EMRE-Desktop-AgentGrade\terminals\51840.txt")
        log_text = alt.read_text(encoding="utf-8", errors="replace")
    else:
        log_text = LOG.read_text(encoding="utf-8", errors="replace")

    cases: list[dict] = []
    current: dict | None = None
    pending: dict | None = None

    for line in log_text.splitlines():
        m = re.search(r"\[soak\]  -> ([^(]+)\((\w+)\)", line)
        if m:
            parts = m.group(1).strip().split("/")
            pending = {
                "label": parts[-1],
                "scenario": parts[0],
                "kind": m.group(2),
            }
            continue

        m3 = re.search(r"Paralel katman bitti \((.+)\)", line)
        if m3 and pending is not None:
            agents: dict[str, str] = {}
            for part in m3.group(1).split(","):
                if "=" in part:
                    k, v = part.strip().split("=", 1)
                    agents[k.strip()] = v.strip()
            pending["parallel"] = agents
            continue

        m4 = re.search(r"Gorev uyumu: programatik=([\d.]+) llm=([\d.]+) birlesik=([\d.]+)", line)
        if m4 and pending is not None:
            pending["align_prog"] = float(m4.group(1))
            pending["align_llm"] = float(m4.group(2))
            pending["align_blend"] = float(m4.group(3))
            continue

        m5 = re.search(r"MasterEvaluator bitti \(final_score=([\d.]+)\)", line)
        if m5 and pending is not None:
            pending["master_score"] = float(m5.group(1))
            continue

        m6 = re.search(r"EvidenceAgent bitti \(validated=(\d+)\)", line)
        if m6 and pending is not None:
            pending["evidence_count"] = int(m6.group(1))
            continue

        m2 = re.search(
            r"\[soak\]\s+(PASS|FAIL) score=([\d.]+) align=([\d.]+) sec=([\d.]+) t=([\d.]+)s",
            line,
        )
        if m2 and pending is not None:
            row = {
                **pending,
                "status": m2.group(1),
                "score": float(m2.group(2)),
                "align": float(m2.group(3)),
                "sec": float(m2.group(4)),
                "time_s": float(m2.group(5)),
            }
            cases.append(row)
            pending = None

    by_label: dict[str, list] = defaultdict(list)
    for c in cases:
        by_label[c["label"]].append(c)

    out: dict = {
        "total": len(cases),
        "pass": sum(1 for c in cases if c["status"] == "PASS"),
        "fail": sum(1 for c in cases if c["status"] == "FAIL"),
        "avg_time_s": round(statistics.mean(c["time_s"] for c in cases), 1),
        "by_label": {},
        "by_kind": {},
        "failures": [c for c in cases if c["status"] == "FAIL"],
        "agent_avgs_uygun": {},
    }

    for label, rows in sorted(by_label.items()):
        scores = [r["score"] for r in rows]
        out["by_label"][label] = {
            "kind": rows[0]["kind"],
            "n": len(rows),
            "score_min": min(scores),
            "score_max": max(scores),
            "score_avg": round(statistics.mean(scores), 1),
            "fail": sum(1 for r in rows if r["status"] == "FAIL"),
        }

    for kind in ("uygun", "alakasiz", "guvensiz", "syntax"):
        rows = [c for c in cases if c["kind"] == kind]
        if not rows:
            continue
        out["by_kind"][kind] = {
            "n": len(rows),
            "score_min": min(r["score"] for r in rows),
            "score_max": max(r["score"] for r in rows),
            "score_avg": round(statistics.mean(r["score"] for r in rows), 1),
            "align_avg": round(statistics.mean(r["align"] for r in rows), 2),
        }

    uygun = [c for c in cases if c["kind"] == "uygun" and "parallel" in c]
    agent_keys = ["CQ", "ALG", "SN", "GL", "SC", "TA"]
    for key in agent_keys:
        vals = []
        for c in uygun:
            p = c.get("parallel", {})
            if key in p:
                v = p[key]
                if v == "safe":
                    continue
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
        if vals:
            out["agent_avgs_uygun"][key] = round(statistics.mean(vals), 1)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
