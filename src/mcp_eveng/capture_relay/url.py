"""Builds the `capture://` URL `get_capture` hands back for the PRO
relay path.

## Mode detection: by path pattern, not a query parameter

Earlier versions of this module put an explicit `mode=pro` field in the
query string, with `.bat`-side detection based on whether that field
was present. Dropped after live testing: EVE-NG's own Community links
never carry a `mode` concept at all (that field was purely an invention
of this project's own, not something EVE-NG itself has any notion of).

Community's own GUI-generated links use device names shaped like
`vunl<N>_<node>_<if>` or `pnet<N>` (confirmed live) as the path segment.
This project's own container names (`Capture-<pid>`, from `docker ps`)
never match either shape. So the `.bat` companion determines which flow
to run purely from the first path segment: `vunl*`/`pnet*` -> Community's
existing, unmodified flow; anything else -> this project's relay flow.

## No query string at all -- plain `/`-separated path segments instead

Two real, confirmed-live bugs in a row came from special characters in
a query string colliding with `cmd.exe`'s own command-line parsing:
first `&` (a command separator in `cmd.exe`, which is *always* the
interpreter for a `.bat` file however it's invoked -- Community's own
links never hit this since they never had a query string at all), then
apparently `=`/`?` truncating the argument before the `.bat` even saw
the rest of it (exact mechanism unconfirmed -- somewhere between the
browser's own handling of a non-standard scheme and Windows' URL
protocol dispatch, outside what this project can directly instrument
or fix). Rather than keep finding one more special character to
work around, this format now avoids the whole class of problem: every
field is passed as a plain path segment, separated by `/` -- which
none of them can ever contain (container names are docker-safe,
`token` is base64url -- no `/` in that alphabet, `eveng_host` is an
IP/hostname, `relay_port` is numeric), so there is no separator
ambiguity left to get wrong, and no `?`/`=`/`&`/`;` anywhere in the URL
at all for any layer to mishandle.

    capture://<relay-advertise-host>/<container>/<token>/<relay-port>/<eveng-host>

The `.bat` tries curl against the relay first (using `relay-port`/
`token`), falling back to plink straight into `eveng-host` if curl or
the relay is unreachable. No password ever appears in the URL -- the
plink fallback still relies on the user's own already-configured SSH
access, same as it does today; this project only supplies enough for
the curl/relay path to work without one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlparse

# Matches EVE-NG Community's own device-name conventions, confirmed
# live -- vunl<N>_<node>_<if> and pnet<N>. Anything else in the first
# path-segment position is treated as this project's own container name.
_COMMUNITY_PATH_PATTERN = re.compile(r"^(vunl|pnet)", re.IGNORECASE)


def is_community_style_path(path: str) -> bool:
    """Whether `path` (a single path segment, no slashes) matches
    Community's own device-name shape rather than this project's
    `Capture-<pid>`-style container names. Used by tests to verify the
    pattern; the `.bat` does its own equivalent match in batch syntax."""
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
    """Build the `capture://` URL for the relay path -- plain
    `/`-separated segments, no query string at all (see module
    docstring for why)."""
    segments = [
        quote(container, safe=""),
        quote(token, safe=""),
        str(relay_port),
        quote(eveng_host, safe=""),
    ]
    return f"capture://{relay_host}/" + "/".join(segments)


def parse_pro_capture_url(url: str) -> ProCaptureUrl:
    """Parse a URL built by `build_pro_capture_url` back into its
    fields. Test-only -- the `.bat` does its own parsing in batch
    syntax, not by calling this."""
    parsed = urlparse(url)
    if parsed.scheme != "capture":
        raise ValueError(f"not a capture:// URL: {url!r}")

    segments = [unquote(p) for p in parsed.path.lstrip("/").split("/")]
    if len(segments) != 4:
        raise ValueError(
            f"expected 4 path segments (container/token/relay_port/eveng_host), got {len(segments)}: {url!r}"
        )

    container, token, relay_port_str, eveng_host = segments
    if is_community_style_path(container):
        raise ValueError(f"path looks like a Community-style link, not ours: {url!r}")
    if not relay_port_str.isdigit():
        raise ValueError(f"relay_port segment isn't numeric: {url!r}")

    return ProCaptureUrl(
        container=container,
        token=token,
        relay_host=parsed.netloc,
        relay_port=int(relay_port_str),
        eveng_host=eveng_host,
    )
