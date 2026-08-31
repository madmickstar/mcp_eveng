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

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        default=60,
        description="How long a get_capture token stays valid. Short by design -- see tokens.py.",
    )
    ssh_timeout_seconds: float = Field(default=15.0, description="Timeout for docker ps lookups.")


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
