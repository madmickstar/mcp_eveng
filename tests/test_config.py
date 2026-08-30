from __future__ import annotations

import pytest

from mcp_eveng.config import EvengSettings, MCPTransportSettings


def test_default_base_url() -> None:
    settings = EvengSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.base_url == "https://127.0.0.1:443/api"


def test_base_url_reflects_https_and_port() -> None:
    settings = EvengSettings(
        host="eve.example.com",
        port=443,
        protocol="https",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.base_url == "https://eve.example.com:443/api"


def test_settings_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("EVENG_HOST", "10.0.0.5")
    monkeypatch.setenv("EVENG_USERNAME", "operator")
    monkeypatch.setenv("EVENG_PASSWORD", "s3cret")

    settings = EvengSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.host == "10.0.0.5"
    assert settings.username == "operator"
    assert settings.password.get_secret_value() == "s3cret"


def test_verify_ssl_defaults_false() -> None:
    settings = EvengSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.verify_ssl is False


def test_host_rejects_url_with_scheme() -> None:
    # Regression: EVENG_HOST="https://172.16.130.14" produced a cryptic
    # "getaddrinfo failed" deep inside an HTTP call instead of a clear error,
    # because the scheme silently became part of the request hostname.
    with pytest.raises(ValueError, match="EVENG_HOST must be a bare hostname or IP"):
        EvengSettings(host="https://172.16.130.14", _env_file=None)  # type: ignore[call-arg]


def test_host_rejects_url_with_scheme_via_real_env_var(monkeypatch) -> None:
    monkeypatch.setenv("EVENG_HOST", "https://172.16.130.14")
    with pytest.raises(ValueError, match="EVENG_HOST must be a bare hostname or IP"):
        EvengSettings(_env_file=None)  # type: ignore[call-arg]


def test_host_error_message_suggests_the_fix() -> None:
    with pytest.raises(ValueError, match=r"EVENG_HOST='172\.16\.130\.14'.*EVENG_PROTOCOL='https'"):
        EvengSettings(host="https://172.16.130.14/", _env_file=None)  # type: ignore[call-arg]


def test_bare_host_without_scheme_is_unaffected() -> None:
    settings = EvengSettings(host="172.16.130.14", _env_file=None)  # type: ignore[call-arg]
    assert settings.host == "172.16.130.14"


# -- MCPTransportSettings ------------------------------------------------


def test_mcp_transport_defaults() -> None:
    settings = MCPTransportSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.http_path == "/mcp"
    assert settings.sse_path == "/sse"
    assert settings.log_level == "INFO"
    assert settings.allowed_hosts == ["localhost:*"]
    assert settings.stateful is True


def test_mcp_http_path_env_var_renamed(monkeypatch) -> None:
    monkeypatch.setenv("MCP_HTTP_PATH", "/custom-mcp")
    settings = MCPTransportSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.http_path == "/custom-mcp"


def test_mcp_host_port_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("MCP_HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_PORT", "9001")

    settings = MCPTransportSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.host == "0.0.0.0"
    assert settings.port == 9001


def test_log_level_normalizes_case() -> None:
    settings = MCPTransportSettings(log_level="debug", _env_file=None)  # type: ignore[call-arg]
    assert settings.log_level == "DEBUG"


def test_log_level_rejects_invalid_value() -> None:
    with pytest.raises(ValueError, match="MCP_LOG_LEVEL"):
        MCPTransportSettings(log_level="VERBOSE", _env_file=None)  # type: ignore[call-arg]


def test_log_level_validator_uses_module_constant_not_private_class_attribute() -> None:
    # Regression test: pydantic v2 converts ANY leading-underscore class
    # attribute inside a BaseModel/BaseSettings subclass into a
    # ModelPrivateAttr descriptor, even without a type annotation -- so a
    # validator referencing `cls._VALID_LOG_LEVELS` (defined as a plain class
    # attribute) raised `TypeError: argument of type 'ModelPrivateAttr' is
    # not iterable` on every single construction, valid or not. The fix
    # moved the constant to module scope. This just re-confirms plain
    # construction with an untouched default succeeds without that TypeError.
    settings = MCPTransportSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.log_level == "INFO"


def test_allowed_hosts_splits_comma_separated_string() -> None:
    settings = MCPTransportSettings(
        allowed_hosts="192.168.1.100:8000,192.168.1.150:*",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.allowed_hosts == ["192.168.1.100:8000", "192.168.1.150:*"]


def test_allowed_hosts_strips_whitespace_around_entries() -> None:
    settings = MCPTransportSettings(
        allowed_hosts=" 192.168.1.100:8000 , 192.168.1.150:* ",
        _env_file=None,  # type: ignore[call-arg]
    )
    assert settings.allowed_hosts == ["192.168.1.100:8000", "192.168.1.150:*"]


def test_allowed_hosts_empty_string_is_empty_list() -> None:
    settings = MCPTransportSettings(allowed_hosts="", _env_file=None)  # type: ignore[call-arg]
    assert settings.allowed_hosts == []


def test_allowed_hosts_from_real_environment_variable(monkeypatch) -> None:
    # Regression test: pydantic-settings tries to JSON-decode env values for
    # list[str] fields *before* any validator runs, so a plain env var like
    # "192.168.1.100:8000,192.168.1.150:*" used to blow up with a
    # json.decoder.JSONDecodeError ("192.168" parses as a float, then choking
    # on the next "."). This must go through the real EnvSettingsSource --
    # constructing with a kwarg directly (as the tests above do) does NOT
    # exercise that code path and would not have caught this bug.
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "192.168.1.100:8000,192.168.1.150:*")

    settings = MCPTransportSettings(_env_file=None)  # type: ignore[call-arg]

    assert settings.allowed_hosts == ["192.168.1.100:8000", "192.168.1.150:*"]


def test_allowed_hosts_from_dotenv_file(tmp_path) -> None:
    # Same regression, but through the DotEnvSettingsSource path specifically
    # (i.e. a real .env file), which is what actually failed in production.
    env_file = tmp_path / ".env"
    env_file.write_text("MCP_ALLOWED_HOSTS=192.168.1.100:8000,192.168.1.150:*\n")

    settings = MCPTransportSettings(_env_file=str(env_file))  # type: ignore[call-arg]

    assert settings.allowed_hosts == ["192.168.1.100:8000", "192.168.1.150:*"]


def test_env_file_values_matching_env_example_quoting(tmp_path) -> None:
    # .env.example wraps every value in double quotes for consistency; make
    # sure that quoting style round-trips correctly for every field type
    # (str, int, float, bool, and the NoDecode list[str]).
    env_file = tmp_path / ".env"
    env_file.write_text(
        'MCP_HOST="0.0.0.0"\n'
        'MCP_PORT="8000"\n'
        'MCP_HTTP_PATH="/mcp"\n'
        'MCP_LOG_LEVEL="DEBUG"\n'
        'MCP_ALLOWED_HOSTS="192.168.1.100:8000,192.168.1.150:*"\n'
        'MCP_STATEFUL="false"\n'
    )

    settings = MCPTransportSettings(_env_file=str(env_file))  # type: ignore[call-arg]

    assert settings.host == "0.0.0.0"
    assert settings.port == 8000
    assert settings.http_path == "/mcp"
    assert settings.log_level == "DEBUG"
    assert settings.allowed_hosts == ["192.168.1.100:8000", "192.168.1.150:*"]
    assert settings.stateful is False


def test_eveng_env_file_values_matching_env_example_quoting(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        'EVENG_HOST="10.0.0.5"\n'
        'EVENG_PORT="443"\n'
        'EVENG_PROTOCOL="https"\n'
        'EVENG_VERIFY_SSL="false"\n'
        'EVENG_TIMEOUT_SECONDS="15"\n'
    )

    settings = EvengSettings(_env_file=str(env_file))  # type: ignore[call-arg]

    assert settings.host == "10.0.0.5"
    assert settings.port == 443
    assert settings.protocol == "https"
    assert settings.verify_ssl is False
    assert settings.timeout_seconds == 15.0


def test_stateful_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("MCP_STATEFUL", "false")
    settings = MCPTransportSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.stateful is False
