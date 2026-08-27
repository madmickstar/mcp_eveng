"""Vendor extraction from EVE-NG template descriptions.

EVE-NG's node-template API has no explicit vendor field -- only a
human-readable description string (e.g. "Cisco CSR 1000V (XE 16.x)",
"Juniper vEVO Router", "Barraccuda NGIPS.hided"). `extract_vendor` maps
that description to a vendor name via `_VENDOR_ALIASES`: a curated,
case-insensitive prefix match that also collapses known aliases/typos in
EVE-NG's own descriptions onto one canonical vendor name (e.g. both
"Barraccuda" and "Barracuda Networks" -> "Barracuda"). Anything not in the
map falls back to the description's first word. This is inference from
EVE-NG's own text, not a value EVE-NG itself returns -- treat it as a
helpful label, not authoritative data.

`has_image`/`strip_hidden_marker` are built around a separate, more
reliable signal: EVE-NG appends a suffix to a template's description when
no image is installed for it. **This suffix differs by edition** --
confirmed live against both: PRO uses ".hided"; Community uses ".missing"
(confirmed against a real Community server's full 168-template catalog --
every template actually installed lacked the suffix, everything else had
it). Both are recognized here so the same code works unmodified against
either edition.
"""

from __future__ import annotations

_HIDDEN_SUFFIXES = (".hided", ".missing")

# Key: a string to match at the start of a template description
# (case-insensitive). Value: the canonical vendor name to report for it.
# Multiple keys commonly collapse onto the same canonical name, either
# because EVE-NG's own descriptions are inconsistent (e.g. "Barraccuda" is
# a typo in EVE-NG's actual catalog) or to normalize a full legal name down
# to the short form people actually use (e.g. "Palo Alto Networks").
_VENDOR_ALIASES: dict[str, str] = {
    # --- Security ---
    "Palo Alto Networks": "Palo Alto",
    "Palo Alto": "Palo Alto",
    "Palo Panorama": "Palo Alto",  # EVE-NG doc-page shorthand
    "Check Point": "Check Point",
    "CheckPoint": "Check Point",
    "Trend Micro": "Trend Micro",
    "TrendMicro": "Trend Micro",
    "Barracuda Networks": "Barracuda",
    "Barracuda": "Barracuda",
    "SonicWall": "SonicWall",
    "WatchGuard": "WatchGuard",
    "Sophos": "Sophos",
    "Fortinet": "Fortinet",
    "F5": "F5",
    "AlienVault": "AlienVault",
    "Cyberoam": "Cyberoam",
    "Clavister": "Clavister",
    "Forcepoint": "Forcepoint",
    "Forescout": "Forescout",
    "Hillstone": "Hillstone",
    "Stormshield": "Stormshield",
    "Kerio": "Kerio",
    "Pulse Secure": "Pulse Secure",
    "Zscaler": "Zscaler",

    # --- Networking / infrastructure ---
    "Hewlett Packard Enterprise": "HPE",
    "Hewlett Packard": "HPE",
    "HPE": "HPE",
    "Extreme Networks": "Extreme",
    "Extreme": "Extreme",
    "Big Switch Networks": "Big Switch",
    "A10 Networks": "A10",
    "A10": "A10",
    "Versa Networks": "Versa",
    "Versa": "Versa",
    "Silver Peak": "Silver Peak",
    "Ruckus": "Ruckus",
    "Cisco": "Cisco",
    "Juniper": "Juniper",
    "Arista": "Arista",
    "Aruba": "Aruba",
    "MikroTik": "MikroTik",
    "Riverbed": "Riverbed",
    "Viptela": "Viptela",
    "Huawei": "Huawei",
    "Nokia": "Nokia",
    "Ericsson": "Ericsson",
    "ZTE": "ZTE",
    "D-Link": "D-Link",
    "TP-Link": "TP-Link",
    "Netgear": "Netgear",
    "Zyxel": "Zyxel",
    "Ubiquiti": "Ubiquiti",
    "Cumulus": "Cumulus",
    "Dell EMC": "Dell",
    "Dell": "Dell",
    "Kemp": "Kemp",
    "Radware": "Radware",

    # --- Cloud / virtualization ---
    "Amazon Web Services": "AWS",
    "Amazon": "AWS",
    "AWS": "AWS",
    "Google Cloud": "Google",
    "VM Ware": "VMware",
    "VMware": "VMware",
    "Nutanix": "Nutanix",
    "Citrix": "Citrix",
    "MS Windows": "Microsoft",
    "Microsoft": "Microsoft",
    "Oracle": "Oracle",
    "Red Hat": "Red Hat",
    "SUSE": "SUSE",
    "Canonical": "Canonical",

    # --- Storage / compute ---
    "NetApp": "NetApp",
    "Pure Storage": "Pure Storage",
    "Broadcom": "Broadcom",
    "NVIDIA": "NVIDIA",

    # --- SD-WAN / monitoring / misc tools ---
    "Aviatrix": "Aviatrix",
    "Infoblox": "Infoblox",
    "VyOS": "VyOS",

    # --- Explicit self-mappings for known single-word template
    # descriptions. These are no longer caught by a generic "first
    # word" fallback (see extract_vendor), so anything we want
    # preserved as a recognized vendor needs its own entry here.
    "Linux": "Linux",
    "Windows": "Microsoft",
    "Docker.io": "Docker",
    "OPNsense": "OPNsense",
    "pfSense": "pfSense",
    "Plixer": "Plixer",
    "Zabbix": "Zabbix",

    # --- Aliases requested explicitly, not really "vendors" ---
    "Virtual PC": "VPCS",
}

# Longest key first, so a more specific multi-word alias (e.g. "Palo Alto
# Networks") is tried before a shorter one it also starts with, and so a
# longer unrelated key never gets shadowed by a shorter accidental prefix.
_SORTED_ALIAS_KEYS: list[str] = sorted(_VENDOR_ALIASES, key=len, reverse=True)


def strip_hidden_marker(description: str) -> str:
    """Remove EVE-NG's trailing no-image marker, if present -- either
    edition's convention (see module docstring)."""
    for suffix in _HIDDEN_SUFFIXES:
        if description.endswith(suffix):
            return description[: -len(suffix)]
    return description


def has_image(description: str) -> bool:
    """Whether a template (as listed by `list_node_templates`) has an image installed."""
    return not description.endswith(_HIDDEN_SUFFIXES)


def extract_vendor(description: str) -> str:
    """Best-effort vendor name from a template description string.

    Strips the no-image marker (either edition's), then checks
    `_VENDOR_ALIASES` for a case-insensitive prefix match (longest alias
    first), falling back to the description's first word if nothing
    matches. Returns "Unknown" for an empty description.
    """
    text = strip_hidden_marker(description).strip()
    if not text:
        return "Unknown"
    lowered = text.lower()
    for alias in _SORTED_ALIAS_KEYS:
        if lowered.startswith(alias.lower()):
            return _VENDOR_ALIASES[alias]
    return text.split()[0]
