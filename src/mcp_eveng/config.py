"""Runtime configuration for the EVENG MCP server.

All configuration is read from environment variables, which may be supplied
via a `.env` file (see `.env.example` in the repository root). This keeps
secrets and per-deployment settings (EVENG credentials, the host/port used
for SSE and Streamable HTTP transports, ...) out of source code entirely.

Nothing in this module talks to the network; it only *describes* how to
connect.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Transport = Literal["stdio", "sse", "streamable-http"]

# Module-level, not a class attribute: pydantic v2 converts any leading-
# underscore class attribute inside a BaseModel/BaseSettings subclass into a
# ModelPrivateAttr descriptor -- even without a type annotation -- so
# referencing it as cls._VALID_LOG_LEVELS from inside the class body would
# not give back the plain tuple.
_VALID_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

# Maps the literal character to the escape sequence a Windows path would
# have contained before python-dotenv's own double-quote escape
# processing corrupted it -- see _check_windows_path_corruption below.
_CONTROL_CHAR_ESCAPES = {
    "\t": "\\t",
    "\n": "\\n",
    "\r": "\\r",
    "\v": "\\v",
    "\f": "\\f",
    "\b": "\\b",
    "\0": "\\0",
}


def _check_windows_path_corruption(value: str, env_var_name: str) -> None:
    """Confirmed directly, not assumed: a Windows path like
    `"C:\\to\\..."` or `"C:\\new\\..."` inside a DOUBLE-quoted `.env`
    value gets its `\\t`/`\\n`/etc. silently turned into an actual
    tab/newline/etc. character by `python-dotenv`'s own escape
    processing -- reproduced with a synthetic `.env` file containing
    exactly this pattern and confirmed the parsed-back value contains a
    literal TAB where `\\t` in `\\to\\` was, and a literal NEWLINE where
    `\\n` in `\\new...` was. Windows paths can't contain control
    characters, so this then fails deep inside OpenSSL with an
    unhelpful `OSError: [Errno 22] Invalid argument` -- confirmed live,
    this is exactly what happened for a real path containing `\\to\\`
    and `\\certs\\new...`. Catching it here gives a message that
    actually explains what's wrong and how to fix it, instead of that
    generic downstream error two layers removed from the real cause.
    """
    found = [esc for ch, esc in _CONTROL_CHAR_ESCAPES.items() if ch in value]
    if found:
        raise ValueError(
            f"{env_var_name} contains a literal {', '.join(found)} character. This "
            'usually means a Windows backslash path (e.g. "C:\\to\\..." or '
            '"C:\\new\\...") got silently corrupted by .env\'s own double-quote '
            "escape processing -- \\t/\\n/etc. become actual control characters, "
            "not literal backslash-letter text. Fix: use forward slashes "
            '("C:/path/to/...") instead of backslashes, or wrap the value in '
            "single quotes instead of double quotes."
        )


class EvengSettings(BaseSettings):
    """Connection settings for the target EVENG server."""

    model_config = SettingsConfigDict(
        env_prefix="EVENG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", description="EVENG server hostname or IP")
    port: int = Field(default=443, description="EVENG server port")
    protocol: Literal["http", "https"] = Field(default="https", description="Scheme used to reach the EVENG API")
    username: str = Field(default="admin", description="EVENG login username")
    password: SecretStr = Field(default=SecretStr("eve"), description="EVENG login password")
    # "1" for native/telnet console (community default), "0" for Pro/HTML5-only.
    html5: str = Field(default="-1", description="EVENG html5 login flag")
    verify_ssl: bool = Field(default=False, description="Verify TLS certificates (Pro/https, often self-signed)")
    timeout_seconds: float = Field(default=30.0, description="HTTP request timeout")

    @field_validator("host", mode="before")
    @classmethod
    def _reject_url_in_host(cls, v: str) -> str:
        """Catch the common mistake of pasting a full URL into EVENG_HOST.

        A value like "https://172.16.130.14" *looks* fine, but goes straight
        into the request URL as the hostname -- DNS resolution then fails
        with a cryptic "getaddrinfo failed" deep inside an HTTP call, with no
        hint that the real problem is upstream in configuration. Fail fast
        here instead, with an actionable message pointing at EVENG_PROTOCOL.
        """
        s = str(v).strip()
        if "://" in s:
            scheme, _, rest = s.partition("://")
            rest = rest.rstrip("/")
            raise ValueError(
                f"EVENG_HOST must be a bare hostname or IP, not a URL. Got {v!r}. "
                f"Set EVENG_HOST={rest!r} and EVENG_PROTOCOL={scheme!r} instead "
                "(protocol and host are separate variables)."
            )
        return s

    @property
    def base_url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}/api"


class MCPTransportSettings(BaseSettings):
    """Settings for how this MCP server exposes itself over the network.

    Which transport to serve (`stdio`, `sse`, or `streamable-http`) is a
    **CLI flag** (`--sse` / `--http`, no flag = stdio), not an environment
    variable -- see `__main__.py`. Everything below only matters when the
    server is started with `--sse` or `--http`; in plain stdio mode there's
    no network listener at all, so none of it needs to be set.
    """

    model_config = SettingsConfigDict(
        env_prefix="MCP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", description="Bind host for --sse/--http")
    port: int = Field(default=8000, description="Bind port for --sse/--http")
    http_path: str = Field(default="/mcp", description="Mount path for the streamable-http app (--http)")
    sse_path: str = Field(default="/sse", description="Mount path for the legacy sse app (--sse)")
    tools_config_path: str = Field(
        default="tools.env",
        description="Path to the per-tool enable/disable config file (see tool_config.py)",
    )
    log_level: str = Field(
        default="INFO",
        description="Python logging level: DEBUG, INFO, WARNING, ERROR, or CRITICAL",
    )
    allowed_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["localhost:*"],
        description=(
            "Comma-separated Host-header allowlist for DNS-rebinding protection, e.g. "
            "'localhost:*,192.168.10.100:*'. Required whenever MCP_HOST is not a "
            "loopback address (127.0.0.1/localhost/::1)."
        ),
    )
    stateful: bool = Field(
        default=True,
        description=(
            "Keep streamable-http session state across requests (default, true). Set to "
            "false so a server restart doesn't leave clients holding a session id the "
            "server no longer recognizes."
        ),
    )
    api_key: SecretStr | None = Field(
        default=None,
        description=(
            "If set, every --sse/--http request must present it via "
            "'Authorization: Bearer <key>', or gets a 401. Unset (default): no "
            "API-key check at all -- only the Host-header allowlist above."
        ),
    )
    tls_cert_path: str | None = Field(
        default=None,
        description=(
            "Path to a TLS certificate file. Serves --sse/--http over HTTPS "
            "instead of plain HTTP when set together with tls_key_path."
        ),
    )
    tls_key_path: str | None = Field(
        default=None,
        description="Path to the TLS certificate's private key file. Required together with tls_cert_path.",
    )
    tls_key_password: SecretStr | None = Field(
        default=None,
        description="Password for tls_key_path, if the private key itself is encrypted.",
    )

    @model_validator(mode="after")
    def _tls_cert_and_key_together(self) -> MCPTransportSettings:
        if bool(self.tls_cert_path) != bool(self.tls_key_path):
            raise ValueError(
                "MCP_TLS_CERT_PATH and MCP_TLS_KEY_PATH must both be set, or neither -- got only one of the two."
            )
        return self

    @field_validator("tls_cert_path", mode="after")
    @classmethod
    def _check_tls_cert_path_corruption(cls, v: str | None) -> str | None:
        if v is not None:
            _check_windows_path_corruption(v, "MCP_TLS_CERT_PATH")
        return v

    @field_validator("tls_key_path", mode="after")
    @classmethod
    def _check_tls_key_path_corruption(cls, v: str | None) -> str | None:
        if v is not None:
            _check_windows_path_corruption(v, "MCP_TLS_KEY_PATH")
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        level = str(v).strip().upper()
        if level not in _VALID_LOG_LEVELS:
            raise ValueError(f"MCP_LOG_LEVEL must be one of {_VALID_LOG_LEVELS}, got {v!r}")
        return level

    @field_validator("allowed_hosts", mode="before")
    @classmethod
    def _split_allowed_hosts(cls, v: str | list[str] | None) -> list[str]:
        if v is None or v == "":
            return []
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v


@lru_cache
def get_eveng_settings() -> EvengSettings:
    """Cached accessor so the whole app shares one settings instance."""
    return EvengSettings()


@lru_cache
def get_mcp_settings() -> MCPTransportSettings:
    return MCPTransportSettings()
