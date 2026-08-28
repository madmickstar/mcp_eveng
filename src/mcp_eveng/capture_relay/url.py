"""Builds the `capture://` URL `get_capture` hands back for the PRO
relay path.

## Mode detection: by path pattern, not a query parameter

Earlier versions of this module put an explicit `mode=pro` field in the
query string, with `.bat`-side detection based on whether that field
was present. Dropped after live testing: EVE-NG's own Community links
never carry a `mode` concept at all (that field was purely an invention
of this project's own, not something EVE-NG itself has any notion of),
and per direct feedback, detecting by the URL's own natural shape is
more robust than relying on a field this project made up and has to
parse correctly under `cmd.exe`'s own quoting rules.

Community's own GUI-generated links use device names shaped like
`vunl<N>_<node>_<if>` or `pnet<N>` (confirmed live) as the path segment,
with no query string at all. This project's own container names
(`Capture-<pid>`, from `docker ps`) never match either shape. So the
`.bat` companion determines which flow to run purely from the path:
`vunl*`/`pnet*` -> Community's existing, unmodified flow; anything else
-> this project's relay flow.

## Query separator: `;`, not `&`

Confirmed live: `&` broke the `.bat`'s parsing in practice. `cmd.exe`
(which is *always* the interpreter for a `.bat` file, however it's
invoked) treats an unescaped `&` in a command line as a command
separator -- Community's own links were never affected by this, since
they never contain a query string at all, but this project's own
multi-field query string was the first `capture://` link ever built
with `&` in it, and it broke exactly where you'd expect (the parser
losing everything from the first `&` onward). `;` isn't one of
`cmd.exe`'s special characters (`& | < > ^ ( ) % !`), so the query
string here uses it as the field separator instead of the HTTP-typical
`&`. `urllib.parse.urlencode` has no option to change its separator, so
the query string is built by hand here instead; parsing uses
`parse_qs`'s own `separator=` parameter (a real, standard library
option, not project-specific) to match.

    capture://<relay-advertise-host>/<container>?token=<token>
        ;relay_port=<port>;eveng_host=<eveng-ssh-host>

The `.bat` tries curl against the relay first (using `relay_port`/
`token`), falling back to plink straight into `eveng_host` if curl or
the relay is unreachable. No password ever appears in the URL -- the
plink fallback still relies on the user's own already-configured SSH
access, same as it does today; this project only supplies enough for
the curl/relay path to work without one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, quote, unquote, urlparse

QUERY_SEPARATOR = ";"

# Matches EVE-NG Community's own device-name conventions, confirmed
# live -- vunl<N>_<node>_<if> and pnet<N>. Anything else in the path
# position is treated as this project's own container name.
_COMMUNITY_PATH_PATTERN = re.compile(r"^(vunl|pnet)", re.IGNORECASE)


def is_community_style_path(path: str) -> bool:
    """Whether `path` (the capture:// URL's path segment, no leading
    slash) matches Community's own device-name shape rather than this
    project's `Capture-<pid>`-style container names. Used by tests to
    verify the pattern; the `.bat` does its own equivalent match in
    batch syntax."""
    return bool(_COMMUNITY_PATH_PATTERN.match(path))


@dataclass(frozen=True)
class ProCaptureUrl:
    """A parsed relay-path capture:// URL -- used by this project's own
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
    """Build the `capture://` URL for the relay path."""
    fields = {
        "token": token,
        "relay_port": str(relay_port),
        "eveng_host": eveng_host,
    }
    query = QUERY_SEPARATOR.join(f"{k}={quote(v, safe='')}" for k, v in fields.items())
    return f"capture://{relay_host}/{quote(container, safe='')}?{query}"


def parse_pro_capture_url(url: str) -> ProCaptureUrl:
    """Parse a URL built by `build_pro_capture_url` back into its
    fields. Test-only -- the `.bat` does its own parsing in batch
    syntax, not by calling this."""
    parsed = urlparse(url)
    if parsed.scheme != "capture":
        raise ValueError(f"not a capture:// URL: {url!r}")

    container = unquote(parsed.path.lstrip("/"))
    if is_community_style_path(container):
        raise ValueError(f"path looks like a Community-style link, not ours: {url!r}")

    query = parse_qs(parsed.query, separator=QUERY_SEPARATOR)

    def _one(name: str) -> str:
        values = query.get(name)
        if not values:
            raise ValueError(f"missing {name!r} in capture:// URL: {url!r}")
        return values[0]

    return ProCaptureUrl(
        container=container,
        token=_one("token"),
        relay_host=parsed.netloc,
        relay_port=int(_one("relay_port")),
        eveng_host=_one("eveng_host"),
    )
