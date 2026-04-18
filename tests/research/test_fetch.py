"""fetch_and_extract_text safety + behaviour tests."""
import pytest
import respx
import httpx

from src.research.fetch import (
    domain_allowed,
    is_private_host,
    choose_fallback_pdf_url,
    FetchConfig,
    fetch_and_extract_text,
)


ALLOW = ("arxiv.org", "openreview.net", "proceedings.mlr.press")


def test_domain_allowed_exact():
    assert domain_allowed("arxiv.org", ALLOW) is True


def test_domain_allowed_subdomain():
    assert domain_allowed("www.arxiv.org", ALLOW) is True
    assert domain_allowed("export.arxiv.org", ALLOW) is True


def test_domain_allowed_suffix_must_be_label():
    assert domain_allowed("evilarxiv.org", ALLOW) is False
    assert domain_allowed("arxiv.org.evil.com", ALLOW) is False


def test_domain_allowed_case_insensitive():
    assert domain_allowed("ARXIV.ORG", ALLOW) is True


def test_domain_allowed_empty():
    assert domain_allowed("", ALLOW) is False


def test_is_private_loopback(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda h: "127.0.0.1")
    assert is_private_host("localhost") is True


def test_is_private_private_range(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda h: "10.0.0.5")
    assert is_private_host("internal") is True


def test_is_private_public(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda h: "8.8.8.8")
    assert is_private_host("dns.google") is False


def test_is_private_fail_closed(monkeypatch):
    def _raise(_):
        raise OSError("boom")
    monkeypatch.setattr("socket.gethostbyname", _raise)
    assert is_private_host("weird.invalid") is True


def test_fallback_pdf_url_abs():
    assert choose_fallback_pdf_url(
        "https://arxiv.org/abs/2410.12345"
    ) == "https://arxiv.org/pdf/2410.12345"


def test_fallback_pdf_url_version():
    assert choose_fallback_pdf_url(
        "https://arxiv.org/abs/2410.12345v2"
    ) == "https://arxiv.org/pdf/2410.12345v2"


def test_fallback_pdf_url_non_arxiv():
    assert choose_fallback_pdf_url("https://openreview.net/forum?id=X") is None


def _cfg(allow=("arxiv.org",), max_bytes=5_242_880, timeout_s=30):
    return FetchConfig(allowlist=tuple(allow), max_bytes=max_bytes, timeout_s=timeout_s)


@pytest.mark.asyncio
@respx.mock
async def test_fetch_html_happy(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda h: "151.101.0.1")  # public-ish
    respx.get("https://arxiv.org/abs/2410.12345").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=b"<html><body><h1>Title</h1><p>body text</p></body></html>",
        )
    )
    res = await fetch_and_extract_text("https://arxiv.org/abs/2410.12345", _cfg())
    assert res.ok is True
    assert "body text" in res.text


@pytest.mark.asyncio
async def test_fetch_out_of_allowlist():
    res = await fetch_and_extract_text("https://evil.example/paper", _cfg())
    assert res.ok is False
    assert "allowlist" in res.error


@pytest.mark.asyncio
async def test_fetch_private_host(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda h: "127.0.0.1")
    res = await fetch_and_extract_text("https://arxiv.org/abs/X", _cfg())
    assert res.ok is False
    assert "private" in res.error or "loopback" in res.error


@pytest.mark.asyncio
@respx.mock
async def test_fetch_bad_content_type(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda h: "151.101.0.1")
    respx.get("https://arxiv.org/abs/X").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "application/zip"},
            content=b"PK\x03\x04",
        )
    )
    res = await fetch_and_extract_text("https://arxiv.org/abs/X", _cfg())
    assert res.ok is False
    assert "content-type" in res.error.lower()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_size_cap(monkeypatch):
    monkeypatch.setattr("socket.gethostbyname", lambda h: "151.101.0.1")
    big = b"x" * (1024 * 10)
    respx.get("https://arxiv.org/abs/Y").mock(
        return_value=httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=big,
        )
    )
    res = await fetch_and_extract_text(
        "https://arxiv.org/abs/Y",
        _cfg(max_bytes=1024),
    )
    assert res.ok is False
    assert "size" in res.error.lower()
