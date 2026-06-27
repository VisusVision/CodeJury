"""
Evidence Mapping Agent -- tam LLM: kanit eslestirme Ollama ile.

Programatik on-dogrulama yalnizca prompt ipucu; validated/rejected listeleri LLM ciktisindan (LLM zorunlu).

Girdi:  {"source_code": str, "agent_findings": dict}
Cikti:  EvidenceOutput dict
"""

import ast as _pyast
import json
import re
from typing import Optional

from backend.agents.base import BaseAgent, LLMInferenceError, build_llm_user_suffix, format_assignment_context_for_prompt
from backend.agents.code_utils import get_code_metrics
from backend.agents.json_output_schema import EVIDENCE_OUTPUT_SCHEMA


def build_numbered_code(source_code: str) -> str:
    """Satır numarası eklenmiş kod üretir."""
    lines = source_code.splitlines()
    width = len(str(len(lines)))
    return "\n".join(f"{i+1:>{width}} | {line}" for i, line in enumerate(lines))

# Evidence-only: slightly warmer so the model keeps legitimate structural findings when unsure.
_EVIDENCE_LLM_TEMPERATURE = 0.28
_EVIDENCE_NUM_PREDICT = 4096

_EVIDENCE_SYSTEM_PROMPT = """\
You are an evidence mapper for automated code review. Validate every agent claim by tying it to
concrete evidence in the source: either specific numbered lines or an AST block.

Rules:
- For each supported claim emit one validated_claim referring to concrete evidence:
  * Single-line: set "lines":[n] (1-based). "code_snippet" should be that line.
  * Block-level (function, class, if/elif/else, for, while, try, with): set
    "block_id" to the matching AST_BLOCKS id, set "line_range":[start,end], and
    "node_type" (function|class|if|for|while|try|with). Add "symbol" for the
    function/class name when known.
  * Whole-file truth with no specific block: "lines":[] and omit "line_range".
- Use "lines":[] only for explicit whole-file facts, runtime/test-log evidence, or
  claims whose source really is the complete file. Set "node_type":"file" in that case.
- If a claim cannot be tied to a source line, AST block, whole-file fact, or runtime/test
  log, put it in rejected_claims with a short reason. Do not validate guesses.
- Prefer the smallest truthful evidence span. Do not attach nearby but unrelated lines just
  to make a weak claim look supported.
- "code_snippet" must be a normal JSON string containing raw source text only. Never include
  markdown fences, ```python, bullets, or commentary inside code_snippet. Escape newlines
  as JSON requires.
- Prefer block evidence for structural critique (gereksiz iç içe if-else, çok uzun
  fonksiyon, eksik try/except, sınıfın bütünü hakkında yorum, vs.). Use block_id
  when AST_BLOCKS contains a clearly matching node.
- Reject claims that are false, unrelated, unsupported by this file, or reference
  APIs/behavior that do not exist in this code.
- One validated_claim per distinct finding; do not summarize away valid items.
- severity: use "info" or "low" for neutral/positive validations (code is correct, requirement met).
  Reserve "medium"/"high"/"critical" only for genuine problems (bugs, missing requirements, risks).
- total_claims_received MUST equal TOTAL_CLAIMS in the user message.
- total_claims_validated MUST equal len(validated_claims).
- Required top-level keys: validated_claims, rejected_claims,
  total_claims_received, total_claims_validated.

Each validated_claim shape:
{
  "lines":[int],
  "line_range":[int,int],          // optional, block evidence
  "block_id":"bN",                  // optional, must come from AST_BLOCKS
  "node_type":"function|class|if|for|while|try|with|line|file",
  "symbol":"name",                  // optional
  "code_snippet":str,
  "feedback":str,
  "agent_source":str,
  "severity":"low|medium|high|critical|info",
  "is_valid":true
}

Return ONLY this JSON object:
{
  "validated_claims":[...],
  "rejected_claims":[],
  "total_claims_received":0,
  "total_claims_validated":0
}
"""


def _first_list(record: dict, *keys: str) -> list | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, list):
            return value
    return None


def _coerce_lines(value) -> list[int]:
    raw_items: list = []
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, (int, float)):
        raw_items = [value]
    elif isinstance(value, str):
        raw_items = re.findall(r"\d+", value)

    out: list[int] = []
    seen: set[int] = set()
    for item in raw_items:
        try:
            n = int(round(float(str(item).strip())))
        except (TypeError, ValueError):
            continue
        if n >= 1 and n not in seen:
            out.append(n)
            seen.add(n)
    return out


def _normalize_severity(value) -> str:
    from backend.agents.json_output_schema import normalize_agent_severity

    return normalize_agent_severity(value)


def _adjust_severity_from_feedback(feedback: str, severity: str) -> str:
    """Downgrade severity when feedback text describes correct/successful behavior."""
    text = (feedback or "").strip()
    if not text:
        return severity
    lower = text.lower()
    negative = (
        "eksik", "yok", "hata", "yanlis", "yanlış", "sorun", "magic number",
        "docstring yok", "tehdit", "anti-pattern", "sql injection", "eval(",
    )
    if any(term in lower for term in negative):
        return severity
    positive = (
        "doğru bir şekilde", "dogru bir sekilde", "doğru şekilde", "dogru sekilde",
        "uyumlu", "basariyla", "başarıyla", "correctly", "successfully",
        "tanımlanmış", "tanimlanmis", "reddiyor", "baslatiyor", "başlatıyor",
        "donduruyor", "döndürüyor",
    )
    if any(term in lower for term in positive):
        if severity in ("high", "critical"):
            return "info"
        if severity == "medium":
            return "low"
    return severity


def _clean_evidence_text(value) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:\w+)?\s*\n", "", text)
    text = re.sub(r"\n?```$", "", text)
    text = text.replace("```", "")
    text = re.sub(r"\s+", " ", text).strip(" -•\t\r\n")
    return text


_WHOLE_FILE_EVIDENCE_TERMS = (
    "whole file",
    "entire file",
    "file-level",
    "tum dosya",
    "tüm dosya",
    "dosyanin tamami",
    "dosyanın tamamı",
    "dosya geneli",
    "genelinde",
    "runtime hatasi",
    "runtime hata",
    "test hatasi",
    "test basarisiz",
    "test başarısız",
    "derleme hatasi",
    "compilation",
    "traceback",
)


def _is_supported_file_level_claim(feedback: str, agent_source: str, node_type: str | None) -> bool:
    if node_type == "file":
        return True
    text = f"{feedback} {agent_source}".lower()
    if any(term in text for term in _WHOLE_FILE_EVIDENCE_TERMS):
        return True
    return agent_source in {"test_agent", "security"} and any(
        term in text for term in ("runtime", "test", "derleme", "compilation", "security", "guvenlik")
    )


_AST_NODE_TYPES = {
    "function",
    "class",
    "if",
    "for",
    "while",
    "try",
    "with",
    "line",
    "file",
}


def _build_ast_evidence_map(source_code: str, language: str) -> dict:
    """Python AST'ten somut delillendirme icin blok haritasi cikar.

    Donen yapi:
        {
            "language": "python",
            "blocks": [
                {"id": "b1", "type": "class", "name": "Kitap", "start": 6, "end": 14},
                ...
            ]
        }

    Python disindaki diller icin bos liste doner -- LLM bu durumda satir bazli
    delil uretmeye odaklanir.
    """
    lang = (language or "").strip().lower()
    if lang not in ("python", "py"):
        return {"language": lang or "unknown", "blocks": []}

    cleaned = source_code.lstrip("\ufeff") if isinstance(source_code, str) else ""
    if not cleaned.strip():
        return {"language": "python", "blocks": []}

    try:
        tree = _pyast.parse(cleaned)
    except SyntaxError as exc:
        return {
            "language": "python",
            "syntax_error": True,
            "error": str(exc)[:160],
            "blocks": [],
        }

    blocks: list[dict] = []
    counter = {"n": 0}

    def _push(node: _pyast.AST, type_: str, name: Optional[str] = None) -> None:
        start = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if not isinstance(start, int) or not isinstance(end, int):
            return
        if end < start:
            end = start
        counter["n"] += 1
        blocks.append({
            "id": f"b{counter['n']}",
            "type": type_,
            "name": name,
            "start": start,
            "end": end,
        })

    for node in _pyast.walk(tree):
        if isinstance(node, (_pyast.FunctionDef, _pyast.AsyncFunctionDef)):
            _push(node, "function", node.name)
        elif isinstance(node, _pyast.ClassDef):
            _push(node, "class", node.name)
        elif isinstance(node, _pyast.If):
            _push(node, "if")
        elif isinstance(node, (_pyast.For, _pyast.AsyncFor)):
            _push(node, "for")
        elif isinstance(node, _pyast.While):
            _push(node, "while")
        elif isinstance(node, _pyast.Try):
            _push(node, "try")
        elif isinstance(node, _pyast.With):
            _push(node, "with")

    blocks.sort(key=lambda b: (b["start"], -(b["end"] - b["start"])))
    if len(blocks) > 60:
        blocks = blocks[:60]
    return {"language": "python", "blocks": blocks}


def _enclosing_block(blocks: list[dict], line_no: int) -> Optional[dict]:
    if line_no <= 0 or not blocks:
        return None
    candidates = [b for b in blocks if b["start"] <= line_no <= b["end"]]
    if not candidates:
        return None
    return min(candidates, key=lambda b: (b["end"] - b["start"], b["start"]))


def _coerce_int(value) -> Optional[int]:
    try:
        return int(round(float(str(value).strip())))
    except (TypeError, ValueError):
        return None


def _line_mentioned_in_feedback(feedback: str, source_lines: list[str]) -> Optional[int]:
    for match in re.finditer(r"\b(?:satir|satır|line)\s*[:#]?\s*(\d+)\b", feedback or "", flags=re.IGNORECASE):
        line_no = _coerce_int(match.group(1))
        if line_no and 1 <= line_no <= len(source_lines):
            return line_no
    return None


def _quoted_literals(text: str) -> list[str]:
    literals: list[str] = []
    for match in re.finditer(r"['\"]([^'\"\n]{3,80})['\"]", text or ""):
        value = match.group(1).strip()
        if value:
            literals.append(value)
    return literals


def coerce_evidence_llm_payload(raw: dict) -> dict:
    """Fill common missing fields on Evidence LLM JSON before schema validation."""
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    claims = out.get("validated_claims")
    if not isinstance(claims, list):
        return out

    coerced_claims: list[dict] = []
    for claim in claims:
        if not isinstance(claim, dict):
            continue
        item = dict(claim)
        item.setdefault(
            "agent_source",
            str(item.get("agent") or item.get("source") or "unknown").strip() or "unknown",
        )
        if "lines" not in item:
            raw_lines = item.get("line", item.get("line_hint", item.get("satir", [])))
            if isinstance(raw_lines, list):
                item["lines"] = raw_lines
            elif isinstance(raw_lines, int):
                item["lines"] = [raw_lines]
            elif isinstance(raw_lines, str):
                nums = [int(n) for n in re.findall(r"\d+", raw_lines)]
                item["lines"] = nums[:3]
            else:
                item["lines"] = []
        if not isinstance(item.get("lines"), list):
            item["lines"] = []
        item["lines"] = _coerce_lines(item.get("lines"))
        if not item["lines"]:
            raw_range = item.get("line_range") or item.get("lineRange") or item.get("range")
            if isinstance(raw_range, list) and raw_range:
                start = _coerce_int(raw_range[0])
                if start and start >= 1:
                    item["lines"] = [start]
        node_type = str(item.get("node_type") or item.get("nodeType") or "").strip().lower()
        if node_type in {"block", "ast", "statement", "expr", "module"}:
            item["node_type"] = "line"
        elif node_type and node_type not in _AST_NODE_TYPES:
            item.pop("node_type", None)
            item.pop("nodeType", None)
        item.setdefault("feedback", str(item.get("feedback") or item.get("message") or "").strip())
        snippet = item.get("code_snippet")
        if snippet is None:
            item["code_snippet"] = ""
        elif not isinstance(snippet, str):
            item["code_snippet"] = str(snippet)
        item["severity"] = _normalize_severity(item.get("severity"))
        item.setdefault("is_valid", True)
        coerced_claims.append(item)

    out["validated_claims"] = coerced_claims
    if not isinstance(out.get("rejected_claims"), list):
        out["rejected_claims"] = []
    return out


def _normalize_claims(
    claims: list,
    source_lines: list[str],
    *,
    ast_blocks: Optional[list[dict]] = None,
) -> list[dict]:
    blocks = ast_blocks or []
    block_idx = {b["id"]: b for b in blocks}
    norm: list[dict] = []
    seen: set[tuple[str, tuple[int, ...], str]] = set()
    for claim in claims:
        if not isinstance(claim, dict):
            continue

        raw_lines = (
            claim.get("lines")
            if "lines" in claim
            else claim.get("line", claim.get("line_hint", claim.get("satir", [])))
        )
        lines_v = [n for n in _coerce_lines(raw_lines) if n <= len(source_lines)]

        feedback = _clean_evidence_text(
            claim.get(
                "feedback",
                claim.get("message", claim.get("description", claim.get("reason", ""))),
            )
        )
        if not feedback:
            continue

        mentioned_line = _line_mentioned_in_feedback(feedback, source_lines)
        if mentioned_line:
            mentioned_source = source_lines[mentioned_line - 1]
            literals = _quoted_literals(feedback)
            if literals and not any(lit in mentioned_source for lit in literals):
                continue
            lines_v = [mentioned_line]

        agent_source = str(
            claim.get("agent_source", claim.get("agent", claim.get("source", "unknown")))
        )
        severity = _adjust_severity_from_feedback(
            feedback,
            _normalize_severity(claim.get("severity", "medium")),
        )

        # ---- Block-level evidence ----
        line_range: Optional[list[int]] = None
        raw_range = (
            claim.get("line_range")
            or claim.get("lineRange")
            or claim.get("range")
            or claim.get("satir_araligi")
        )
        if isinstance(raw_range, list) and len(raw_range) >= 2:
            start = _coerce_int(raw_range[0])
            end = _coerce_int(raw_range[1])
            if start and end and start >= 1 and end >= start and end <= len(source_lines):
                line_range = [start, end]

        block_id = str(claim.get("block_id") or claim.get("blockId") or "").strip()
        if line_range is None and block_id and block_id in block_idx:
            blk = block_idx[block_id]
            line_range = [int(blk["start"]), int(blk["end"])]

        node_type_raw = str(
            claim.get("node_type") or claim.get("nodeType") or ""
        ).strip().lower()
        node_type = node_type_raw if node_type_raw in _AST_NODE_TYPES else None
        symbol = str(claim.get("symbol") or "").strip() or None

        # If only specific lines were given but they sit inside an AST block,
        # surface the block context so the UI can highlight the full range.
        if line_range is None and lines_v:
            blk = _enclosing_block(blocks, lines_v[0])
            # Only attach when the block is meaningfully wider than a single line.
            if blk and (blk["end"] - blk["start"]) >= 2:
                block_id = str(blk.get("id") or block_id or "")
                line_range = [blk["start"], blk["end"]]
                if not node_type:
                    node_type = blk.get("type")
                if not symbol and blk.get("name"):
                    symbol = blk.get("name")

        if line_range is not None:
            if not node_type:
                blk = block_idx.get(block_id)
                if not blk:
                    blk = _enclosing_block(blocks, line_range[0])
                if blk:
                    block_id = str(blk.get("id") or block_id or "")
                    node_type = blk.get("type")
                    if not symbol and blk.get("name"):
                        symbol = blk.get("name")
            if not lines_v:
                start, end = line_range
                cap = min(end, start + 5)
                lines_v = list(range(start, cap + 1))
            else:
                start, end = line_range
                in_range = [n for n in lines_v if start <= n <= end]
                if not in_range:
                    cap = min(end, start + 5)
                    in_range = list(range(start, cap + 1))
                lines_v = in_range

        literals = _quoted_literals(feedback)
        if literals and lines_v:
            matching_lines = [
                n
                for n in lines_v
                if 1 <= n <= len(source_lines)
                and any(lit in source_lines[n - 1] for lit in literals)
            ]
            if not matching_lines and line_range:
                start, end = line_range
                matching_lines = [
                    n
                    for n in range(start, end + 1)
                    if any(lit in source_lines[n - 1] for lit in literals)
                ]
            if matching_lines:
                lines_v = matching_lines[:4]
            elif not line_range:
                continue

        # ---- Snippet ----
        code_snippet = ""
        if line_range:
            start, end = line_range
            block_lines = source_lines[start - 1: end]
            if len(block_lines) > 8:
                block_lines = block_lines[:5] + ["    # ..."] + block_lines[-2:]
            code_snippet = "\n".join(s.rstrip() for s in block_lines)
        elif lines_v:
            code_snippet = "\n".join(source_lines[n - 1].rstrip() for n in lines_v[:4])

        if not lines_v and not line_range:
            if not _is_supported_file_level_claim(feedback, agent_source, node_type):
                continue
            node_type = "file"

        key = (feedback[:180], tuple(lines_v[:4]), agent_source)
        if key in seen:
            continue
        seen.add(key)

        out: dict = {
            "lines": lines_v[:8],
            "code_snippet": code_snippet,
            "feedback": feedback,
            "agent_source": agent_source,
            "severity": severity,
            "is_valid": True,
        }
        if line_range:
            out["line_range"] = line_range
        if block_id:
            out["block_id"] = block_id
        if node_type:
            out["node_type"] = node_type
        if symbol:
            out["symbol"] = symbol
        norm.append(out)
    return norm


def _normalize_rejected_claims(rejected: list, source_lines: list[str]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in rejected:
        if isinstance(item, dict):
            claim = _clean_evidence_text(
                item.get("claim")
                or item.get("feedback")
                or item.get("description")
                or item.get("message")
                or item.get("text")
                or ""
            )
            reason = _clean_evidence_text(item.get("reason") or item.get("detail") or "")
            agent_source = str(item.get("agent_source") or item.get("agent") or item.get("source") or "unknown").strip()
            raw_lines = item.get("lines") if "lines" in item else item.get("line", item.get("line_hint", []))
        else:
            raw = _clean_evidence_text(item)
            if " -- " in raw:
                claim, reason = raw.split(" -- ", 1)
            else:
                claim, reason = raw, "Somut kod kaniti bulunamadi."
            agent_match = re.match(r"^\[([^\]]+)\]\s*(.*)$", claim)
            agent_source = agent_match.group(1) if agent_match else "unknown"
            if agent_match:
                claim = agent_match.group(2).strip()
            raw_lines = []

        lines_v = [n for n in _coerce_lines(raw_lines) if n <= len(source_lines)]
        if not claim:
            claim = "Desteklenmeyen bulgu"
        if not reason:
            reason = "Somut kod kaniti bulunamadi."
        key = f"{agent_source}|{claim[:160]}|{reason[:160]}|{tuple(lines_v)}"
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            "claim": claim[:240],
            "reason": reason[:240],
            "agent_source": agent_source,
            "lines": lines_v[:4],
        })
    return normalized


def _rejected_claims_for_dropped_llm_claims(
    raw_claims: list,
    source_lines: list[str],
    *,
    ast_blocks: Optional[list[dict]] = None,
) -> list[dict]:
    """Convert LLM claims discarded by normalization into structured rejections."""
    rejected: list[dict] = []
    for raw in raw_claims:
        if not isinstance(raw, dict):
            continue
        if _normalize_claims([raw], source_lines, ast_blocks=ast_blocks):
            continue
        feedback = _clean_evidence_text(
            raw.get("feedback")
            or raw.get("message")
            or raw.get("description")
            or raw.get("reason")
            or "Desteklenmeyen bulgu"
        )
        agent_source = str(
            raw.get("agent_source") or raw.get("agent") or raw.get("source") or "unknown"
        ).strip() or "unknown"
        rejected.append({
            "claim": feedback,
            "reason": "Somut kod kaniti bulunamadi veya iddia kaynak satirlariyla dogrulanamadi.",
            "agent_source": agent_source,
            "lines": _coerce_lines(raw.get("lines", raw.get("line", []))),
        })
    return rejected


def _merge_claim_lists(*claim_lists: list[dict], max_items: int | None = None) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, tuple[int, ...], str]] = set()
    for claims in claim_lists:
        for claim in claims:
            key = (
                str(claim.get("feedback", ""))[:180],
                tuple(claim.get("lines", [])[:4]),
                str(claim.get("agent_source", "unknown")),
            )
            if key in seen:
                continue
            seen.add(key)
            merged.append(claim)
            if max_items is not None and len(merged) >= max_items:
                return merged
    return merged


class EvidenceAgent(BaseAgent):
    name = "evidence"
    description = "Kanit eslestirme ve dogrulama"

    def _pre_schema_normalize(self, result: dict, output_json_schema: dict | None) -> dict:
        from backend.agents.json_output_schema import EVIDENCE_OUTPUT_SCHEMA

        if output_json_schema is EVIDENCE_OUTPUT_SCHEMA:
            return coerce_evidence_llm_payload(result)
        return result

    async def analyze(self, input_data: dict) -> dict:
        source_code = input_data["source_code"]
        agent_findings = input_data["agent_findings"]
        language = input_data.get("language", "python")
        report_language = input_data.get("report_language") or "tr"

        programmatic = self._programmatic_analysis(source_code, agent_findings, language)

        ast_map = _build_ast_evidence_map(source_code, language)
        ast_blocks = ast_map.get("blocks", []) or []

        n_lines = len(source_code.splitlines())
        if n_lines <= 260:
            numbered = build_numbered_code(source_code)
        else:
            excerpt = self._truncate_code(source_code, max_lines=220)
            numbered = build_numbered_code(excerpt)
            numbered += (
                "\n\n[NOTE] Middle of file may be omitted. Agent line numbers refer to the "
                "full original file; map them to this excerpt when visible."
            )

        findings_for_llm = {}
        for agent_name, findings in agent_findings.items():
            if not isinstance(findings, dict):
                continue
            items = []
            for key in ("issues", "style_violations", "threats", "test_failures"):
                for item in (findings.get(key) or [])[:6]:
                    if isinstance(item, dict):
                        items.append({
                            "severity": item.get("severity", "?"),
                            "description": str(item.get("description", item.get("reason", "")))[:130],
                            "line": item.get("line", item.get("line_hint", "")),
                        })
            for key in ("immaturity_indicators", "maturity_indicators"):
                for text in (findings.get(key) or [])[:4]:
                    if isinstance(text, str):
                        items.append({"severity": "info", "description": text[:120]})
            if items:
                findings_for_llm[agent_name] = items

        pre_validated = [
            {"lines": c["lines"], "feedback": c["feedback"][:90], "agent": c["agent_source"]}
            for c in programmatic["validated_claims"][:10]
        ]

        total_in = programmatic["total_claims_received"]
        brief = format_assignment_context_for_prompt(input_data.get("assignment_description"))

        ast_block_payload = ast_blocks[:60]
        ast_block_json = (
            json.dumps(ast_block_payload, ensure_ascii=False, separators=(",", ":"))
            if ast_block_payload
            else "[]"
        )
        if ast_map.get("syntax_error"):
            ast_block_note = (
                "AST_BLOCKS is empty because the source has a SyntaxError "
                f"({ast_map.get('error', '')[:120]}). Use line-level evidence only."
            )
        elif not ast_block_payload:
            ast_block_note = (
                "AST_BLOCKS is empty for this language. Use line-level evidence only."
            )
        else:
            ast_block_note = (
                "Reference AST_BLOCKS via 'block_id' (preferred) or 'line_range' for "
                "structural critique (long function, nested if-else, missing try, etc.)."
            )

        user_prompt = (
            f"Language: {language}\n"
            f"TOTAL_CLAIMS: {total_in}\n\n"
            f"{brief}\n"
            "Numbered source (use these integers in 'lines'):\n"
            f"```\n{numbered}\n```\n\n"
            "AST_BLOCKS (id,type,name,start,end):\n"
            f"{ast_block_json}\n"
            f"{ast_block_note}\n\n"
            f"Agent findings (by agent):\n{json.dumps(findings_for_llm, ensure_ascii=False, separators=(',',':'))}\n\n"
            f"Heuristic pre-map (non-binding):\n{json.dumps(pre_validated, ensure_ascii=False, separators=(',',':'))}\n\n"
            "For every distinct claim above: validate with concrete evidence. Prefer a block "
            "(block_id + line_range + node_type) when the issue is structural; otherwise use "
            "specific lines. Use lines=[] only for whole-file truths. Reject only clear "
            "hallucinations or statements false for this file. "
            f"Set total_claims_received to {total_in}. "
            "If no claims exist, return validated_claims: [] and rejected_claims: []."
            f"{build_llm_user_suffix(report_language=report_language)}"
        )

        if total_in == 0:
            return {
                "validated_claims": [],
                "rejected_claims": [],
                "total_claims_received": 0,
                "total_claims_validated": 0,
                "llm_status": "skipped_no_claims",
            }

        # LLM kanit eslestirmesi tercih edilir; LLM parse/sema hatasinda ise kullanici
        # raporunu bos birakmamak icin yalnizca kaynak koddan dogrulanan programatik
        # kanitlara dusulur.
        try:
            llm_result = await self._call_llm(
                system_prompt=_EVIDENCE_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                required_keys=[
                    "validated_claims",
                    "rejected_claims",
                    "total_claims_received",
                    "total_claims_validated",
                ],
                output_json_schema=EVIDENCE_OUTPUT_SCHEMA,
                temperature=_EVIDENCE_LLM_TEMPERATURE,
                num_predict=_EVIDENCE_NUM_PREDICT,
            )
        except LLMInferenceError as exc:
            fallback = {
                **programmatic,
                "rejected_claims": _normalize_rejected_claims(
                    programmatic.get("rejected_claims", []),
                    source_code.splitlines(),
                ),
                "llm_error": str(exc)[:300],
                "ast_block_count": len(ast_blocks),
                "block_evidence_count": sum(
                    1
                    for c in programmatic.get("validated_claims", [])
                    if isinstance(c, dict) and c.get("line_range")
                ),
                "evidence_quality_flags": ["programmatic_evidence_fallback"],
            }
            if ast_map.get("syntax_error"):
                fallback["ast_syntax_error"] = ast_map.get("error", "")
            return self._with_contract_metadata(
                fallback,
                llm_status="fallback",
                guardrail_flags=["llm_inference_fallback"],
            )
        if not isinstance(llm_result, dict):
            raise LLMInferenceError("[evidence] LLM yaniti gecersiz (JSON nesnesi bekleniyordu).")

        llm_result["total_claims_received"] = total_in
        vclaims = _first_list(
            llm_result,
            "validated_claims",
            "validatedClaims",
            "valid_claims",
            "validClaims",
            "claims",
            "evidence",
        )
        if not isinstance(vclaims, list):
            vclaims = []
        source_lines = source_code.splitlines()
        # Kaynak satirlari yalnizca snippet/satir bicimlendirmesi icin kullanilir
        # (sunum); kanit secimi tamamen LLM'e aittir.
        norm = _normalize_claims(vclaims, source_lines, ast_blocks=ast_blocks)
        if total_in > 0:
            norm = norm[:total_in]
        llm_result["validated_claims"] = norm
        llm_result["total_claims_validated"] = len(norm)
        rejected = _first_list(llm_result, "rejected_claims", "rejectedClaims", "rejections")
        if not isinstance(rejected, list):
            rejected = []
        dropped_rejections = _rejected_claims_for_dropped_llm_claims(
            vclaims[:total_in] if total_in > 0 else vclaims,
            source_lines,
            ast_blocks=ast_blocks,
        )
        llm_result["rejected_claims"] = _normalize_rejected_claims(
            list(rejected) + dropped_rejections,
            source_lines,
        )
        llm_result.setdefault("llm_status", "ok")
        llm_result["ast_block_count"] = len(ast_blocks)
        if ast_map.get("syntax_error"):
            llm_result["ast_syntax_error"] = ast_map.get("error", "")
        # Block-bazli kanit oraninin ayri raporlanmasi UI/audit icin faydali olabilir.
        llm_result["block_evidence_count"] = sum(
            1 for c in norm if isinstance(c, dict) and c.get("line_range")
        )
        llm_result["evidence_quality_flags"] = [
            "source_snippets_rebuilt",
            "rejected_claims_normalized",
        ]

        return llm_result

    def _programmatic_analysis(self, source_code: str, agent_findings: dict, language: str) -> dict:
        """On-dogrulama sayimlari ve kisa ozet -- yalnizca LLM prompt ipucu."""
        lines = source_code.splitlines()
        metrics = get_code_metrics(source_code, language)

        validated = []
        rejected = []
        total = 0

        for agent_name, findings in agent_findings.items():
            if not isinstance(findings, dict):
                continue

            for issue in findings.get("issues", []):
                total += 1
                claim = self._validate_issue(issue, lines, metrics, agent_name)
                if claim:
                    validated.append(claim)
                else:
                    desc = issue.get("description", "")
                    sev = issue.get("severity", "medium")
                    if sev == "info":
                        if _is_supported_file_level_claim(desc, agent_name, None):
                            validated.append({
                                "lines": [],
                                "code_snippet": "",
                                "feedback": desc[:120],
                                "agent_source": agent_name,
                                "severity": "info",
                                "node_type": "file",
                                "is_valid": True,
                            })
                        else:
                            rejected.append(f"[{agent_name}] '{desc[:80]}' -- somut kanit yok")
                    else:
                        rejected.append(f"[{agent_name}] '{desc[:80]}' -- kodda dogrulanamadi")

            for viol in findings.get("style_violations", []):
                total += 1
                claim = self._validate_violation(viol, lines, metrics, agent_name)
                if claim:
                    validated.append(claim)
                else:
                    desc = viol.get("description", viol.get("rule", ""))[:120]
                    sev = viol.get("severity", "low")
                    if sev == "info":
                        if _is_supported_file_level_claim(desc, agent_name, None):
                            validated.append({
                                "lines": [],
                                "code_snippet": "",
                                "feedback": desc,
                                "agent_source": agent_name,
                                "severity": "info",
                                "node_type": "file",
                                "is_valid": True,
                            })
                        else:
                            rejected.append(f"[{agent_name}] '{desc[:80]}' -- somut kanit yok")
                    else:
                        rejected.append(f"[{agent_name}] '{desc[:80]}' -- kodda dogrulanamadi")

            for indicator in findings.get("immaturity_indicators", []):
                total += 1
                claim = self._validate_text_claim(indicator, lines, agent_name, "medium")
                if claim:
                    validated.append(claim)
                elif _is_supported_file_level_claim(indicator, agent_name, None):
                    validated.append({
                        "lines": [],
                        "code_snippet": "",
                        "feedback": indicator,
                        "agent_source": agent_name,
                        "severity": "medium",
                        "node_type": "file",
                        "is_valid": True,
                    })
                else:
                    rejected.append(f"[{agent_name}] '{indicator[:80]}' -- somut kanit yok")

            for indicator in findings.get("maturity_indicators", []):
                total += 1
                claim = self._validate_text_claim(indicator, lines, agent_name, "info")
                if claim:
                    validated.append(claim)
                elif _is_supported_file_level_claim(indicator, agent_name, None):
                    validated.append({
                        "lines": [],
                        "code_snippet": "",
                        "feedback": indicator,
                        "agent_source": agent_name,
                        "severity": "info",
                        "node_type": "file",
                        "is_valid": True,
                    })
                else:
                    rejected.append(f"[{agent_name}] '{indicator[:80]}' -- somut kanit yok")

            for ap in findings.get("antipatterns", []):
                total += 1
                line_num = ap.get("line", 0)
                if 1 <= line_num <= len(lines):
                    validated.append({
                        "lines": [line_num],
                        "code_snippet": lines[line_num - 1].rstrip(),
                        "feedback": ap.get("description", "Anti-pattern tespit edildi"),
                        "agent_source": agent_name,
                        "severity": ap.get("severity", "medium"),
                        "is_valid": True,
                    })

            for fail in findings.get("test_failures", []):
                total += 1
                if isinstance(fail, dict):
                    fail_reason = fail.get("reason", fail.get("test_name", "unknown"))
                else:
                    fail_reason = fail
                validated.append({
                    "lines": [],
                    "code_snippet": "",
                    "feedback": f"Test hatasi: {str(fail_reason)[:300]}",
                    "agent_source": agent_name,
                    "severity": "high",
                    "node_type": "file",
                    "is_valid": True,
                })

            for err in findings.get("runtime_errors", []):
                total += 1
                validated.append({
                    "lines": [],
                    "code_snippet": "",
                    "feedback": f"Runtime hatasi: {err}",
                    "agent_source": agent_name,
                    "severity": "high",
                    "node_type": "file",
                    "is_valid": True,
                })

            for threat in findings.get("threats", []):
                if not isinstance(threat, dict):
                    continue
                total += 1
                line_num = int(threat.get("line") or 0)
                snippet = ""
                if 1 <= line_num <= len(lines):
                    snippet = lines[line_num - 1].rstrip()
                validated.append({
                    "lines": [line_num] if line_num else [],
                    "code_snippet": snippet,
                    "feedback": threat.get("description", "Guvenlik tehdidi"),
                    "agent_source": agent_name,
                    "severity": threat.get("severity", "high"),
                    "node_type": "line" if line_num else "file",
                    "is_valid": True,
                })

        return {
            "validated_claims": validated,
            "rejected_claims": rejected,
            "total_claims_received": total,
            "total_claims_validated": len(validated),
        }

    def _validate_issue(self, issue: dict, lines: list[str], metrics, agent: str) -> dict | None:
        """Code quality issue'sunu satirlarla eslestirir."""
        desc = issue.get("description", "")

        line_nums = re.findall(r'satir\s*(\d+)', desc, re.IGNORECASE)
        line_nums += re.findall(r'line\s*(\d+)', desc, re.IGNORECASE)

        if issue.get("line"):
            try:
                line_nums.append(str(issue["line"]))
            except (TypeError, ValueError):
                pass

        line_nums = [int(n) for n in line_nums if 1 <= int(n) <= len(lines)]

        if not line_nums:
            line_nums = self._find_relevant_lines(desc, lines)

        if line_nums:
            snippets = [lines[n-1].rstrip() for n in line_nums[:4] if n <= len(lines)]
            return {
                "lines": line_nums[:4],
                "code_snippet": "\n".join(snippets),
                "feedback": desc,
                "agent_source": agent,
                "severity": issue.get("severity", "medium"),
                "is_valid": True,
            }
        return None

    def _validate_violation(self, viol: dict, lines: list[str], metrics, agent: str) -> dict | None:
        """Style violation'i satirlarla eslestirir."""
        raw_desc = viol.get("description", viol.get("rule", ""))
        if isinstance(raw_desc, list):
            desc = " ".join(str(x) for x in raw_desc)
        else:
            desc = str(raw_desc or "")
        raw_hint = viol.get("line_hint", "")

        line_nums: list[int] = []
        if isinstance(raw_hint, list):
            for item in raw_hint:
                if isinstance(item, int):
                    line_nums.append(item)
                elif isinstance(item, str):
                    line_nums.extend(int(n) for n in re.findall(r'(\d+)', item))
            line_hint = " ".join(str(x) for x in raw_hint)
        elif isinstance(raw_hint, int):
            line_nums.append(raw_hint)
            line_hint = str(raw_hint)
        else:
            line_hint = str(raw_hint or "")
            line_nums = [int(n) for n in re.findall(r'(\d+)', line_hint)]

        line_nums = [n for n in line_nums if 1 <= n <= len(lines)]

        if not line_nums:
            line_nums = self._find_relevant_lines(desc, lines)

        if line_nums:
            snippets = [lines[n-1].rstrip() for n in line_nums[:4] if n <= len(lines)]
            return {
                "lines": line_nums[:4],
                "code_snippet": "\n".join(snippets),
                "feedback": desc,
                "agent_source": agent,
                "severity": viol.get("severity", "low"),
                "is_valid": True,
            }
        elif (
            "tum dosya" in line_hint.lower()
            or "tum dosya" in desc.lower()
            or "whole file" in line_hint.lower()
            or "whole file" in desc.lower()
            or "entire file" in desc.lower()
        ):
            return {
                "lines": [],
                "code_snippet": "",
                "feedback": desc,
                "agent_source": agent,
                "severity": viol.get("severity", "medium"),
                "node_type": "file",
                "is_valid": True,
            }
        return None

    def _validate_text_claim(self, text: str, lines: list[str], agent: str, severity: str) -> dict | None:
        """Metin tabanli bir iddiay kodda dogrular."""
        found_lines = self._find_relevant_lines(text, lines)
        if found_lines:
            snippets = [lines[n-1].rstrip() for n in found_lines[:3] if n <= len(lines)]
            return {
                "lines": found_lines[:3],
                "code_snippet": "\n".join(snippets),
                "feedback": text,
                "agent_source": agent,
                "severity": severity,
                "is_valid": True,
            }
        return None

    def _find_relevant_lines(self, text: str, lines: list[str]) -> list[int]:
        """Metindeki anahtar kelimeleri kodda arar."""
        keywords = []

        func_names = re.findall(r'(\w+)\(\)', text)
        keywords.extend(func_names)

        code_refs = re.findall(r'`([^`]+)`', text)
        keywords.extend(code_refs)

        identifiers = re.findall(r'\b([a-z_]\w{2,})\b', text)
        for ident in identifiers:
            if ident not in ("bir", "var", "yok", "ile", "icin", "gibi", "daha",
                             "cok", "kisa", "uzun", "iyi", "kotu", "satir", "line",
                             "kod", "code", "fonksiyon", "function", "degisken",
                             "sinif", "class", "metot", "method", "dosya", "file",
                             "kullanilmis", "kullanilmamis", "tespit", "edildi",
                             "olmali", "olmasi", "gerekir", "eksik", "mevcut",
                             "ogrenci", "odev", "analiz", "sonuc", "puan"):
                keywords.append(ident)

        py_keywords = ["for ", "while ", "def ", "class ", "import ", "range(", "len(",
                       "append(", "set(", "dict(", "enumerate(", "sorted(", "try:", "except",
                       "__init__", "__name__", "self.", "return ", "if ", "elif ", "else:"]
        for pk in py_keywords:
            if pk.strip("( :") in text.lower():
                keywords.append(pk.rstrip("(: "))

        found = []
        seen = set()
        for kw in keywords:
            for i, line in enumerate(lines):
                if kw in line and (i + 1) not in seen:
                    found.append(i + 1)
                    seen.add(i + 1)

        return found[:8]
