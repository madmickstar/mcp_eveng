"""EVE-NG edition detection (PRO vs Community).

EVE-NG's REST API has no explicit "edition" field, but the version string
returned by `get_status` carries a "-PRO" suffix on PRO servers (confirmed
live: "6.5.0-27-PRO"); plain Community builds don't have it (confirmed
live: "6.2.0-4"). This is the only reliable, API-visible signal for which
edition a server is running, so every edition-aware behavior in this
project derives from it.

Several tools genuinely behave differently by edition -- confirmed against
EVE-NG's own official features-compare page
(https://www.eve-ng.net/index.php/features-compare/), live testing, or
both:

- `connect_interface`: PRO allows wiring interfaces on running nodes;
  Community requires every node involved stopped first (confirmed live,
  and via a real Community troubleshooting report: "running nodes cannot
  be directly connected together ... must power down the nodes before
  being able to establish connections").
- `export_node`: the official comparison page lists "Export/Import
  configs or config packs to local PC" as a separate toggleable
  Community/PRO feature row. Confirmed live: fails
  unconditionally on Community -- across VPCS and IOL, running and
  stopped, `config="Saved"` and `"Unconfigured"` -- while the identical
  request shape works normally for `start_node`/`stop_node`/`wipe_node`
  on the same server.
- `share_lab`: the official comparison page lists "Shared Lab" and
  "Shared Project" as separate toggleable feature rows. Confirmed live
  on Community: `get_lab` never returns a `shared` key at all, and
  attempting to actually add a share fails with "Lab has not been
  modified (20030)" -- the request is accepted but silently has no
  effect, unlike PRO where it applies normally.
- `set_link_quality`: per-connection delay/jitter/packet-loss/bandwidth
  is a PRO-only feature with no Community equivalent at all
  (confirmed directly by a user: no GUI option exists there, and unlike
  the other three tools above, there's no open-source Community-side
  code for it either -- it isn't a restricted version of a shared
  feature, it simply doesn't exist outside PRO). See
  `tools/quality.py` for the confirmed request shape.

An unrecognized or missing version string is treated as Community, the
more conservative assumption -- this fails safe by assuming the more
restricted edition rather than risking behavior EVE-NG might reject.
"""

from __future__ import annotations

from typing import Any


def is_pro_edition(status_data: dict[str, Any]) -> bool:
    """Whether an EVE-NG server -- given its `get_status` response `data` -- is PRO, vs Community."""
    version = str(status_data.get("version", ""))
    return version.strip().upper().endswith("-PRO")
