"""fetch_and_summarize_paper internals — allowlist, SSRF, redirect, PDF, HTML."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import urlparse

import httpx


_ARXIV_ABS_RE = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?)/?$",
    re.IGNORECASE,
)


def domain_allowed(host: str, allowlist: Iterable[str]) -> bool:
    host = (host or "").strip().lower()
    if not host:
        return False
    for allowed in allowlist:
        a = allowed.strip().lower()
        if host == a or host.endswith("." + a):
            return True
    return False


def is_private_host(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except (OSError, ValueError):
        return True
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast


def choose_fallback_pdf_url(url: str) -> Optional[str]:
    m = _ARXIV_ABS_RE.match(url)
    if not m:
        return None
    return f"https://arxiv.org/pdf/{m.group(1)}"


@dataclass(frozen=True)
class FetchConfig:
    allowlist: tuple[str, ...]
    max_bytes: int
    timeout_s: int


@dataclass
class FetchResult:
    ok: bool
    text: str = ""
    content_type: str = ""
    final_url: str = ""
    error: str = ""


def _strip_html(raw: bytes) -> str:
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript"):
                self._skip += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self._skip:
                self._skip -= 1

        def handle_data(self, data):
            if self._skip == 0:
                self.parts.append(data)

    parser = _Stripper()
    try:
        parser.feed(raw.decode("utf-8", errors="replace"))
    except Exception:
        return raw.decode("utf-8", errors="replace")
    joined = " ".join(parser.parts)
    return re.sub(r"\s+", " ", joined).strip()


def _strip_pdf(raw: bytes) -> str:
    from io import BytesIO
    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(raw))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as e:
        raise RuntimeError(f"pdf parse failed: {e}")


async def _fetch_one(url: str, cfg: FetchConfig) -> FetchResult:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not domain_allowed(host, cfg.allowlist):
        return FetchResult(ok=False, error=f"domain not in allowlist: {host}")
    if is_private_host(host):
        return FetchResult(ok=False, error=f"private/loopback host refused: {host}")

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            max_redirects=3,
            timeout=cfg.timeout_s,
        ) as client:
            async with client.stream("GET", url) as resp:
                final = str(resp.url)
                final_host = urlparse(final).hostname or ""
                if not domain_allowed(final_host, cfg.allowlist):
                    return FetchResult(ok=False, error=f"redirect landed off-allowlist: {final_host}", final_url=final)
                if is_private_host(final_host):
                    return FetchResult(ok=False, error=f"redirect landed on private host: {final_host}", final_url=final)
                if resp.status_code >= 400:
                    return FetchResult(ok=False, error=f"http {resp.status_code}", final_url=final)
                ctype = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
                if ctype not in ("text/html", "application/pdf"):
                    return FetchResult(ok=False, error=f"content-type not allowed: {ctype}", final_url=final, content_type=ctype)
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > cfg.max_bytes:
                        return FetchResult(ok=False, error=f"response size exceeded {cfg.max_bytes} bytes", final_url=final, content_type=ctype)
                raw = bytes(buf)
    except httpx.HTTPError as e:
        return FetchResult(ok=False, error=f"http error: {e}")

    try:
        if ctype == "text/html":
            text = _strip_html(raw)
        else:
            text = _strip_pdf(raw)
    except Exception as e:
        return FetchResult(ok=False, error=str(e), final_url=final, content_type=ctype)

    return FetchResult(ok=True, text=text, content_type=ctype, final_url=final)


async def fetch_and_extract_text(url: str, cfg: FetchConfig) -> FetchResult:
    res = await _fetch_one(url, cfg)
    if res.ok:
        return res
    fallback = choose_fallback_pdf_url(url)
    if fallback is not None:
        alt = await _fetch_one(fallback, cfg)
        if alt.ok:
            return alt
    return res
