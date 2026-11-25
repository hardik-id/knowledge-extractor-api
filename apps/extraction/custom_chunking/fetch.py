"""Fetch the reference page a person linked, on the server and never in the sandbox.

The link is untrusted, so the fetch is narrow: https on the default port only, no
credentials in the link, and the host must resolve to public addresses only (private,
loopback, link-local, reserved, multicast and unspecified addresses, IPv4 and IPv6, are
refused; so is an IPv4 address wrapped in an IPv6 one). The connection goes to the
address that was checked, not to the name, so a second DNS answer cannot swap it: the
request is made to the IP with the host name as ``Host`` header and TLS server name, and
the certificate is still checked against the host name. No proxy from the environment is
used, redirects are not followed, the whole fetch has ``TIMEOUT_SECONDS``, only text
content types are accepted and the body is read up to ``MAX_BODY_BYTES``. HTML becomes
rough plain text (standard library parser), cut to ``MAX_TEXT_CHARS``.

A refusal raises ``ReferenceRefused`` with a short reason a person can read.
"""

import ipaddress
import socket
import time
from html.parser import HTMLParser
from urllib.parse import urlsplit

import httpx2

TIMEOUT_SECONDS = 10.0
MAX_BODY_BYTES = 500_000
MAX_TEXT_CHARS = 20_000
HTML_TYPES = ("text/html", "application/xhtml+xml")
_SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "head"})
_BLOCKS = frozenset(
    {"p", "div", "br", "li", "ul", "ol", "tr", "table", "section", "article", "pre"}
    | {"h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "hr", "dt", "dd"}
)


class ReferenceRefused(Exception):
    """The link may not be fetched or its page cannot be used; ``str`` is the reason."""


def fetch_reference(url: str, transport: httpx2.BaseTransport | None = None) -> str:
    """The plain text of the page at ``url``. ``transport`` is for tests."""
    host = _check_url(url)
    address = _public_address(host)
    path = urlsplit(url)
    target = path._replace(
        netloc=f"[{address}]" if ":" in address else address, fragment=""
    ).geturl()
    body, content_type = _get(target, host, transport)
    text = body.decode("utf-8", errors="replace")
    if content_type in HTML_TYPES:
        text = _html_to_text(text)
    text = text.replace("\x00", "").strip()
    if not text:
        raise ReferenceRefused("The page has no text.")
    return text[:MAX_TEXT_CHARS]


def _check_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise ReferenceRefused("This is not a valid link.") from None
    if parts.scheme != "https":
        raise ReferenceRefused("Only https links are allowed.")
    if not parts.hostname:
        raise ReferenceRefused("This is not a valid link.")
    if parts.username is not None or parts.password is not None:
        raise ReferenceRefused("A link with a user name or password is not allowed.")
    if port not in (None, 443):
        raise ReferenceRefused("Only the standard https port is allowed.")
    return parts.hostname


def _resolve(host: str) -> list[str]:
    """Every address of ``host`` (a seam for tests)."""
    try:
        found = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        raise ReferenceRefused("The address could not be found.") from None
    return [str(info[4][0]) for info in found]


def _public_address(host: str) -> str:
    """The address to connect to; refuses when any address of the host is not public."""
    addresses = _resolve(host)
    if not addresses:
        raise ReferenceRefused("The address could not be found.")
    parsed = []
    for raw in addresses:
        try:
            parsed.append(ipaddress.ip_address(raw.split("%")[0]))
        except ValueError:
            raise ReferenceRefused("The address could not be found.") from None
    if not all(_is_public(address) for address in parsed):
        raise ReferenceRefused("This address is not a public one.")
    return str(parsed[0])


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(address, ipaddress.IPv6Address):
        embedded = address.ipv4_mapped or _nat64(address)
        if embedded is not None and not _is_public(embedded):
            return False
        if address.sixtofour is not None and not _is_public(address.sixtofour):
            return False
    return bool(
        address.is_global
        and not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
            or address.is_multicast
            or address.is_unspecified
        )
    )


def _nat64(address: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if address in ipaddress.ip_network("64:ff9b::/96"):
        return ipaddress.IPv4Address(int(address) & 0xFFFFFFFF)
    return None


def _get(
    target: str, host: str, transport: httpx2.BaseTransport | None
) -> tuple[bytes, str]:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    try:
        with httpx2.Client(
            transport=transport,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            with client.stream(
                "GET",
                target,
                headers={
                    "Host": host,
                    "Accept": "text/html, text/plain, text/markdown;q=0.9",
                    "Accept-Encoding": "identity",
                    "User-Agent": "knowledge-extractor",
                },
                extensions={"sni_hostname": host},
            ) as response:
                if response.is_redirect:
                    raise ReferenceRefused("The link redirects, which is not followed.")
                if response.status_code != 200:
                    raise ReferenceRefused(
                        f"The page answered with status {response.status_code}."
                    )
                content_type = (
                    response.headers.get("content-type", "")
                    .split(";")[0]
                    .strip()
                    .lower()
                )
                if not (content_type.startswith("text/") or content_type in HTML_TYPES):
                    raise ReferenceRefused("The page is not text.")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) >= MAX_BODY_BYTES:
                        break
                    if time.monotonic() > deadline:
                        raise ReferenceRefused("The page took too long to load.")
    except ReferenceRefused:
        raise
    except httpx2.TimeoutException:
        raise ReferenceRefused("The page took too long to load.") from None
    except httpx2.HTTPError:
        raise ReferenceRefused("The page could not be loaded.") from None
    return bytes(body[:MAX_BODY_BYTES]), content_type


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _SKIPPED:
            self._skip += 1
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    parser.close()
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    return "\n".join(line for line in lines if line)
