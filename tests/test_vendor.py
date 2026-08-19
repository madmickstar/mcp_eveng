from __future__ import annotations

from mcp_eveng.vendor import extract_vendor, has_image, strip_hidden_marker


def test_has_image_true_without_hided_suffix() -> None:
    assert has_image("Cisco CSR 1000V (XE 16.x)") is True


def test_has_image_false_with_hided_suffix() -> None:
    assert has_image("Arista cEOS.hided") is False


def test_strip_hidden_marker_removes_suffix() -> None:
    assert strip_hidden_marker("Arista cEOS.hided") == "Arista cEOS"


def test_strip_hidden_marker_leaves_others_untouched() -> None:
    assert strip_hidden_marker("Cisco CSR 1000V (XE 16.x)") == "Cisco CSR 1000V (XE 16.x)"


# -- direct alias-map matches, case-insensitive --------------------------------


def test_extract_vendor_simple_alias() -> None:
    assert extract_vendor("Cisco CSR 1000V (XE 16.x)") == "Cisco"
    assert extract_vendor("Juniper vEVO Router") == "Juniper"
    assert extract_vendor("Arista cEOS.hided") == "Arista"


def test_extract_vendor_case_insensitive() -> None:
    assert extract_vendor("cisco csr 1000v") == "Cisco"
    assert extract_vendor("JUNIPER vEVO Router") == "Juniper"


def test_extract_vendor_collapses_known_typo_alias() -> None:
    # EVE-NG's own catalog spells this "Barraccuda" (typo) -- must still
    # collapse to the canonical "Barracuda".
    assert extract_vendor("Barraccuda NGIPS.hided") == "Barracuda"


def test_extract_vendor_collapses_full_legal_name_alias() -> None:
    assert extract_vendor("Palo Alto Networks NGFW") == "Palo Alto"
    assert extract_vendor("Palo Alto Panorama") == "Palo Alto"
    assert extract_vendor("Hewlett Packard Enterprise Switch") == "HPE"
    assert extract_vendor("Dell EMC Something") == "Dell"
    assert extract_vendor("Amazon Web Services Gateway") == "AWS"


def test_extract_vendor_longest_alias_wins() -> None:
    # "Palo Alto Networks" and "Palo Alto" both match as a prefix of this
    # description; the longer, more specific alias must be tried first
    # (though here both happen to map to the same canonical name).
    assert extract_vendor("Palo Alto Networks Firewall") == "Palo Alto"


def test_extract_vendor_explicit_self_mappings() -> None:
    assert extract_vendor("Linux") == "Linux"
    assert extract_vendor("Windows") == "Microsoft"
    assert extract_vendor("Windows Server.hided") == "Microsoft"
    assert extract_vendor("Docker.io") == "Docker"
    assert extract_vendor("OPNsense.hided") == "OPNsense"
    assert extract_vendor("pfSense Firewall.hided") == "pfSense"
    assert extract_vendor("Zabbix monitoring.hided") == "Zabbix"


def test_extract_vendor_requested_non_vendor_alias() -> None:
    assert extract_vendor("Virtual PC (VPCS)") == "VPCS"


# -- fallback for anything not in the alias map --------------------------------


def test_extract_vendor_falls_back_to_first_word_when_unmapped() -> None:
    # "HP" isn't in the alias map (only "HPE"/"Hewlett Packard..." are), so
    # this must fall back to the first word rather than mismatching HPE.
    assert extract_vendor("HP VSR1000.hided") == "HP"
    assert extract_vendor("Apstra AOS Server.hided") == "Apstra"
    assert extract_vendor("RSA Authentication Manager.hided") == "RSA"


def test_extract_vendor_empty_string_is_unknown() -> None:
    assert extract_vendor("") == "Unknown"
    assert extract_vendor("   ") == "Unknown"


def test_extract_vendor_handles_malformed_icon_filename_description() -> None:
    # The live catalog's "vsrx" template has a malformed description (an
    # icon filename, not "<Vendor> <Product>" like everything else) --
    # str.startswith() doesn't need a word boundary, so the "Juniper"
    # alias still matches correctly despite the immediately-following "-".
    assert extract_vendor("Juniper-2D-VSRX-S.svg") == "Juniper"


# -- spot-check against the live template catalog -------------------------------


def test_extract_vendor_matches_live_catalog_samples() -> None:
    live_samples = {
        "Cisco Catalyst 8000v": "Cisco",
        "Cisco CSR 1000V (XE 16.x)": "Cisco",
        "Cisco IOL": "Cisco",
        "Cisco vIOS Switch": "Cisco",
        "Cisco XRv 9000": "Cisco",
        "F5 BIG-IP LTM VE": "F5",
        "Juniper 128T": "Juniper",
        "Juniper RR": "Juniper",
        "Juniper vEVO Router": "Juniper",
        "Juniper vEX Switch": "Juniper",
        "Juniper vMX VCP": "Juniper",
        "Juniper vMX VFP": "Juniper",
        "Juniper vQFX PFE": "Juniper",
        "Juniper vQFX RE": "Juniper",
        "Juniper vRouter": "Juniper",
        "MikroTik RouterOS": "MikroTik",
    }
    for description, expected_vendor in live_samples.items():
        assert extract_vendor(description) == expected_vendor
