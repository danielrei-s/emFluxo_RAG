"""Filtro de saída (F4-T05, INV-08): sem HTML ativo, sem imagens, links só da allowlist."""

from __future__ import annotations

import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from rag_core.ingestion.sanitize import clean_text

IMAGE_REMOVED = "[imagem removida]"
_PAREN = r"\((?:[^()]|\([^()]*\))*\)"  # parênteses com um nível de aninhamento
_IMAGE = re.compile(rf"!\[[^\]]*\](?:{_PAREN}|\[[^\]]*\])?")
_LINK = r"\[(?P<text>[^\]]*)\]\(\s*(?P<url>(?:[^()\s]|\([^()\s]*\))*)(?:\s+\"[^\"]*\")?\s*\)"
_REF_LINK = r"\[(?P<ref_text>[^\]]+)\]\[(?P<ref>[^\]]*)\]"
_AUTOLINK = r"<(?P<auto>[A-Za-z][A-Za-z0-9+.-]*:[^<>\s]*)>"
_BARE = r"(?P<bare>(?:\b(?:https?|ftp)://|\bwww\.)[^\s<>\]\)\"']+)"
_TOKEN = re.compile(rf"{_LINK}|{_REF_LINK}|{_AUTOLINK}|{_BARE}", re.IGNORECASE)
_DEFINITION = re.compile(r"^[ \t]*\[(?P<label>[^\]]+)\]:[ \t]*\S+.*$\n?", re.MULTILINE)
_DANGEROUS_SCHEME = re.compile(r"(?:java|vb)script\s*:|\bdata\s*:\s*[a-z]+/[a-z0-9.+-]+", re.I)
_TRAILING = ".,;:!?"


def _normalize_domains(domains: Iterable[str]) -> frozenset[str]:
    return frozenset(d.strip().lower().lstrip("*").lstrip(".") for d in domains if d.strip())


def _split(url: str, *, bare: bool = False) -> tuple[str, str | None]:
    """``(esquema, anfitrião)``; ``www.`` solto assume ``https``; erros dão ``("", None)``."""
    target = url if "://" in url else f"https://{url}"
    try:
        parts = urlsplit(target)
        scheme = parts.scheme.lower() if "://" in url else ("https" if bare else "")
        return scheme, parts.hostname
    except ValueError:
        return "", None


def _allowed(url: str, domains: frozenset[str], *, bare: bool = False) -> bool:
    scheme, host = _split(url, bare=bare)
    if scheme != "https" or not host:
        return False
    return any(host == d or host.endswith("." + d) for d in domains)


def _removed(url: str) -> str:
    return f"(ligação removida: {_split(url, bare=True)[1] or 'desconhecido'})"


def _replace(match: re.Match[str], domains: frozenset[str], defined: set[str]) -> str:
    if match.group("url") is not None:
        text, url = match.group("text"), match.group("url")
        return match.group(0) if url and _allowed(url, domains) else text
    if match.group("ref_text") is not None:
        label = (match.group("ref") or match.group("ref_text")).strip().lower()
        # [1][2] sem definição é uma citação, não um link por referência
        return match.group("ref_text") if label in defined else match.group(0)
    if match.group("auto") is not None:
        url = match.group("auto")
        return url if _allowed(url, domains) else _removed(url)
    raw = match.group("bare")
    url = raw.rstrip(_TRAILING)
    trailing = raw[len(url) :]
    return (url if _allowed(url, domains, bare=True) else _removed(url)) + trailing


def sanitize_answer_markdown(text: str, *, allowed_link_domains: Iterable[str] = ()) -> str:
    """Remove imagens, links fora da allowlist e HTML da resposta (INV-08)."""
    domains = _normalize_domains(allowed_link_domains)
    current = clean_text(text).text
    previous = None
    while previous != current:  # imagens dentro de imagens/links: repete até estabilizar
        previous = current
        current = _IMAGE.sub(IMAGE_REMOVED, current)
    defined = {m.group("label").strip().lower() for m in _DEFINITION.finditer(current)}
    current = _DEFINITION.sub("", current)
    current = _TOKEN.sub(lambda m: _replace(m, domains, defined), current)
    current = _DANGEROUS_SCHEME.sub("(ligação removida)", current)
    current = current.replace("<", "&lt;").replace(">", "&gt;").replace("![", "! [")
    return clean_text(current).text.strip()
