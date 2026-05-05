"""Assignment safety agent for faculty-created homework briefs.

The agent is hybrid:
- deterministic checks always run first for speed and availability;
- when Ollama is enabled, an LLM review runs inside the same agent to handle
  ambiguous edge cases and defensive/educational contexts.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from backend.core.config import settings
from backend.llm.ollama_client import chat_json


@dataclass(frozen=True)
class AssignmentSafetyIssue:
    code: str
    category: str
    message: str
    matches: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssignmentSafetyResult:
    allowed: bool
    is_programming_assignment: bool
    issues: tuple[AssignmentSafetyIssue, ...]
    llm_used: bool = False
    llm_reason: str | None = None
    review_source: str = "deterministic"

    @property
    def summary(self) -> str:
        if self.allowed:
            return "Odev guvenlik ajani onayladi."
        return " ".join(issue.message for issue in self.issues)

    def to_api_error(self) -> dict:
        return {
            "agent": "assignment_safety",
            "message": self.summary,
            "is_programming_assignment": self.is_programming_assignment,
            "llm_used": self.llm_used,
            "llm_reason": self.llm_reason,
            "review_source": self.review_source,
            "issues": [
                {
                    "code": issue.code,
                    "category": issue.category,
                    "message": issue.message,
                    "matches": list(issue.matches),
                }
                for issue in self.issues
            ],
        }


_TR_TRANSLATION = str.maketrans({
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
    "Ç": "c",
    "Ğ": "g",
    "İ": "i",
    "I": "i",
    "Ö": "o",
    "Ş": "s",
    "Ü": "u",
})


_TR_TRANSLATION.update(str.maketrans({
    "ç": "c",
    "ğ": "g",
    "ı": "i",
    "İ": "i",
    "ö": "o",
    "ş": "s",
    "ü": "u",
    "Ç": "c",
    "Ğ": "g",
    "Ö": "o",
    "Ş": "s",
    "Ü": "u",
}))


def _normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = text.translate(_TR_TRANSLATION).lower()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


def _find_patterns(text: str, patterns: tuple[str, ...]) -> tuple[str, ...]:
    matches: list[str] = []
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            matches.append(pattern)
    return tuple(matches)


def _is_short_topic_seed(text: str) -> bool:
    words = re.findall(r"[a-z0-9+#]+", text)
    if not words or len(words) > 4:
        return False
    return any(len(word) >= 3 for word in words)


_PROGRAMMING_STRONG_PATTERNS: tuple[str, ...] = (
    r"\bprogram(lama|ming)?\b",
    r"\bkod(lama|la| yaz| gelistir| implement| uygula)?\b",
    r"\byazilim\b",
    r"\balgoritma\b",
    r"\bfonksiyon\b",
    r"\bclass\b",
    r"\bsinif(lar|i)?\b",
    r"\bnesne\b",
    r"\boop\b",
    r"\bveri yap",
    r"\bagac\b",
    r"\bgraf\b",
    r"\bhash\b",
    r"\bstack\b",
    r"\byigin\b",
    r"\bkuyruk\b",
    r"\blinked list\b",
    r"\bbinary search tree\b",
    r"\bbst\b",
    r"\bapi\b",
    r"\brest\b",
    r"\bbot\b",
    r"\bfrontend\b",
    r"\bbackend\b",
    r"\bweb\b",
    r"\bveritabani\b",
    r"\bveri tabani\b",
    r"\bsql\b",
    r"\bpython\b",
    r"\bjava(script)?\b",
    r"\btypescript\b",
    r"\bc\+\+\b",
    r"\bc#\b",
    r"\bpytest\b",
    r"\bbirim test\b",
    r"\bunit test\b",
    r"\bkomut satiri\b",
    r"\bkonsol\b",
    r"\bsiniflandir(ici|ma)?\b",
)

_PROGRAMMING_SOFT_PATTERNS: tuple[str, ...] = (
    r"\bhesapla(ma|yici)?\b",
    r"\bislem(ci|leri|ler)?\b",
    r"\bsistem(i)?\b",
    r"\buygulama(si)?\b",
    r"\bsimulasyon\b",
    r"\bmodel(le|i)?\b",
    r"\bmodul\b",
    r"\bdosya\b",
    r"\bgirdi\b",
    r"\bcikti\b",
    r"\bmatris\b",
    r"\bvektor\b",
    r"\bfaktoriyel\b",
    r"\bpolinom\b",
    r"\bdenklem\b",
    r"\bkayit\b",
    r"\bsorgu\b",
    r"\bkatalog\b",
    r"\bkutuphane\b",
    r"\baraba\b",
    r"\botomobil\b",
    r"\btasit\b",
    r"\bvehicle\b",
    r"\barac(i)?\b",
    r"\bpark\b",
    r"\benvanter\b",
)

_NON_PROGRAMMING_PATTERNS: tuple[str, ...] = (
    r"\bmakale\b",
    r"\bdeneme\b",
    r"\bsunum\b",
    r"\bposter\b",
    r"\brapor yaz\b",
    r"\bokuma odev",
    r"\btartisma\b",
    r"\bkavram haritasi\b",
)

_UNSAFE_CATEGORY_PATTERNS: dict[str, tuple[str, ...]] = {
    "crime": (
        r"\bhirsiz(lik|ligi|la|lama)?\b",
        r"\bdolandiricilik\b",
        r"\bsahtecilik\b",
        r"\bsahte (belge|kimlik|fatura)",
        r"\bkimlik (cal|hirsiz)",
        r"\bkredi karti\b.*\b(cal|kopya|sahte)",
        r"\bphishing\b",
        r"\boltala(ma)?\b",
        r"\bmalware\b",
        r"\bzararli yazilim\b",
        r"\bvirus\b",
        r"\btrojan\b",
        r"\bransomware\b",
        r"\bkeylogger\b",
        r"\bddos\b",
        r"\bcredential\b",
        r"\bsifre\w*\b.*\b(topla\w*|cal\w*|kir\w*|kirma)\b",
        r"\b(topla\w*|cal\w*|kopyala\w*)\b.*\b(sifre|kimlik|kredi karti|credential)\w*\b",
        r"\bbrute force\b",
        r"\bbypass\b.*\b(sifre|guvenlik|login)",
        r"\bhack(le|lemek|leme)?\b",
        r"\byasa disi\b.*\b(satis|pazar|market)",
    ),
    "sexual": (
        r"\bcinsellik\b",
        r"\bporn(o|ografi)?\b",
        r"\berotik\b",
        r"\bciplak\b",
        r"\bnude\b",
        r"\bsex\b",
        r"\byetiskin icerik\b",
        r"\bfuhus\b",
        r"\btaciz\b",
    ),
    "drugs": (
        r"\buyusturucu\b",
        r"\bmadde kullanimi\b",
        r"\bmadde satisi\b",
        r"\besrar\b",
        r"\bkokain\b",
        r"\beroin\b",
        r"\bmetamfetamin\b",
        r"\bmet\b",
        r"\bfentanil\b",
        r"\bnarkotik\b",
        r"\bdrug\b",
    ),
    "terrorism": (
        r"\bteror\b",
        r"\bterror",
        r"\bterorist\b",
        r"\bpropaganda\b.*\bteror",
        r"\bradikallesme\b",
        r"\bbomba\b",
        r"\bpatlayici\b",
        r"\bied\b",
        r"\bsaldiri plani\b",
    ),
    "violence": (
        r"\bsilah\b",
        r"\bsilahli\b",
        r"\boldur(me|mek|me)\b",
        r"\byarala(ma|mak)?\b",
        r"\bintihar\b",
        r"\bkendine zarar\b",
    ),
}

_SAFETY_OR_EDUCATIONAL_CONTEXT_PATTERNS: tuple[str, ...] = (
    r"\bfarkindalik\b",
    r"\btespit\b",
    r"\bsiniflandir",
    r"\bfiltre(le|leme)?\b",
    r"\bmoderasyon\b",
    r"\braporla",
    r"\banaliz\b",
    r"\bonle(me|yici)?\b",
    r"\bsavunmaci\b",
    r"\bguvenli\b",
    r"\boyuncak veri\b",
    r"\bsentetik veri\b",
    r"\bkimlik bilgisi topla(nma|ma)(yacak|dan)?\b",
    r"\bgercek (kimlik|sifre|kullanici) bilgisi (toplama|kullanma)",
    r"\bbildirim sistemi\b",
    r"\bdestek sistemi\b",
    r"\brisk anketi\b",
)

_CLEAR_ENABLEMENT_PATTERNS: tuple[str, ...] = (
    r"\b(cal\w*|hirsizla\w*|topla\w*|kopyala\w*)\b.*\b(sifre|kimlik|kredi karti|credential)\w*\b",
    r"\b(sifre|kimlik|kredi karti|credential)\w*\b.*\b(cal\w*|topla\w*|kopyala\w*)\b",
    r"\b(phishing|oltalama)\b.*\b(mail|eposta|sayfa|site)\b.*\b(gonder|yay|kur|olustur)",
    r"\b(malware|zararli yazilim|ransomware|keylogger|trojan)\b.*\b(yaz|gelistir|uret|kur|calistir)",
    r"\bddos\b.*\b(yap|duzenle|baslat|araci|bot)",
    r"\bbypass\b.*\b(sifre|guvenlik|login)",
    r"\b(satis|sat|stok|musteri|pazar|market)\b.*\b(uyusturucu|esrar|kokain|eroin|metamfetamin|fentanil)",
    r"\b(uyusturucu|esrar|kokain|eroin|metamfetamin|fentanil)\b.*\b(satis|sat|stok|musteri|pazar|market)",
    r"\b(teror|terorist|terror)\b.*\b(yay|reklam|uye kazan|radikallestir)",
    r"\b(bomba|patlayici|ied)\b.*\b(yap|uret|tasarla|tarif|plan)",
    r"\b(silah|saldiri|oldur|yarala)\b.*\b(plan|optimiz|hedef|simulasyon)",
)

_CATEGORY_LABELS = {
    "crime": "suc",
    "sexual": "cinsellik",
    "drugs": "madde kullanimi",
    "terrorism": "teror",
    "violence": "siddet",
}


def _llm_text_has_safe_educational_guardrail(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    has_safety_context = bool(_find_patterns(normalized, _SAFETY_OR_EDUCATIONAL_CONTEXT_PATTERNS))
    has_negative_guardrail = bool(
        re.search(r"\b(gercek )?(kimlik|sifre|kullanici) bilgisi topla(nma|ma)(yacak|dan)?\b", normalized)
        or re.search(r"\b(credential|sifre|kimlik) topla(nma|ma)(yacak|dan)?\b", normalized)
        or re.search(r"\boperasyonel (saldiri|zarar) adimi verme(yecek|den)?\b", normalized)
        or re.search(r"\bsaldiri adimi verme(yecek|den)?\b", normalized)
    )
    return has_safety_context and has_negative_guardrail


class AssignmentSafetyAgent:
    """Single creation-time agent for faculty assignment policy checks."""

    name = "assignment_safety"
    description = "Odevin programlama odevine uygunlugunu ve riskli icerigi denetler."

    def _is_safe_educational_context(self, category: str, text: str, matches: tuple[str, ...]) -> bool:
        if not matches:
            return False
        clear_enablement = _find_patterns(text, _CLEAR_ENABLEMENT_PATTERNS)
        has_clear_negative_guardrail = bool(
            re.search(r"\b(gercek )?(kimlik|sifre|kullanici) bilgisi topla(nma|ma)(yacak|dan)?\b", text)
            or re.search(r"\b(credential|sifre|kimlik) topla(nma|ma)(yacak|dan)?\b", text)
        )
        if clear_enablement and not has_clear_negative_guardrail:
            return False
        if not _find_patterns(text, _SAFETY_OR_EDUCATIONAL_CONTEXT_PATTERNS):
            return False
        if category == "sexual":
            return bool(re.search(r"\b(bildirim|destek|moderasyon|filtre|taciz onleme)\b", text))
        return True

    def analyze(self, *, title: str, description: str | None = None, course_context: str | None = None) -> AssignmentSafetyResult:
        """Deterministic baseline review."""
        assignment_text = _normalize_text(f"{title or ''} {description or ''}")
        context_text = _normalize_text(course_context or "")
        combined = _normalize_text(f"{assignment_text} {context_text}")

        strong = _find_patterns(assignment_text, _PROGRAMMING_STRONG_PATTERNS)
        soft = _find_patterns(assignment_text, _PROGRAMMING_SOFT_PATTERNS)
        context_strong = _find_patterns(context_text, _PROGRAMMING_STRONG_PATTERNS)
        non_programming = _find_patterns(assignment_text, _NON_PROGRAMMING_PATTERNS)
        unsafe_matches = tuple(
            match
            for patterns in _UNSAFE_CATEGORY_PATTERNS.values()
            for match in _find_patterns(combined, patterns)
        )

        # Course context can help ambiguous titles ("Matris Islemleri"), but it
        # cannot turn a purely non-programming brief into a programming homework.
        is_programming = bool(strong) or len(soft) >= 2 or (bool(soft) and bool(context_strong))
        if (
            not is_programming
            and context_strong
            and _is_short_topic_seed(assignment_text)
            and not non_programming
            and not unsafe_matches
        ):
            is_programming = True
        if non_programming and not strong:
            is_programming = False

        issues: list[AssignmentSafetyIssue] = []
        for category, patterns in _UNSAFE_CATEGORY_PATTERNS.items():
            matches = _find_patterns(combined, patterns)
            if not matches:
                continue
            if self._is_safe_educational_context(category, combined, matches):
                continue
            issues.append(
                AssignmentSafetyIssue(
                    code=f"unsafe_{category}",
                    category=category,
                    message=f"Odev guvenlik ajani: Odev metninde {_CATEGORY_LABELS.get(category, category)} kapsaminda riskli icerik bulundu. Lutfen sucluluk, cinsellik, madde kullanimi, teror veya siddet iceren ogeleri kaldirin.",
                    matches=matches,
                )
            )

        return AssignmentSafetyResult(
            allowed=not issues,
            is_programming_assignment=is_programming,
            issues=tuple(issues),
        )

    async def analyze_hybrid(
        self,
        *,
        title: str,
        description: str | None = None,
        course_context: str | None = None,
    ) -> AssignmentSafetyResult:
        """Run deterministic checks plus LLM review when available."""
        deterministic = self.analyze(
            title=title,
            description=description,
            course_context=course_context,
        )

        if not settings.ollama_enabled:
            return deterministic

        llm_result = await self._call_llm_review(
            title=title,
            description=description,
            course_context=course_context,
            deterministic=deterministic,
        )
        if llm_result is None:
            if deterministic.allowed:
                return deterministic
            return AssignmentSafetyResult(
                allowed=False,
                is_programming_assignment=deterministic.is_programming_assignment,
                issues=deterministic.issues,
                llm_used=False,
                llm_reason="LLM review could not be completed; deterministic risk signal was kept.",
                review_source="deterministic_fallback",
            )

        return self._merge_llm_review(deterministic, llm_result)

    async def _call_llm_review(
        self,
        *,
        title: str,
        description: str | None,
        course_context: str | None,
        deterministic: AssignmentSafetyResult,
    ) -> dict[str, Any] | None:
        system_prompt = """\
You are the assignment safety reviewer for a university faculty panel.
Return ONLY one valid JSON object. No markdown, no commentary.

Decide whether the instructor's homework brief may be created.

JSON shape:
{
  "allowed": true,
  "is_programming_assignment": true,
  "risk_categories": [],
  "reason": "short Turkish explanation",
  "suggested_fix": ""
}

Rules:
- Approve all harmless assignment briefs, even if they are not programming assignments.
- is_programming_assignment is informational only; NEVER reject only because it is not programming.
- Block assignments that ask students to create, optimize, simulate, facilitate, or instruct crime,
  sexual content, drug use, terrorism, self-harm, or real-world violence.
- Educational and defensive safety work can be allowed if it clearly avoids enabling harm, e.g.
  "phishing awareness classifier", "malware indicator detector", or "terror propaganda detection"
  with toy data, no credential collection, no deployment, no operational instructions.
- If the brief is ambiguous but there is no concrete unsafe element, approve it.
- risk_categories values must be chosen from:
  ["crime","sexual","drugs","terrorism","violence"].
- Write reason and suggested_fix in Turkish.
"""

        deterministic_payload = {
            "allowed": deterministic.allowed,
            "is_programming_assignment": deterministic.is_programming_assignment,
            "issues": [
                {
                    "code": issue.code,
                    "category": issue.category,
                    "message": issue.message,
                }
                for issue in deterministic.issues
            ],
        }
        user_prompt = (
            "Review this assignment creation request.\n\n"
            f"Course context: {course_context or ''}\n"
            f"Title: {title or ''}\n"
            f"Description: {description or ''}\n\n"
            f"Deterministic precheck: {deterministic_payload}\n\n"
            "Return JSON only."
        )

        try:
            return await chat_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.1,
                num_predict=512,
                use_cache=False,
            )
        except Exception:
            return None

    def _merge_llm_review(self, deterministic: AssignmentSafetyResult, llm_result: dict[str, Any]) -> AssignmentSafetyResult:
        allowed = bool(llm_result.get("allowed", False))
        is_programming = bool(llm_result.get("is_programming_assignment", deterministic.is_programming_assignment))
        reason = str(llm_result.get("reason") or "").strip() or None
        suggested_fix = str(llm_result.get("suggested_fix") or "").strip()

        raw_categories = llm_result.get("risk_categories")
        categories = [
            str(category).strip()
            for category in raw_categories
            if str(category).strip()
        ] if isinstance(raw_categories, list) else []

        unsafe_categories = [
            category
            for category in categories
            if category in {"crime", "sexual", "drugs", "terrorism", "violence"}
        ]

        if allowed and unsafe_categories and deterministic.allowed and _llm_text_has_safe_educational_guardrail(
            f"{reason or ''}\n{suggested_fix}"
        ):
            return AssignmentSafetyResult(
                allowed=True,
                is_programming_assignment=is_programming,
                issues=(),
                llm_used=True,
                llm_reason=reason,
                review_source="hybrid_llm_safe_educational",
            )

        if not unsafe_categories:
            return AssignmentSafetyResult(
                allowed=True,
                is_programming_assignment=is_programming,
                issues=(),
                llm_used=True,
                llm_reason=reason,
                review_source="hybrid_llm",
            )

        if deterministic.allowed and _llm_text_has_safe_educational_guardrail(
            f"{reason or ''}\n{suggested_fix}"
        ):
            return AssignmentSafetyResult(
                allowed=True,
                is_programming_assignment=is_programming,
                issues=(),
                llm_used=True,
                llm_reason=reason,
                review_source="hybrid_llm_safe_educational",
            )

        issues: list[AssignmentSafetyIssue] = []
        for category in unsafe_categories:
            label = _CATEGORY_LABELS.get(category, category)
            issues.append(
                AssignmentSafetyIssue(
                    code=f"unsafe_{category}",
                    category=category,
                    message=(
                        suggested_fix
                        or reason
                        or f"Odev guvenlik ajani: Odev metninde {label} kapsaminda riskli icerik bulundu."
                    ),
                )
            )

        if not issues and deterministic.issues:
            issues.extend(deterministic.issues)
        if not issues:
            issues.append(
                AssignmentSafetyIssue(
                    code="assignment_safety_rejected",
                    category="ambiguous",
                    message=reason or "Odev guvenlik ajani: Odev metni guvenlik kontrolunden gecemedi.",
                )
            )

        return AssignmentSafetyResult(
            allowed=False,
            is_programming_assignment=is_programming,
            issues=tuple(issues),
            llm_used=True,
            llm_reason=reason,
            review_source="hybrid_llm",
        )
