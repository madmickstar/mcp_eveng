"""Parsing for `docker ps` output listing EVE-NG's capture containers.

Deliberately not parsed from `docker ps`'s default human-readable table
(column-aligned, several fields containing spaces -- `CREATED` is e.g.
"About a minute ago", `STATUS` is e.g. "Up 18 seconds" -- fragile to
split on whitespace). Since this project constructs the SSH command
itself rather than parsing whatever a human happened to run, it asks
docker for a machine-parseable format instead:

    docker ps --filter ancestor=eve-wireshark \\
        --format '{{.ID}}\\t{{.Names}}\\t{{.CreatedAt}}\\t{{.Status}}'

Filtered by `ancestor=eve-wireshark` (the image every capture container
runs, confirmed live) rather than by name prefix -- the `Capture-nnnnnnn`
naming convention is PID-like and specific to what's been observed, not
documented as a stable EVE-NG contract, whereas the image name is what
actually identifies "this is a capture container."

Fields are tab-separated (`\\t` can't appear within any of the field
values docker produces here), so parsing is a plain split -- no need to
handle embedded spaces since nothing here relies on there being none.
"""

from __future__ import annotations

from dataclasses import dataclass

DOCKER_PS_FORMAT = "{{.ID}}\t{{.Names}}\t{{.CreatedAt}}\t{{.Status}}"
DOCKER_PS_COMMAND = f"docker ps --filter ancestor=eve-wireshark --format '{DOCKER_PS_FORMAT}'"


@dataclass(frozen=True)
class RunningCapture:
    """One running EVE-NG capture container."""

    container_id: str
    name: str
    created_at: str
    status: str


def parse_docker_ps_output(output: str) -> list[RunningCapture]:
    """Parse tab-separated `docker ps` output (see `DOCKER_PS_FORMAT`)
    into a list of `RunningCapture`, oldest-first (matching docker's own
    default ordering -- newest container first -- reversed, since
    "oldest first" is the more natural order for a numbered list a
    person picks from by position, e.g. "get_capture 1").

    Blank lines are skipped. A line with the wrong number of fields is
    skipped rather than raising -- a partial/garbled line from a flaky
    SSH session shouldn't take down the whole listing.
    """
    captures: list[RunningCapture] = []
    for line in output.splitlines():
        line = line.strip("\r\n")
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 4:
            continue
        container_id, name, created_at, status = fields
        captures.append(
            RunningCapture(
                container_id=container_id.strip(),
                name=name.strip(),
                created_at=created_at.strip(),
                status=status.strip(),
            )
        )
    captures.reverse()
    return captures
