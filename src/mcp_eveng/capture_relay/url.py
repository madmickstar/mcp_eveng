"""Builds the `capture://` URL `get_capture` hands back for PRO mode.

Community's own GUI already generates `capture://<eveng-host>/<device>`
links today (two path segments, no query string) -- that format is
untouched; this project's `.bat` companion treats the *absence* of a
`mode` query parameter as "this is an unmodified Community link, handle
it exactly as before." A PRO-mode link is always explicit about it:

    capture://<relay-advertise-host>/<container>?mode=pro&token=<token>
        &relay_port=<port>&eveng_host=<eveng-ssh-host>

The `.bat` uses `mode=pro` to branch into the new logic, then tries curl
against the relay first (using `relay_port`/`token`), falling back to
plink straight into `eveng_host` if curl or the relay is unreachable.
No password ever appears in the URL -- the plink fallback still relies
on the user's own already-configured SSH access, same as it does today;
this project only supplies enough for the curl/relay path to work
without one.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse


@dataclass(frozen=True)
class ProCaptureUrl:
    """A parsed PRO-mode capture:// URL -- used by this project's own
    tests to verify round-tripping; the real consumer is the `.bat`
    companion, which parses the same fields using batch syntax."""

    container: str
    token: str
    relay_host: str
    relay_port: int
    eveng_host: str


def build_pro_capture_url(
    *,
    container: str,
    token: str,
    relay_host: str,
    relay_port: int,
    eveng_host: str,
) -> str:
    """Build the `capture://` URL for the PRO/relay path."""
    query = urlencode(
        {
            "mode": "pro",
            "token": token,
            "relay_port": str(relay_port),
            "eveng_host": eveng_host,
        }
    )
    return f"capture://{relay_host}/{quote(container, safe='')}?{query}"


def parse_pro_capture_url(url: str) -> ProCaptureUrl:
    """Parse a URL built by `build_pro_capture_url` back into its
    fields. Test-only -- the `.bat` does its own parsing in batch
    syntax, not by calling this."""
    parsed = urlparse(url)
    if parsed.scheme != "capture":
        raise ValueError(f"not a capture:// URL: {url!r}")

    container = unquote(parsed.path.lstrip("/"))
    query = parse_qs(parsed.query)

    def _one(name: str) -> str:
        values = query.get(name)
        if not values:
            raise ValueError(f"missing {name!r} in capture:// URL: {url!r}")
        return values[0]

    if _one("mode") != "pro":
        raise ValueError(f"not a PRO-mode capture:// URL: {url!r}")

    return ProCaptureUrl(
        container=container,
        token=_one("token"),
        relay_host=parsed.netloc,
        relay_port=int(_one("relay_port")),
        eveng_host=_one("eveng_host"),
    )
