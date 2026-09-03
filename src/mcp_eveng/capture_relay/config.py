"""Settings for the capture-relay feature.

Split into two classes because the two processes that use this feature
need different subsets:

- `CaptureSSHSettings` (env prefix `CAPTURE_`): read by BOTH the main
  `mcp-eveng` process (`tools/capture.py`'s `list_captures`/
  `get_capture`, which SSH in to run `docker ps`) and the standalone
  relay (which SSHes in to run `docker exec ... dumpcap`). Also carries
  the HMAC token secret both sides need to agree on -- see `tokens.py`.
- `RelayListenSettings` (env prefix `CAPTURE_RELAY_`): read ONLY by the
  relay's own entrypoint (which host/port to listen on for incoming
  stream requests) -- the main process has no listener of its own to
  configure.

This is a deliberately different SSH identity from `EvengSettings`
(`EVENG_USERNAME`/`EVENG_PASSWORD` in the main `config.py`) -- that's an
EVE-NG *application* login used against its REST API; this is an
OS-level SSH account on the EVE-NG host itself, scoped (via sudoers) to
exactly the `docker ps`/`docker exec ... dumpcap` commands this feature
needs and nothing else. Using the same credential for both would give
the API user OS-level access it has no business having.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Module-level, not a class attribute -- see the identical comment in the
# main config.py for why (pydantic v2 turns a leading-underscore class
# attribute into a ModelPrivateAttr, even without a type annotation).
# Duplicated rather than imported from mcp_eveng.config: this package is
# deliberately self-contained (its own settings, own deployment), and the
# tuple itself is small and unlikely to diverge.
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


class CaptureSSHSettings(BaseSettings):
    """SSH connection settings for reaching the EVE-NG host's docker
    captures -- shared by the main process and the relay."""

    model_config = SettingsConfigDict(
        env_prefix="CAPTURE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ssh_host: str = Field(..., description="EVE-NG host to SSH into for docker ps/exec.")
    ssh_port: int = Field(default=22, description="SSH port on the EVE-NG host.")
    ssh_username: str = Field(..., description="OS account scoped (via sudoers) to docker ps/exec dumpcap only.")
    ssh_key_path: str = Field(
        ..., description="Path to this account's private key. Key-based auth only -- no password option."
    )
    ssh_known_hosts: str | None = Field(
        default=None,
        description=(
            "Path to a known_hosts file to verify the EVE-NG host's SSH key against. "
            "Unset disables host-key checking entirely -- fine for a lab/internal network, "
            "but leaves this connection open to a MITM on production infrastructure. "
            "Set this for anything beyond a lab."
        ),
    )
    token_secret: SecretStr = Field(
        ..., description="Shared HMAC secret for signing/verifying capture tokens -- see tokens.py."
    )
    token_ttl_seconds: int = Field(
        default=300,
        description=(
            "How long a get_capture token stays valid. It's the only "
            "revocation mechanism there is, so keep it reasonably short -- "
            "but confirmed live, 60s was too tight for a real, human-paced "
            "workflow (clicking through EVE-NG's UI, the eve-wireshark "
            "container starting, the Windows client launching), causing "
            "persistent, hard-to-diagnose 403s even with correctly "
            "synced clocks."
        ),
    )
    ssh_timeout_seconds: float = Field(default=15.0, description="Timeout for docker ps lookups.")

    @field_validator("ssh_key_path", mode="after")
    @classmethod
    def _check_ssh_key_path_corruption(cls, v: str) -> str:
        _check_windows_path_corruption(v, "CAPTURE_SSH_KEY_PATH")
        return v

    @field_validator("ssh_known_hosts", mode="after")
    @classmethod
    def _check_ssh_known_hosts_corruption(cls, v: str | None) -> str | None:
        if v is not None:
            _check_windows_path_corruption(v, "CAPTURE_SSH_KNOWN_HOSTS")
        return v


class RelayListenSettings(BaseSettings):
    """Which host/port the standalone relay listens on. Not read by the
    main mcp-eveng process -- it has no listener to configure."""

    model_config = SettingsConfigDict(
        env_prefix="CAPTURE_RELAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    listen_host: str = Field(default="0.0.0.0")
    listen_port: int = Field(default=8001)
    token_required: bool = Field(
        default=True,
        description=(
            "If false, the relay streams for any syntactically-valid token "
            "-- including a tampered, hand-crafted, or expired one -- "
            "skipping the signature and expiry checks entirely. An "
            "explicit opt-out of this project's whole capture-token "
            "security model; only appropriate on a network you already "
            "trust. CAPTURE_TOKEN_TTL_SECONDS (on the main process) still "
            "controls how long a normally-issued token stays valid when "
            "this is left at its default, true."
        ),
    )
    log_level: str = Field(
        default="INFO",
        description="Python logging level: DEBUG, INFO, WARNING, ERROR, or CRITICAL",
    )
    tls_cert_path: str | None = Field(
        default=None,
        description=(
            "Path to a TLS certificate file. Serves the relay over HTTPS "
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
    def _tls_cert_and_key_together(self) -> RelayListenSettings:
        if bool(self.tls_cert_path) != bool(self.tls_key_path):
            raise ValueError(
                "CAPTURE_RELAY_TLS_CERT_PATH and CAPTURE_RELAY_TLS_KEY_PATH must "
                "both be set, or neither -- got only one of the two."
            )
        return self

    @field_validator("tls_cert_path", mode="after")
    @classmethod
    def _check_tls_cert_path_corruption(cls, v: str | None) -> str | None:
        if v is not None:
            _check_windows_path_corruption(v, "CAPTURE_RELAY_TLS_CERT_PATH")
        return v

    @field_validator("tls_key_path", mode="after")
    @classmethod
    def _check_tls_key_path_corruption(cls, v: str | None) -> str | None:
        if v is not None:
            _check_windows_path_corruption(v, "CAPTURE_RELAY_TLS_KEY_PATH")
        return v

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, v: str) -> str:
        level = str(v).strip().upper()
        if level not in _VALID_LOG_LEVELS:
            raise ValueError(f"CAPTURE_RELAY_LOG_LEVEL must be one of {_VALID_LOG_LEVELS}, got {v!r}")
        return level


class CaptureURLSettings(BaseSettings):
    """The relay's externally-reachable address, for building
    `capture://` URLs in `get_capture` -- distinct from
    `RelayListenSettings.listen_host`, which is a *bind* address
    (`0.0.0.0` is meaningless as something a client connects *to*).
    Read only by the main mcp-eveng process.

    Shares the `CAPTURE_RELAY_` prefix with `RelayListenSettings` (no
    collision -- different field names), and defaults `advertise_port`
    to the same 8001 as `RelayListenSettings.listen_port`, so a single
    shared `.env` with just `CAPTURE_RELAY_ADVERTISE_HOST` set "just
    works" when the relay and the advertised address are the same
    machine on the default port; override independently if not.
    """

    model_config = SettingsConfigDict(
        env_prefix="CAPTURE_RELAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    advertise_host: str = Field(
        ..., description="Hostname/IP the .bat connects to for streaming -- not the bind address."
    )
    advertise_port: int = Field(default=8001)


@lru_cache
def get_capture_ssh_settings() -> CaptureSSHSettings:
    return CaptureSSHSettings()  # type: ignore[call-arg]


@lru_cache
def get_relay_listen_settings() -> RelayListenSettings:
    return RelayListenSettings()


@lru_cache
def get_capture_url_settings() -> CaptureURLSettings:
    return CaptureURLSettings()  # type: ignore[call-arg]
