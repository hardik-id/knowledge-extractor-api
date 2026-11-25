"""The reference fetch: what it refuses, and what it keeps. No real network."""

import httpx2
import pytest

from apps.extraction.custom_chunking import fetch
from apps.extraction.custom_chunking.fetch import ReferenceRefused, fetch_reference

PUBLIC = "93.184.216.34"


class Resolver(list[str]):
    """The hosts looked up; ``answer`` is what every host resolves to."""

    answer: list[str]


@pytest.fixture
def resolves(monkeypatch: pytest.MonkeyPatch) -> Resolver:
    looked_up = Resolver()
    looked_up.answer = [PUBLIC]

    def resolve(host: str) -> list[str]:
        looked_up.append(host)
        return looked_up.answer

    monkeypatch.setattr(fetch, "_resolve", resolve)
    return looked_up


def page(
    body: bytes | str = "<html><head><title>T</title></head><body><h1>Hi</h1>"
    "<script>evil()</script><p>First</p><p>Second &amp; more</p></body></html>",
    content_type: str = "text/html; charset=utf-8",
    status: int = 200,
    headers: dict[str, str] | None = None,
) -> tuple[httpx2.MockTransport, list[httpx2.Request]]:
    seen: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.append(request)
        return httpx2.Response(
            status,
            content=body,
            headers={"content-type": content_type, **(headers or {})},
        )

    return httpx2.MockTransport(handler), seen


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "ftp://example.com/",
        "file:///etc/passwd",
        "//example.com/x",
        "example.com",
        "https://",
        "https://user:pw@example.com/",
        "https://example.com:8443/",
        "https://example.com:bad/",
    ],
)
def test_a_link_that_is_not_plain_https_is_refused(
    url: str, resolves: Resolver
) -> None:
    with pytest.raises(ReferenceRefused):
        fetch_reference(url, transport=page()[0])
    assert resolves == []


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "224.0.0.1",
        "240.0.0.1",
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",
        "::ffff:10.0.0.1",
        "64:ff9b::7f00:1",
        "2002:7f00:1::",
        "fec0::1",
        "not an address",
    ],
)
def test_a_host_with_a_non_public_address_is_refused(
    address: str, resolves: Resolver
) -> None:
    resolves.answer[:] = [address]
    transport, seen = page()
    with pytest.raises(ReferenceRefused):
        fetch_reference("https://example.com/", transport=transport)
    assert seen == []


def test_one_non_public_address_among_public_ones_refuses(resolves: Resolver) -> None:
    resolves.answer[:] = [PUBLIC, "10.0.0.5"]
    transport, seen = page()
    with pytest.raises(ReferenceRefused):
        fetch_reference("https://example.com/", transport=transport)
    assert seen == []


def test_a_host_that_does_not_resolve_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def gone(host: str) -> list[str]:
        raise ReferenceRefused("The address could not be found.")

    monkeypatch.setattr(fetch, "_resolve", gone)
    with pytest.raises(ReferenceRefused):
        fetch_reference("https://nowhere.example/", transport=page()[0])


def test_the_connection_goes_to_the_checked_address(resolves: Resolver) -> None:
    transport, seen = page()
    fetch_reference("https://example.com/a/b?q=1", transport=transport)
    (request,) = seen
    assert resolves == ["example.com"]  # resolved once; the request does not resolve
    assert request.url.host == PUBLIC
    assert request.url.path == "/a/b" and request.url.query == b"q=1"
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"


def test_an_ipv6_address_is_bracketed(resolves: Resolver) -> None:
    resolves.answer[:] = ["2606:2800:220:1:248:1893:25c8:1946"]
    transport, seen = page()
    fetch_reference("https://example.com/", transport=transport)
    assert seen[0].url.host == "2606:2800:220:1:248:1893:25c8:1946"


def test_html_becomes_plain_text(resolves: Resolver) -> None:
    text = fetch_reference("https://example.com/", transport=page()[0])
    assert text == "Hi\nFirst\nSecond & more"


def test_plain_text_and_markdown_are_kept_as_they_are(resolves: Resolver) -> None:
    for content_type in ("text/plain", "text/markdown; charset=utf-8"):
        transport, _ = page("# Title\n\nbody", content_type)
        assert fetch_reference("https://example.com/", transport=transport) == (
            "# Title\n\nbody"
        )


@pytest.mark.parametrize(
    "content_type", ["application/json", "application/pdf", "image/png", ""]
)
def test_other_content_types_are_refused(content_type: str, resolves: Resolver) -> None:
    with pytest.raises(ReferenceRefused, match="not text"):
        fetch_reference("https://example.com/", transport=page("{}", content_type)[0])


@pytest.mark.parametrize("status", [301, 302, 307, 404, 500])
def test_redirects_and_errors_are_refused_not_followed(
    status: int, resolves: Resolver
) -> None:
    transport, seen = page(
        "", "text/html", status, {"location": "https://127.0.0.1/secret"}
    )
    with pytest.raises(ReferenceRefused):
        fetch_reference("https://example.com/", transport=transport)
    assert len(seen) == 1


def test_the_body_and_the_text_are_capped(resolves: Resolver) -> None:
    transport, _ = page("x" * (fetch.MAX_BODY_BYTES * 3), "text/plain")
    text = fetch_reference("https://example.com/", transport=transport)
    assert len(text) == fetch.MAX_TEXT_CHARS


def test_a_page_without_text_is_refused(resolves: Resolver) -> None:
    transport, _ = page("<html><script>x()</script></html>")
    with pytest.raises(ReferenceRefused, match="no text"):
        fetch_reference("https://example.com/", transport=transport)


def test_a_failed_connection_is_refused(resolves: Resolver) -> None:
    def broken(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("no route")

    with pytest.raises(ReferenceRefused):
        fetch_reference("https://example.com/", transport=httpx2.MockTransport(broken))
