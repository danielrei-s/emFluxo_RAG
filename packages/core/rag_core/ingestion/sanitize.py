"""Sanitização de texto e deteção de prompt injection (F3-T02, INV-06).

Camada de defesa, não garantia: ``detect_injection`` devolve nomes de regra e quem usa decide
(F3-T12 marca o chunk com ``suspected_injection``).
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_TAG_START, _TAG_END = 0xE0000, 0xE007F
_TRAILING_BLANKS = re.compile(r"[ \t]+$", re.MULTILINE)
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class CleanResult:
    text: str
    removed: dict[str, int] = field(default_factory=dict)


def _removal_key(ch: str) -> str | None:
    if _TAG_START <= ord(ch) <= _TAG_END:
        return "tag"
    category = unicodedata.category(ch)
    if category == "Cc":
        return None if ch in "\n\t" else "Cc"
    return category if category in {"Cf", "Co"} else None


def clean_text(s: str) -> CleanResult:
    """Remove caracteres invisíveis/perigosos (Cc, Cf, Co, tags) e normaliza para NFC."""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    removed: dict[str, int] = {}
    kept: list[str] = []
    for ch in s:
        key = _removal_key(ch)
        if key is None:
            kept.append(ch)
        else:
            removed[key] = removed.get(key, 0) + 1
    text = unicodedata.normalize("NFC", "".join(kept))
    text = _BLANK_LINES.sub("\n\n", _TRAILING_BLANKS.sub("", text))
    return CleanResult(text=text, removed=removed)


_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(pattern, re.IGNORECASE))
    for name, pattern in (
        (
            "ignore_instructions",
            r"ignor(?:a|e|ar)\s+(?:todas\s+)?(?:as\s+)?instru"
            r"|ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)\s+instructions",
        ),
        ("forget_instructions", r"esquece\s+(?:tudo|as\s+instru)"),
        ("role_override", r"a\s+partir\s+de\s+agora\s+(?:és|tu\s+és|vais)\b|\byou\s+are\s+now\b"),
        ("system_prompt", r"(?:prompt|mensagem)\s+de\s+sistema|system\s+prompt"),
        ("respond_only", r"responde\s+apenas|respond\s+only\s+with"),
        ("fake_tags", r"</?(?:system|assistant|document|instructions)>"),
        ("md_image_exfil", r"!\[[^\]]*\]\(\s*https?://[^)\s]*\?[^)\s]*\)"),
        ("exfil_email", r"envia\s+(?:isto|os\s+dados|para)\b[^\n]*@"),
        ("base64_blob", r"[A-Za-z0-9+/]{200,}={0,2}"),
    )
)


def detect_injection(text: str) -> list[str]:
    """Devolve os nomes das regras de injection que o texto aciona (ordem fixa, sem repetidos)."""
    return [name for name, pattern in _RULES if pattern.search(text)]
