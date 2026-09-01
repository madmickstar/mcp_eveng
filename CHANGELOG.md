# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.2] - 2026-08-31

### Documentation
- **`install-windows.md` reviewed following user edits, per direct
  request to check for breakage**: found one clear bug (a new heading,
  `## HTTPs Cert Paths Require / `, that looked like an unfinished
  edit -- trailing `/ ` with no continuation, and too narrow for its
  own content, which covers every `*_PATH` variable, not just TLS
  certs -- `CAPTURE_SSH_KEY_PATH` is an SSH key, not a cert). Renamed
  to `Windows paths: use forward slashes`, content unchanged. No
  cross-section collision risk here the way `install-linux.md` had
  (no systemd section on Windows to collide with, and Install itself
  wasn't touched). Also fixed: the TOC, which the reporter had already
  flagged as not yet updated; the same inconsistent heading style
  between the two "Client integration" sections found in
  `install-linux.md` (now `Client integration: <transport>` in both
  docs, for consistency); a stray blank line left inside a code block
  from an earlier edit. Confirmed the removed `MCP_ALLOWED_HOSTS`
  example/Windows-Firewall note/`mcp-remote` link were deliberate
  simplifications, not left in place.

- **`docs/manual-curl-commands.md`'s commands didn't work on Windows**
  -- confirmed live, reported directly: every example used bash-style
  single-quoted inline JSON (`-d '{"jsonrpc":...}'`), but `cmd.exe`
  doesn't treat single quotes as string delimiters the way bash does,
  so the payload arrives with literal quote characters baked in,
  breaking JSON parsing (compounded by `cmd.exe`'s own argument
  splitting getting confused by the JSON's many embedded double
  quotes on top of that). Confirmed working alternative (per direct
  testing, both `http://` and `https://`): write the JSON to a file
  first, then `-d @file.json` instead of the inline `-d '...'` --
  verified this mechanism directly against a real running server
  before documenting it. Added as a new step 2, ahead of the existing
  bash-style examples, rather than duplicating every example in both
  styles.

- **`install-linux.md` restructured following user edits, per direct
  request to check for breakage**: the edited "Install" section now
  always targets `/opt/mcp_eveng` with `sudo` (confirmed intentional,
  not reverted) -- but this collided with the systemd section's own
  identical clone command, which would fail with "destination path
  already exists" for anyone following both sections in sequence (a
  realistic path: quick stdio test first, systemd deployment later).
  Fixed by making "Install" the single canonical first step and
  removing the now-redundant clone/venv/install steps from the systemd
  section, which just builds on it -- reducing that section from 7
  steps to 5, with every cross-reference to the old step numbering
  (`.env.example` x2, `capture-relay.md` x1) updated to match. Also
  fixed along the way: a stale ".[dev] instead of `.`" instruction
  that no longer corresponded to the actual command shown (which used
  a full path, not a bare `.`) after an earlier edit; a repeated
  "enviroment" typo; inconsistent heading style between the two
  "Client integration" sections (one had parens, one didn't) -- both
  now use `Client integration: <transport>`, which also produces
  cleaner anchors than the previous "... - (...)" phrasing; the TOC,
  which the reporter had already flagged as not yet updated to match.
  A doubled `# #` introduced while fixing one of the cross-references
  was caught and corrected before being included here.

- **`eve-capture.bat`'s comments trimmed from 272 to 170 lines** -- per
  direct feedback, refined every comment down to what a variable/section
  is and its practical impact/options, with all "confirmed live"
  debugging narrative and historical bug-fix context removed. Verified
  by diffing every non-comment line against the previous version --
  identical except two already-approved changes from earlier (the
  `CURL` default path, window title format), confirming this pass
  touched comments only, no functional change.
- **Root cause found for the Windows `curl.exe`/Schannel
  `SEC_E_INTERNAL_ERROR` failure documented in the previous release**:
  not Windows' `curl.exe` itself, but the TLS certificate's key
  algorithm. Confirmed by directly comparing two real certificates
  (one that triggered the error, one that didn't) -- the only
  meaningful difference was ECDSA P-521 (`secp521r1`) vs RSA, matching
  a known, Microsoft-documented Windows Schannel incompatibility with
  P-521 specifically (P-256/P-384 ECDSA and RSA are unaffected).
  `eve-capture.bat`'s `CURL` variable now defaults back to Windows'
  own bundled `C:\Windows\System32\curl.exe` (previously pointed at a
  separate curl.se download by default) -- the earlier workaround is
  no longer the primary advice, since the actual fix is regenerating
  the certificate with a different key algorithm; the curl.se
  alternative is still mentioned as a fallback if that's not an
  option. Documented in `README.md`'s TLS section and both
  `MCP_TLS_CERT_PATH`/`CAPTURE_RELAY_TLS_CERT_PATH` comments in
  `.env.example`.

- **README's "Available MCP tools" table now has `Comm Eve`/`Pro Eve`
  columns**, ticked per tool, instead of inline "PRO only" notes
  scattered through the description column (removed from
  `set_link_quality`/`get_link_quality`/`list_captures`/`get_capture`'s
  descriptions once the columns made them redundant -- "Disabled by
  default" left in place, a separate concept from edition support).
  Confirmed the 6 PRO-only tools match "EVE-NG Pro vs Community MCP
  tools" exactly (`export_node`, `share_lab`, `set_link_quality`,
  `get_link_quality`, `list_captures`, `get_capture`) -- `connect_interface`
  is available on both editions (just behaves differently), so it's
  ticked in both columns, not flagged as PRO-only.
- **`install-linux.md`'s `/etc/mcp-eveng` step never actually showed
  how to `chmod`/`chown` the PEM files themselves once you put them
  there** -- only the directory. Added explicit commands, in the same
  code block, for both the main process's `cert.pem`/`key.pem` and the
  relay's `relay-cert.pem`/`relay-key.pem`, using the exact filenames
  already suggested in `.env.example` so there's nothing to translate
  between the two. Certs get `640` (not sensitive -- routinely served
  publicly as part of the TLS handshake); keys get the stricter `600`.

### Fixed
- **`eve-capture.bat`'s window title (`EVE Capture - <name>`) was too
  long** -- confirmed live, testing the window-title feature. Dropped
  the `EVE Capture - ` prefix on both paths (relay/PRO and Community);
  the window title is now just the capture name itself (e.g.
  `Capture-2101248` or `vunl0_1_0`).

### Documentation
- **`CAPTURE_SSH_KNOWN_HOSTS`'s suggested path was `/etc/mcp-eveng`,
  requiring a whole separate directory setup, when it could just reuse
  the `~/.ssh` directory `CAPTURE_SSH_KEY_PATH`'s own private key
  already lives in** -- per direct feedback, confirmed there was no
  actual technical reason for this: `known_hosts` is a plain SSH
  artifact with no special requirement to live under `/etc/`, unlike
  TLS certs (a genuinely different kind of credential, where `/etc/
  mcp-eveng` remains the right suggestion, unchanged). Now suggested at
  `/home/mcp-eveng/.ssh/known_hosts`, matching `CAPTURE_SSH_KEY_PATH`'s
  own existing convention -- no separate directory/permissions step
  needed, since that directory already exists and is already correctly
  permissioned by the time anyone reaches this setting.

## [0.6.1] - 2026-08-31

### Documentation
- **Combining a server certificate with a CA certificate into one PEM
  file requires the server cert FIRST, CA cert below it** — confirmed
  directly with a real CA-signed cert pair: the reverse order fails
  with `OSError [X509: KEY_VALUES_MISMATCH] key values mismatch`, since
  `load_cert_chain()` matches the *first* certificate in the file
  against the private key, not any certificate that happens to be
  present. A universal PEM chain-file convention, not specific to this
  project, but undocumented here until now. Added to `README.md`'s TLS
  section and both `.env.example`'s `*_TLS_CERT_PATH` comments.

### Added
- **Ready-to-use systemd unit files** (`systemd/mcp-eveng.service`,
  `systemd/mcp-relay.service`) — `install-linux.md`/`capture-relay.md`
  now `cp` these directly instead of having the reader hand-type or
  copy-paste the same content from a markdown code block, which also
  means the docs and the actual files can't drift out of sync with
  each other the way two separate copies of the same content could.
  README's Project layout tree refreshed while in there — it had grown
  quite stale (missing `capture_relay/`, several `docs/` additions,
  `.env.example`, `scripts/`, `assets/`).

### Changed
- **`mcp-eveng` and `mcp-relay` now share ONE venv and ONE `.env` file
  -- `/opt/mcp_relay` as a separate deployment no longer exists.** Per
  direct feedback: now that `asyncssh`/`starlette`/`uvicorn` are base
  dependencies (see the entry below), both processes are just two
  different entrypoints (`mcp-eveng`, `mcp-eveng-capture-relay`) of the
  exact same installed package -- there was no longer a real reason for
  a second venv. Confirmed directly, not assumed: every settings class
  involved already uses `extra="ignore"`, so pointing both processes at
  the same `.env` file works with zero code changes -- verified by
  actually loading `EvengSettings`/`MCPTransportSettings`/
  `CaptureSSHSettings`/`CaptureURLSettings`/`RelayListenSettings` all
  from one real combined file and confirming each correctly reads only
  its own variables. This also fixes a genuine footgun: `CAPTURE_SSH_*`
  and `CAPTURE_TOKEN_SECRET` previously had to be kept identical across
  two separate files by hand; now there's only one declaration of each,
  so they can't drift out of sync at all. `.env.capture-relay.example`
  is gone -- merged into `.env.example` as a clearly-labeled section
  below the main settings, per direct request not to mix the two.
  `docs/capture-relay.md` restructured accordingly (steps 5/6 merged
  into one settings step; the systemd unit now uses
  `WorkingDirectory=/opt/mcp_eveng`, matching `mcp-eveng.service`
  itself, with only `ExecStart` differing between the two units) and
  `docs/upgrading.md` simplified to one `pip install` covering both
  services. 618 tests still pass unchanged -- this was a deployment/
  docs restructuring, not a code-logic change, confirmed by the test
  suite and every source file needing zero changes beyond what's
  already covered by the entry below.

- **`asyncssh`/`starlette`/`uvicorn` folded into the base install --
  the optional `capture-relay` extra is gone.** Per direct feedback:
  the complexity of a separate extra wasn't worth it for the actual
  size of what it gated. Confirmed exactly what that extra was really
  adding: `starlette`/`uvicorn` were already pulled in transitively by
  `mcp[cli]` itself (its own `--sse`/`--http` transports are built on
  both), so the only genuinely new dependency was `asyncssh` (plus its
  own single dependency, `cryptography`) -- a small, single-purpose
  library, not worth a separate install step for. Verified end-to-end
  in a fresh, clean venv: a plain `pip install -e .` (no extra) now
  installs everything `list_captures`/`get_capture` and the standalone
  relay both need. `docs/capture-relay.md` steps 5/6 and
  `docs/upgrading.md` updated to drop `[capture-relay]` from every
  install/upgrade command; step 6 renamed from "Install and config" to
  "Config" since there's nothing left to separately install if
  `mcp-eveng` was already set up via `install-linux.md`'s systemd
  section. `_require_asyncssh()`'s error message (in the unlikely case
  it's still missing on a broken/incomplete install) updated to match
  -- it's a base dependency now, not something to `pip install` an
  extra for.

## [0.6.0] - 2026-08-31

### Documentation
- **`/etc/mcp-eveng` was referenced as a suggested path in 6 places
  across `.env.example`/`.env.capture-relay.example` (TLS certs, TLS
  keys, SSH `known_hosts`) but never actually documented anywhere** --
  no instructions existed to create it or set correct ownership/
  permissions. Added a new step 5 to `install-linux.md`'s systemd
  section (`mkdir`/`chown mcp-eveng:mcp-eveng`/`chmod 750`, private
  key files specifically `600`), with a note that `ProtectSystem=strict`
  doesn't block *reading* from there -- only writing, which this
  directory is never used for -- so no systemd unit change is needed.
  `docs/capture-relay.md` and every `.env.example`/
  `.env.capture-relay.example` comment suggesting this path now points
  back to that step. `install-windows.md` needs nothing -- no systemd
  section, and `/etc/mcp-eveng` is a Linux-specific convention anyway.

### Fixed
- **`eve-capture.bat`'s curl calls could silently resolve to Windows'
  own bundled Schannel-based `curl.exe` instead of a working
  alternative** -- confirmed live: Windows' `curl.exe` (Schannel, its
  native TLS stack) fails against this relay over HTTPS with a cryptic
  `schannel: next InitializeSecurityContext failed:
  SEC_E_INTERNAL_ERROR`, while the official curl.se Windows build
  (a different TLS backend) connects to the exact same server without
  issue -- a genuine Windows/Schannel-level quirk, not specific to
  this project (the identical error shows up against totally unrelated
  HTTPS servers on affected machines, confirmed via a live test
  against `https://www.google.com`). All three curl invocations
  (availability check, preflight, real stream) now use a new
  configurable `CURL` variable, matching the existing `WIRESHARK`/
  `PLINK` pattern -- an explicit full path by default, not a bare
  `curl.exe` relying on `PATH`, since `PATH` order can silently
  resolve back to Windows' own Schannel-based curl even after
  installing a working alternative, reintroducing the exact same
  failure with no obvious cause.
- **`python-dotenv` silently corrupts Windows paths inside
  double-quoted `.env` values** -- confirmed live, hit by a real
  Windows user: a path like `"C:\path\to\...\certs\newkey.pem"` parses
  back with an actual TAB character where `\to\` was and an actual
  NEWLINE where `\new...` was, since `\t`/`\n`/etc. are recognized
  escape sequences inside double-quoted values, not literal
  backslash-letter text. Windows paths can't contain control
  characters, so this then fails deep inside OpenSSL's
  `load_cert_chain()` with the exact same unhelpful `OSError: [Errno
  22] Invalid argument` as the previous entry below -- two genuinely
  different root causes producing an identical, unhelpful symptom, only
  told apart by directly reproducing the corruption with a synthetic
  `.env` file matching the real path's shape and confirming the actual
  control characters land in the parsed value. Fixed with a validator
  on every `*_PATH` settings field across both processes
  (`MCP_TLS_CERT_PATH`/`_KEY_PATH`, `CAPTURE_RELAY_TLS_CERT_PATH`/
  `_KEY_PATH`, `CAPTURE_SSH_KEY_PATH`, `CAPTURE_SSH_KNOWN_HOSTS`) that
  detects a literal control character in the value and explains
  exactly what happened and how to fix it (forward slashes, or single
  quotes instead of double) -- confirmed live against the exact
  corruption pattern that caused the original report. Also documented
  prominently in `.env.example`, `.env.capture-relay.example`, and
  `install-windows.md`, so Windows users can avoid this happening in
  the first place rather than needing to hit and diagnose it. 12 new
  tests; `ruff`/`mypy` clean.
- **A bad TLS cert/key path (typo, missing file, wrong permissions) on
  either `mcp-eveng` or `mcp-relay` surfaced as an utterly unhelpful
  `OSError: [Errno 22] Invalid argument`, deep inside OpenSSL's own
  `load_cert_chain()`, with no indication of which of the two files
  was the problem or what was actually wrong with it** -- hit live: a
  single missing path segment in `CAPTURE_RELAY_TLS_KEY_PATH`
  (`certskey.pem` instead of `certs\key.pem`) produced this exact
  cryptic error with nothing pointing at the actual typo. Root cause
  confirmed by researching the exact error/traceback signature: this
  is a known, generic failure mode of Python's `ssl` module on a bad
  path or an encrypted key with no password supplied, not specific to
  this project's own code, and not something a clearer message from
  `uvicorn`/OpenSSL could be coaxed out of after the fact. Fixed by
  adding a pre-flight check, in both `server.py`'s `_run_networked`
  and `capture_relay/__main__.py`'s `main()`, that opens each
  configured TLS file itself before ever reaching `uvicorn.Config`/
  `uvicorn.run` -- on failure, prints a clear message naming the exact
  variable (`MCP_TLS_CERT_PATH`/`_KEY_PATH` or
  `CAPTURE_RELAY_TLS_CERT_PATH`/`_KEY_PATH`) and the exact path, then
  exits cleanly (code 1, no traceback) rather than letting the
  original cryptic `OSError` propagate. Confirmed live on both
  processes: a bad path now exits immediately with a clear message; a
  valid cert/key pair still works exactly as before. 11 new tests
  (both the check function directly and that `main()`/`_run_networked`
  genuinely call it before touching uvicorn, not just that the check
  works in isolation) -- two pre-existing tests were using fake,
  non-existent example paths for their TLS settings and needed
  updating to real temp files once this check started actually
  opening them. 610 passed; `ruff`/`mypy` clean.

### Added
- **`CAPTURE_RELAY_LOG_LEVEL` for the standalone relay** -- confirmed
  it had no log-level configuration at all (no `logging.basicConfig()`
  anywhere in `capture_relay/`, and `uvicorn.run()` never passed a
  `log_level`, so it silently used uvicorn's own built-in default,
  `"info"`, with no way to change it). Adding it to the relay's `.env`
  before this had zero effect -- confirmed the settings model uses
  `extra="ignore"`, so it wouldn't even error, just be silently
  dropped. Matches the main `mcp-eveng` process's own
  `MCP_LOG_LEVEL` pattern exactly (same validation, same default,
  same `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` set) but under its
  own `CAPTURE_RELAY_` prefix, consistent with this settings class's
  other fields (`_LISTEN_HOST`, `_TLS_*`) -- drives both
  `logging.basicConfig()` (this process's own log statements) and
  `uvicorn.run(..., log_level=...)` (uvicorn's own access/error logs)
  separately, since they're genuinely two different mechanisms.
  Confirmed live against a real running relay: a `DEBUG`-level line
  appears with `CAPTURE_RELAY_LOG_LEVEL=DEBUG` set and is correctly
  absent at the default `INFO` level. 6 new tests; `ruff`/`mypy` clean.

## [0.5.0] - 2026-08-31

### Fixed
- **"PRO/Corporate" replaced with "PRO" throughout** (66 mechanical
  occurrences across 17 files, plus 3 "Professional/Corporate/Learning
  Center tiers" mentions rewritten properly) -- EVE-NG has no separate
  "Corporate" product; this project's own edition check is a single
  binary `is_pro_edition()`, with no sub-tier distinction to begin
  with, so the old wording implied a distinction that was never real.
- **A real internal IP address (the tester's own EVE-NG PRO server)
  was hardcoded across 28 places in 7 test files** -- confirmed via a
  full audit of every hostname/IP/username/password literal across the
  whole test suite (everything else checked out: IANA-reserved test
  domains, EVE-NG's own documented defaults, generic placeholders).
  Replaced with the same placeholder already used in the docs
  (`192.168.1.50`) for consistency. Deliberately did NOT rewrite git
  history to scrub it from past commits too -- weighed against the
  actual severity (a private RFC1918 address, not attached to any
  credential or public hostname) and the real disruption a full
  history rewrite causes (every subsequent commit SHA changes, forces
  a rewrite on every existing clone/fork), the forward-only fix was
  judged proportionate.
- **`.env.example`/`.env.capture-relay.example` spacing was
  inconsistent** -- blank lines between two adjacent variables with no
  comment describing either one (removed) vs. between a variable and
  the comment block documenting the *next* one (kept) -- per direct
  feedback on which pattern should apply where.

### Documentation
- **"Publishing to PyPI" section removed from the README** entirely.
- **`docs/capture-relay.md` steps 5-7 reorganized** per direct
  feedback: the two install-and-configure steps grouped by *app*
  (`mcp-relay` then `mcp-eveng`) instead of by file type, each with
  its own install command (a missing `git clone` added, with a note
  on why it targets the shared `/opt/mcp_eveng` even under the
  "install mcp-relay" step); step 6's "copy `.env.example`" instruction
  corrected -- that file already exists from the base `mcp-eveng`
  install, so this step now says to update specific existing fields,
  not copy a fresh file, with the field list converted to bullets; a
  "Start app manually" step added after the systemd commands; step 7
  renamed to include "(MCP server)" for clarity.
- **`scripts/eve-capture.bat`**: added self-signed-cert support
  (`-k`/`--insecure` on every curl call -- a no-op on plain HTTP,
  needed for HTTPS against a self-signed cert, the realistic case for
  a relay on a private/lab network) and a new `RELAY_SCHEME` variable
  so the script can actually reach a relay that has TLS configured
  (added in the API-key/TLS work below) at all -- a real gap: relay-side
  TLS support existed with no way for this script to use it until now.
  `--connect-timeout`/`--max-time` (previously hardcoded 5/10) are now
  the configurable `RELAY_CONNECT_TIMEOUT`/`RELAY_MAX_TIME` variables,
  both defaulting to 5 per direct request. Also fixed three stale
  step-number references left over from the `capture-relay.md`
  renumbering (missed in this file specifically at the time) and
  rewrote the file's top status comment, which still said "UNTESTED
  end-to-end" and "still being confirmed" despite everything having
  since been confirmed working live.

### Added
- **Optional API key for `mcp-eveng`'s `--sse`/`--http` transports**
  (`MCP_API_KEY`). When set, every request must present it via
  `Authorization: Bearer <key>` or gets a `401` before it ever reaches
  the MCP handler -- checked with `secrets.compare_digest`, not `==`,
  so a wrong guess can't be narrowed down via response timing.
- **Optional TLS for both `mcp-eveng` and `mcp-relay`**
  (`MCP_TLS_CERT_PATH`/`_KEY_PATH`/`_KEY_PASSWORD` on the main process,
  `CAPTURE_RELAY_TLS_CERT_PATH`/`_KEY_PATH`/`_KEY_PASSWORD` on the
  relay). Cert and key are validated as a pair -- one without the
  other fails fast at startup, not a confusing runtime error.
  `mcp-relay` already called `uvicorn.run()` directly, so this was a
  direct kwarg passthrough. `mcp-eveng`'s `--sse`/`--http` needed more:
  the SDK's own `FastMCP.run()` hardcodes a plain-HTTP `uvicorn.Config`
  with no hook for TLS (or for the API key above), confirmed by reading
  its actual source -- `run_sse_async`/`run_streamable_http_async` both
  build `uvicorn.Config(..., host=..., port=..., log_level=...)` with
  nothing else configurable. Fixed by building the same Starlette app
  the SDK itself would (via its own public `sse_app()`/
  `streamable_http_app()`), optionally wrapping it in the new API-key
  middleware, and serving it with our own `uvicorn.Config` instead --
  `stdio` is untouched, still goes through the SDK's own `mcp.run()`
  entirely, since it never opens a socket and neither feature applies.
  Both confirmed working against real running servers (not just code
  review): correct 401/401/200 sequence across no-key/wrong-key/
  right-key requests, successful TLS handshake on both processes, and
  plain HTTP correctly refused once TLS is configured. 28 new tests
  covering the config validators, the middleware directly (via
  Starlette's `TestClient`), and that settings genuinely reach
  `uvicorn.Config`/`uvicorn.run` rather than just being present
  somewhere in a settings object. `ruff check`/`ruff format --check`/
  `mypy` all clean -- one genuine mypy limitation surfaced along the
  way: `**dict` unpacking against `uvicorn`'s heterogeneously-typed
  keyword arguments doesn't type-check at all, regardless of the
  dict's actual contents; switched to explicit named parameters
  instead (uvicorn's own default for each is already `None`, confirmed
  against its signature), which is cleaner code besides.

## [0.4.0] - 2026-08-30

### Fixed
- **GitHub Actions' CI "lint" job was failing outright** (`Ruff lint`
  step, discovered live via the actual CI run after merging to `main` --
  never caught locally since this project's own verification throughout
  had only ever run `python -m py_compile`, never the real `ruff`/`mypy`
  checks CI actually runs). 110 `ruff check` errors, the large majority
  in files that predate this session's work entirely (`client.py`,
  `edition.py`, `tools/nodes.py`, `telnet.py`, etc.) -- this had almost
  certainly been failing before any of the capture-relay work started,
  just never noticed since CI apparently hadn't run against this repo
  before. Fixed in three passes:
  - `ruff check`: raised `line-length` from 100 to 120 in
    `pyproject.toml` (the single most surgical fix for the ~80 `E501`
    violations, none of which exceeded 114 characters -- manually
    rewrapping dozens of lines across files this session never touched
    would have been far riskier for no real benefit), ran
    `ruff check --fix` for the ~40 mechanically-fixable ones (import
    sorting, unused imports, `typing` -> `collections.abc`
    modernization), then manually resolved the 7 requiring judgment
    (a nested `with` combined into one statement, a `try`/`except`/
    `pass` replaced with `contextlib.suppress`, `.keys()` iteration
    simplified, a tuple-membership check replacing chained `==`, a `for`
    loop replaced with `all(...)`, an `if`/`else` replaced with a
    ternary, and a test's blind `except Exception` narrowed to the
    actual `pydantic.ValidationError` it was testing for).
  - `ruff format --check`: the `line-length` change left 36 files with
    lines the formatter wanted to un-wrap now that they fit comfortably
    -- ran `ruff format .` to apply that.
  - `mypy`: 18 errors, mostly a repeated pattern -- an `int | None`
    (or similarly optional) value passed somewhere expecting a
    non-optional `int`, where the code's own control flow already
    guaranteed it couldn't actually be `None` at that point but `mypy`
    couldn't trace the guarantee across a separately-stored boolean
    flag or an `if`/`else` spanning many lines. Fixed with explicit
    `assert ... is not None` at each such point (zero behavior change
    in the guaranteed-true case; a clear `AssertionError` instead of
    silently proceeding, in the -- believed impossible -- case the
    guarantee is ever violated) or, in `tools/quality.py`, by
    restructuring so the variable is genuinely typed `int` once both
    resolution branches complete rather than carrying an unnecessary
    `int | None` union throughout. Separately, `tools/nodes.py`'s and
    `tools/networks.py`'s `_node_id`/`_delay_node_id`/`_network_id`
    helpers had a real (if narrow) latent crash risk -- `int(node.get(
    "id", node.get("_key")))` would raise an unhandled `TypeError` if a
    record ever had neither key -- now raise a clear `ValueError`
    instead if that ever happens, rather than mypy simply being told to
    ignore the possibility.
  All three (`ruff check`, `ruff format --check`, `mypy src/`) now pass
  cleanly, confirmed by actually running each one, not just reasoning
  through the fixes. Full test suite re-run afterwards with zero
  regressions (identical to the pre-existing baseline failure list at
  the time), confirming this large a cleanup pass changed no actual
  behavior.
- **All 7 previously-"established baseline" test failures were actually
  genuine, fixable bugs -- confirmed live via a real GitHub Actions run
  with full tracebacks, not just reasoned through.** This project's own
  local verification had been comparing against these 7 as an
  unexamined "known failure list" for the entire engagement without
  ever diagnosing them individually; the real CI output made that no
  longer defensible.
  - `test_generic_api_error`: a test bug, not a client bug -- the test
    never mocked the `/auth/login` call that `EvengClient`'s own
    (correct, extensively documented) relogin-on-400 behavior triggers.
    Fixed by mocking the full sequence (initial 400, login, retried
    400) instead of assuming a single request.
  - `test_extract_vendor_collapses_known_typo_alias`: EVE-NG's own
    catalog typo `"Barraccuda"` was documented in `vendor.py`'s own
    comments as a case this handles, but the actual alias entry was
    missing from `_VENDOR_ALIASES` -- added.
  - Three `test_open_lab_*` tests: `open_lab` computed `lock` as a
    proper bool via `_is_locked()`, then immediately overwrote it with
    the raw (int/string) value via `{"lock": locked, **data}` -- `data`
    itself carries its own raw `lock` field, and a later key in a dict
    literal always wins over an earlier one. Fixed by reordering to
    `{**data, "lock": locked, ...}`.
  - `test_add_lab_node_selection_by_exact_name_resolves_template`:
    `resolve_selection` (shared by every search/select/confirm tool)
    tokenizes on commas/whitespace for multi-select (e.g. "R1, R2"),
    which incorrectly split a single space-containing exact name like
    `"Cisco Catalyst 8000v"` into three separate, individually
    unmatchable words. Fixed by trying the whole (stripped) selection
    as one exact match first, falling through to the existing
    token-splitting only if that doesn't match anything -- confirmed
    via the full `test_confirmation.py`/`test_nodes.py`/`test_labs.py`/
    `test_folders_networks_users.py` suite that genuine multi-select
    (comma/whitespace-separated numbers or names) still works
    identically.
  - `test_eve_start_node_all_nodes_one_failure_does_not_block_others`:
    the partial-failure branch of `_loop_node_action`'s message
    reported a success *count* but never named which nodes actually
    succeeded, unlike the all-succeeded branch, which did. Fixed for
    consistency.
  All fixes verified: full suite went from 7 failing to 565 passing,
  `ruff check`/`ruff format --check`/`mypy src/` all still clean
  afterwards. None of the 7 root causes touch anything Python-version-
  specific (dict-literal duplicate-key ordering, plain `re.split`,
  string formatting, missing test mocks, a missing dict entry) --
  confirmed by direct reasoning through each mechanism, though only
  actually re-run under Python 3.12 in this environment; the project's
  own CI matrix (3.10-3.13) is the definitive cross-version check.

### Added
- **`get_link_quality`: new PRO-only tool complementing
  `set_link_quality`.** Gets the current delay/jitter/packet-loss/
  bandwidth on both sides of an existing connection -- the given node's
  interface, and whatever's on the opposite end, resolved automatically
  via the same topology-resolution logic `set_link_quality` already
  uses. Accepts either `node_id` or `node_name` (case-insensitive
  substring match, matching the existing pattern from
  `change_node_delay`'s `names` parameter) -- multiple name matches
  return `selection_required` with the candidates listed, rather than
  guessing. If the far side is network-attached, reports it as
  `settable: false` with all four values `0` and the network's actual
  name (resolved via `list_lab_networks`, falling back to the raw
  `"network<id>"` token if that lookup fails) rather than just the
  opaque topology token. Registered and enabled by default on PRO
  (matching `set_link_quality`); tool-parity tests updated (four
  edition-gated tools, not three). 14 new tests; `ruff check`,
  `ruff format --check`, and `mypy` all clean.

### Documentation
- **README.md restructured for scannability**, per direct feedback that
  it was still too word-heavy to scan quickly: Features section reduced
  to one line per feature (plus a "sales pitch" bullet on bulk edits);
  a new "Run App" section replacing "Choosing a transport" with three
  bare `python -m mcp_eveng` command examples; "PRO vs Community
  differences" renamed to "EVE-NG Pro vs Community MCP tools" (the
  project itself has no PRO/Community version, only EVE-NG does),
  moved after Configuration and before Available tools, and its
  per-tool bullets reduced from full paragraphs to one line each, with
  two long tangential paragraphs removed entirely; "Available tools"/
  "Controlling which tools are exposed" renamed to "Available MCP
  tools"/"Controlling which MCP tools are exposed" (every cross-
  reference updated, including two stale ones found along the way); "A
  note on sessions and relogin" moved to just above "Known issues",
  its full content relocated to `docs/tools-reference.md`.
- **`docs/capture-relay.md` steps reorganized** per direct feedback that
  the `.env`-then-install split was confusing: "Append the public key"
  and "Sudoers" split into their own EVE-NG-host-labeled steps; the two
  install-and-configure steps reorganized by *app* (`mcp-relay` then
  `mcp-eveng`) rather than by *file type*, each now including its own
  install command (a missing `git clone` was also added); a "Start app
  manually" step added after the systemd commands; the keypair step's
  Windows example moved to last, followed immediately by a PowerShell
  `icacls` permission-fix block; separate `PRO_SSH_*`/`COMMUNITY_SSH_*`
  credential variables (previously incorrectly shared) in the `.bat`
  reference.
- **Two new pages, each linked from every relevant page**:
  `docs/upgrading.md` (updating an existing `mcp-eveng`/`mcp-relay`
  install, both systemd and manual/dev paths) and
  `docs/manual-curl-commands.md` (testing the server directly over
  HTTP without an MCP client -- every command in it, including the
  full `initialize`/`notifications/initialized`/`tools/call` sequence,
  was actually run against a live local server before being written
  down, which is how a real gotcha was caught: the default
  `MCP_ALLOWED_HOSTS=localhost:*` rejects `127.0.0.1`, only `localhost`
  works).

## [0.3.17] - 2026-08-30

**Capture-relay feature branch (`feature/capture-relay`), merged to
`main` after a full round of live testing -- every major path
confirmed working end-to-end:** stopping the relay mid-stream
(cleanly breaks the stream rather than hanging/orphaning the remote
process), adding/deleting link-quality settings on both source and
destination interfaces, curl-based streaming on PRO, plink-based
streaming on PRO (the fallback path), and plink-based streaming on
Community. Developed across many small, individually-tested commits
(see the full history in `feature/capture-relay` if useful) rather
than as one large, unverified change -- summarized below by area
rather than repeating every individual commit message.

### Fixed
- **`docs/capture-relay.md` had no instructions at all for running the
  relay anywhere except via systemd, which is Linux-only** -- a real
  gap surfaced by a genuine Windows test setup, not a hypothetical.
  Confirmed live that `python -m mcp_eveng.capture_relay` (or the
  installed `mcp-eveng-capture-relay` console script) works exactly
  like running the main process interactively
  (`python -m mcp_eveng --http`) -- nothing in `uvicorn`/`asyncssh`/
  Starlette is Linux-specific, only the systemd deployment steps are.
  Added a new "Running the relay for manual/interactive testing (any
  OS, including Windows)" section to step 5, including the easy-to-miss
  detail that the `.env` read is whichever one sits in the current
  working directory at the moment the command is run -- same
  convention the main process already uses -- so testing both
  processes on the same machine means running each from its own
  separate directory, not the same one.
- **Community-mode captures could fail with Wireshark reporting `File
  type is neither a supported pcap nor pcapng format... magic =
  0x6b63696d`, even though the underlying capture was fine.** Decoded
  live: those four bytes are the literal ASCII text `mick` -- the
  tester's own Windows username -- meaning something was leaking
  non-pcap text into the piped stream ahead of any real capture data.
  Root cause: no plink call in the script used `-batch`, so plink was
  free to prompt interactively for anything it couldn't resolve
  non-interactively -- most likely an unconfirmed SSH host key on a
  first-time connection (not suppressed by `-no-antispoof`, a
  different, unrelated flag) -- and since the whole command's stdout is
  piped straight into Wireshark expecting pure pcap/pcapng bytes,
  prompt/banner text corrupts that stream instead of the command
  failing cleanly. Added `-batch` to all four plink invocations (both
  PRO-fallback and Community-mode, both the key-based default and the
  commented-out password-based alternative) -- the correct behavior for
  a piped, scripted invocation regardless of the exact root cause.
  Also, per direct feedback: split the single shared
  `COMMUNITY_SSH_USER`/`COMMUNITY_SSH_KEY` pair into separate
  `PRO_SSH_USER`/`PRO_SSH_KEY` (this project's own dedicated
  relay-fallback account) and `COMMUNITY_SSH_USER`/`COMMUNITY_SSH_KEY`
  (whatever account the existing, separate Community setup uses) --
  the script was silently assuming these were interchangeable, which
  they aren't in general. Default `PLINK` path corrected to PuTTY's
  actual default install location
  (`C:\Program Files\PuTTY\plink.exe`, was a placeholder). Confirmed
  (per direct feedback, no fix needed): the curl preflight's ~10s
  discard window (see the widened-timeout fix above) is an accepted,
  deliberate tradeoff, not a bug to chase further.
- **Stopping the relay (`systemctl stop mcp-relay.service`) while a
  capture was streaming would hang, then eventually SIGKILL the whole
  process, orphaning the remote `dumpcap` process on the EVE-NG host --
  confirmed against uvicorn's own source, not assumed.** uvicorn's
  `timeout_graceful_shutdown` defaults to `None`, and `asyncio.wait_for(
  ..., timeout=None)` waits forever -- the code path that cancels
  remaining in-flight requests is never reached at all. Since a capture
  stream is designed to never finish on its own (that's the whole
  point), `systemctl stop` would hang until systemd's own, much longer
  default `TimeoutStopSec` (90s) gave up and SIGKILLed the process --
  bypassing Python's own cleanup entirely (the `async with` chain in
  `streaming_process` that closes the SSH channel, which is what
  actually terminates the remote process; also confirmed directly
  against `asyncssh`'s own source: closing the process context manager
  closes the channel, which is exactly what's needed). Fixed by setting
  `timeout_graceful_shutdown=5` explicitly in `__main__.py`'s
  `uvicorn.run()` call, so uvicorn cancels any still-running stream
  itself after 5 seconds -- Python's normal task-cancellation-through-
  `async with` semantics then run that same cleanup chain correctly.
  Added `TimeoutStopSec=20` to the relay's systemd unit in
  `docs/capture-relay.md` as a safety net on top of that (comfortably
  longer than the 5s, so uvicorn's own graceful path is what normally
  handles this, with SIGKILL only as a last resort if that somehow
  doesn't complete in time). 2 new tests: one confirming
  `_stream_capture`'s cleanup genuinely runs when its task is cancelled
  (using a tracked fake context manager, not just asserted by
  inspection), one confirming `main()` actually passes
  `timeout_graceful_shutdown` through to `uvicorn.run` and not just
  present somewhere in the file.
- **The Community-mode `tcpdump` command was missing `sudo`, per direct
  feedback: the real original Community `.bat` this was copied from
  authenticates as root (no `sudo` needed for raw-capture privileges),
  but this deployment's `mcp-eveng` account is deliberately non-root,
  authenticating via the `capture_relay` group instead -- `sudo` is
  required here even though it wasn't in the source this was copied
  from.** Added `sudo` back to both the primary and password-based
  Community `tcpdump` invocations in `scripts/eve-capture.bat`. Also
  incorporated a third sudoers rule (confirmed from the user's own
  deployed `/etc/sudoers.d/capture_relay`) into `docs/capture-relay.md`
  step 3 for this command -- `%capture_relay ALL=(root) NOPASSWD:
  /usr/bin/tcpdump -U -i * -s 0 -w -*` -- with a trailing `*` after
  `-w -` specifically, per a sharp catch: sudoers matches a command
  exactly unless its own spec ends in a wildcard, and the Community
  `.bat` conditionally appends `not port 22` after `-w -` for the
  `pnet0` interface case, which the two PRO sudoers rules never do (so
  correctly have no trailing `*`, not an oversight). Split the sudoers
  example into three separate, commented rules matching the real
  deployed file's own structure, rather than one dense comma-joined
  line.
- **The `.bat`'s plink invocations never actually pointed at a private
  key -- `plink` has no equivalent to `ssh`'s automatic key discovery,
  and this project's own key-based auth setup (`docs/capture-relay.md`
  step 2) was silently unusable through either plink call as a result.**
  Added `-i "%COMMUNITY_SSH_KEY%"` to both the PRO-fallback and
  Community-mode plink commands, plus a `COMMUNITY_SSH_KEY` variable
  to configure, and a commented-out `-pw`-based alternative at each
  call (matching the original Community `.bat`'s own approach) for
  anyone who'd rather use password auth instead.
- **Replaced the reconstructed Community-mode command block with the
  real, working one, copied directly from an existing Community `.bat`
  rather than guessed from a prose description.** Confirmed real
  differences from the earlier reconstruction: no `sudo` at all
  (Community's SSH account apparently doesn't need it for this, unlike
  this project's own dedicated relay-fallback account, which still
  does); `tcpdump -U -s 0` (unbuffered output -- important for a live
  stream, not a completed capture -- and snaplen 0, capturing the full
  packet); and a `not port 22` filter applied specifically when the
  interface is exactly `pnet0` (excluding the SSH session's own
  traffic from a capture on an interface that happens to carry it too).
- **Widened the curl preflight's timeout window (`--connect-timeout`
  3s->5s, `--max-time` 5s->10s) after live evidence it was too tight
  for a genuinely-working relay.** Observed live: a preflight timeout
  at ~3004ms immediately followed by Wireshark receiving a real,
  successful capture moments later via the separate, unbounded
  streaming call -- meaning the relay's actual round-trip (SSH connect
  + sudo + `docker exec` + `dumpcap` startup) legitimately took longer
  than the old window without anything being broken. This is also the
  first confirmed case of a real capture reaching Wireshark
  successfully end-to-end, though which code path actually delivered
  it (the real curl stream, vs. the plink fallback) isn't fully
  confirmed -- plink's missing `-i` flag (see above) makes a
  successful fallback in that same run less likely than the real
  stream having worked despite the tight preflight, but this isn't
  certain either way.
- **The relay crashed with `asyncssh.misc.ProtocolError: 'utf-8' codec
  can't decode byte ... invalid continuation byte` the moment a real
  capture actually reached it.** Confirmed live, with a full stack
  trace: `asyncssh.create_process()` defaults to UTF-8 text mode
  (verified directly against the installed library's own docstring,
  not assumed) unless told otherwise, but `dumpcap`'s output (`-w -`)
  is raw binary pcap/pcapng, not text at all -- asyncssh tried to
  decode the first non-UTF-8 byte of genuine capture data and failed
  immediately. Fixed with `encoding=None` on `create_process` in
  `streaming_process` (`ssh_client.py`) -- asyncssh's own documented
  way to request raw bytes. `run_command` (used only for `docker ps`,
  genuinely textual output) was correctly left in text mode; this fix
  is specific to the binary streaming path. This is exactly the kind
  of bug `ssh_client.py`'s own "thin enough to be correct by
  inspection, but genuinely unverified" caveat was hedging against --
  and it was wrong at least this once. Added 2 new tests mocking
  `asyncssh.connect`/`create_process` directly to assert the actual
  arguments reaching asyncssh (`encoding=None` present,
  `_connect_kwargs` passed through correctly) -- this class of bug
  (wrong arguments passed to the SSH library) turns out to be testable
  without a live server after all, even though the SSH round-trip
  itself still isn't; updated `ssh_client.py`'s and this doc's status
  notes accordingly rather than leaving the old blanket "not
  unit-tested" claim in place now that it's no longer fully accurate.
- **The `.bat`'s curl preflight could treat a genuine connection
  failure as success.** Confirmed live: `curl: (28) Connection timed
  out` (the relay wasn't reachable at all) was indistinguishable, by
  exit code alone, from "connected fine, was streaming, got cut off by
  our own `--max-time` before the indefinite body ever finishes" --
  both produce curl exit code `28`. The previous preflight design
  (introduced to fix the separate curl-exit-code-through-a-pipe issue)
  treated any `28` as success, so a real connection failure launched
  Wireshark anyway with nothing to actually show. Fixed by checking the
  *actual response headers* instead of inferring from the exit code:
  `--connect-timeout` now bounds just the TCP handshake, separately
  from the overall `--max-time`; headers (if any were received at all)
  are dumped to a temp file and checked afterward with `findstr` for a
  genuine `200` status line, which is present only if the relay
  actually accepted the token and started responding, regardless of
  which timeout curl's own exit code happens to reflect. Also updated
  the `.bat`'s and `docs/capture-relay.md`'s status notes to reflect
  what this same live test actually confirmed working: the new
  path-segment URL format parses correctly all the way through to
  reaching curl (the previous two bugs are resolved) -- the streaming
  path itself, the plink fallback, and Community mode remain
  unexercised live. Added a troubleshooting entry to "Known
  limitations" for relay-unreachable symptoms (service not running,
  advertised vs. listen address mismatch between the two separate
  `.env` files, firewall) as a first checklist before assuming a script
  bug, since that's what this specific live test turned out to be.
- **A second, distinct `capture://` URL parsing bug found live even
  after switching the query separator from `&` to `;` -- the argument
  came through truncated right after the first field name (`?token`,
  nothing after it, not even `=`).** Exact mechanism unconfirmed --
  somewhere between the browser's handling of a non-standard scheme
  and Windows' own URL dispatch, outside what this project can
  directly instrument or verify without a live Windows/browser
  environment. Rather than find one more special character to work
  around, redesigned the URL format entirely: no query string at all,
  just plain `/`-separated path segments --
  `capture://<relay-host>/<container>/<token>/<relay-port>/<eveng-host>`.
  Every field is guaranteed free of `/` itself (container names are
  docker-safe, `token` is base64url -- no `/` in that alphabet,
  `eveng_host` is an IP/hostname, `relay_port` is numeric), so there's
  no separator ambiguity left for any layer to mishandle. `url.py`'s
  `build_pro_capture_url`/`parse_pro_capture_url` rewritten
  accordingly; `is_community_style_path` unchanged in spirit (still
  checks the first path segment against `vunl*`/`pnet*`) but now
  operates on one segment among several rather than the whole query-less
  path. 17 tests in `test_url.py` rewritten/added, including one
  asserting the URL contains none of `?`, `&`, `;`, or `=` at all.
  The relay's own HTTP endpoint contract (`GET /capture/stream?token=`)
  is unaffected -- that's a separate HTTP request curl constructs
  directly, was never at risk from this issue (only one query field, so
  `&` never came up there), and needed no changes.
- **Fixed the curl-exit-code-through-a-pipe issue flagged (and
  deliberately deferred) during a prior code review.** `%ERRORLEVEL%`
  after `curl | wireshark` reflects Wireshark's own exit code, not
  curl's -- `cmd.exe` has no equivalent to a shell's
  `pipefail`/`PIPESTATUS` for seeing an earlier pipeline stage's exit
  code. Without addressing this, a curl failure (bad token, relay
  unreachable) piped straight into Wireshark could go unnoticed if
  Wireshark itself still exits `0` after being closed normally with
  nothing to show. Fixed with a short, separate preflight request
  before committing to the real (indefinite) stream: `--max-time 3`
  cuts it off regardless of outcome (a successful stream never
  completes on its own), `--fail` makes an actual HTTP error (rejected
  token) fail fast with a distinct code, and curl's own exit code `28`
  (operation timeout) is treated as the *success* signal specifically,
  since it means headers were received and streaming had already
  started when the preflight's short clock ran out. Restructured this
  section of the `.bat` to use flag variables rather than
  `goto`/labels inside a parenthesized `if` block -- a well-known
  `cmd.exe` fragility trap (jumping into or out of a block that's
  already been tokenized as one unit can behave unpredictably) that an
  earlier draft of this same fix had introduced.
- **`list_captures`/`get_capture` confirmed working live.** The earlier
  `docker ps`/`docker exec` sudo and `ProtectHome` fixes, plus the
  restored group-based sudoers, are all confirmed live rather than
  just reasoned through -- `list_captures` now returns real results
  against a live EVE-NG PRO server.
- **The `.bat` companion's `mode=pro` query field broke live, and its
  root cause led to redesigning the whole detection scheme rather than
  patching the symptom.** Confirmed live: the query string ended up
  with `mode` parsed as an empty string despite `get_capture` always
  including `mode=pro` in the URL it builds. Root cause: `&` (used as
  the query-field separator, matching ordinary HTTP convention) is a
  command separator in `cmd.exe`, which is *always* the interpreter
  for a `.bat` file however it's invoked -- an unescaped `&` in the
  argument corrupts everything after it, and Community's own links had
  never hit this before since they never carried a query string at
  all; this project's own multi-field query string was the first
  `capture://` link ever built with `&` in it. Per direct feedback
  (confirmed live: Community's own device names always start `vunl` or
  `pnet`, a second shape beyond the single example seen earlier),
  redesigned mode detection to use the URL's own path pattern instead
  of an invented `mode=` field at all -- `vunl*`/`pnet*` in the path
  position means Community's existing, unmodified flow; anything else
  (this project's own `Capture-<pid>`-style container names) means the
  relay flow. Also switched the query separator itself from `&` to `;`
  (not one of `cmd.exe`'s special characters: `& | < > ^ ( ) % !`) for
  the fields that remain (`token`/`relay_port`/`eveng_host`). New
  `is_community_style_path()` in `url.py` for the path-pattern check;
  `urllib.parse.urlencode` has no option to change its separator from
  `&`, so the query string is now built by hand, and parsed back with
  `parse_qs`'s own `separator=` parameter (a real, standard-library
  option, not project-specific) to match. `.bat` rewritten to match:
  substring-prefix check instead of query parsing for mode detection,
  `;`-based query splitting for the remaining fields, and `pause` added
  on every error path so the window stays open to read the message
  (matching debugging pauses added by hand during live testing) rather
  than flashing closed immediately, which is how the original bug was
  even readable enough to report in the first place. 14 tests in
  `test_url.py` rewritten/added for the new scheme (path-pattern
  matching for both `vunl*` and `pnet*`, confirming `;` not `&` appears
  in the built URL, confirming no `mode=` field exists at all); full
  suite re-run afterwards with zero regressions. The curl-relay path,
  its plink fallback, and the Community-mode command block itself
  (still a reconstruction, not copied from a real file) remain
  unverified live -- see the updated status note at the top of
  `docs/capture-relay.md`.
- **Restored group-based sudoers on the EVE-NG host, per direct
  feedback that this got lost in an earlier consolidation.** The
  v0.3.3-v0.3.5 sequence collapsed a two-account design down to a
  single `mcp-eveng` account for simplicity, but along the way also
  flattened the EVE-NG-host sudoers rule from group-based
  (`%capture_relay`) to username-based (`mcp-eveng` directly) --
  losing the ability to add another account to the same rights later
  without editing sudoers again, which was the specific reason for a
  group in the first place. Restored: `docs/capture-relay.md` step 1
  now creates both the `mcp-eveng` account AND a `capture_relay` group
  (with `mcp-eveng` as its first member), and step 3's sudoers rule
  targets `%capture_relay`, not `mcp-eveng`. This is scoped narrowly to
  the EVE-NG-host side (role 2 in the doc's own terminology) -- the
  *local* accounts running `mcp-eveng.service`/`mcp-relay.service`
  (role 1) are unaffected and still both simply `mcp-eveng`/`mcp-eveng`,
  per the same direct feedback that this part is exactly what was
  wanted.
- **Neither `docker_ps.DOCKER_PS_COMMAND` nor `server._dumpcap_command`
  actually prefixed the command with `sudo`, despite the sudoers rules
  this same project sets up in `docs/capture-relay.md` being written
  for exactly that (`mcp-eveng ALL=(root) NOPASSWD: /usr/bin/docker
  ps ..., /usr/bin/docker exec ...`).** Confirmed live: without `sudo`,
  `docker ps` can't reach the daemon socket and exits non-zero, even
  though the SSH account itself authenticates fine -- this project's
  design deliberately uses scoped sudo rather than `docker` group
  membership (broader, unscoped daemon access) for this account, so
  the commands sent over SSH need to actually say `sudo`. Both
  `list_captures` (via `DOCKER_PS_COMMAND`) and the relay's streaming
  (via `_dumpcap_command`) were affected identically. Fixed by
  prefixing both with `sudo`; 2 new regression tests confirm the
  prefix directly rather than relying on it being implied by
  surrounding assertions. Full suite re-run afterwards with zero
  regressions.
- **`ProtectHome=true` in both systemd units (`mcp-eveng.service` in
  `docs/install-linux.md`, `mcp-relay.service` in
  `docs/capture-relay.md`) makes `/home` completely invisible to the
  service -- not permission-checked, hidden entirely -- which directly
  contradicted this same project's own advice to store the
  capture-relay SSH private key under `/home/mcp-eveng/.ssh/`.**
  Confirmed live: this produced a `[Errno 13] Permission denied`
  reading the key that looked exactly like a file-ownership problem
  (and was reported, reasonably, as one) but wasn't -- verified
  correct ownership/permissions on the key file made no difference,
  and duplicating it under a different filename in the same directory
  reproduced the identical error, which only makes sense if the whole
  directory tree is inaccessible to the service rather than one
  specific file being denied. Changed to `ProtectHome=read-only` in
  both units, which still blocks the service from writing anywhere
  under `/home` but permits reads. Added a forward-reference from
  `docs/capture-relay.md`'s keypair-generation step to this fix, since
  reading the doc in order means generating the key before reaching
  the systemd section that would otherwise silently break reading it.
- **Consolidated capture-relay from a dedicated `mcp-relay`/`capture_relay`
  account+group back to reusing the same `mcp-eveng` account the main
  process already runs as, per direct feedback that the multi-account
  design was still overcomplicating setup.** `docs/capture-relay.md`
  now explicitly names two different *roles* that name covers -- the
  account systemd uses to run `mcp-eveng.service`/`mcp-relay.service`
  locally (no shell/home directory required, since systemd execs the
  process directly and never invokes a shell) vs. the account being
  SSH'd into on the EVE-NG host (which does need a real shell and a
  home directory, since `sshd` invokes the shell to run a command) --
  these can be the literal same Unix account if colocated, or two
  different accounts sharing a name if not, but either way the
  distinction needed to be spelled out since conflating the two is an
  easy way to get confused about which one's requirements apply where.
  Sudoers rule simplified from a group-based rule to a direct
  username-based one, since there's only the one account now.
  Corrected a resulting bug in the docs: the systemd unit's
  `ExecStart` for the relay must run the `mcp-eveng-capture-relay`
  console script, not `mcp-eveng --http` -- both scripts get installed
  into any venv the package is installed into regardless of which one
  you meant to run there, so this is an easy mix-up, and running the
  wrong one starts a second copy of the main tool server instead of
  the actual relay. Clarified the `pip install` pattern for a venv
  belonging to a different (or unprivileged) account: `sudo -u
  <account> /path/to/venv/bin/pip install ...` directly, rather than
  `source .venv/bin/activate` -- activation doesn't reliably carry
  through `sudo -u`. Also clarified there is only ONE source checkout
  regardless of how many venvs/deployments run from it -- every `pip
  install` (for either process) points at the same source path, just
  into different venvs, and `[capture-relay]` needs installing into
  BOTH separately since venvs share nothing with each other.
- **`CAPTURE_SSH_HOST` now defaults to `${EVENG_HOST}`** in
  `.env.example`, via `pydantic-settings`' variable-interpolation
  support (confirmed working directly against the real file, not just
  assumed) -- the docker host this SSHes to reach and the EVE-NG REST
  API host are the same server in the overwhelming majority of setups,
  so asking for a second, easily-out-of-sync IP was redundant. Still
  overridable for the rare case where they genuinely differ.
  `.env.capture-relay.example` has no `EVENG_HOST` of its own to
  interpolate from (documented as such), so it keeps an explicit value
  there.
- **Added a Table of Contents to `docs/install-linux.md`,
  `docs/install-windows.md`, and `docs/capture-relay.md`.**
- **Added blank lines between every individual variable in both
  `.env` example files** (previously only between section headers),
  for easier scanning/editing.
- **The `mcp-relay` service account's shell was set to
  `/usr/sbin/nologin`, which blocks SSH from executing ANY command
  through that account -- not just interactive sessions.** Confirmed
  live: authenticating with the account's key still succeeds (auth and
  shell-invocation are separate steps), but the account then fails
  every actual command with `"This account is currently not
  available"` -- OpenSSH's own message for a `nologin` shell, not a
  permissions problem. This directly broke both `list_captures`'
  `docker ps` and the relay's `docker exec` calls; the account is now
  created with `--shell /bin/bash` (restricting what it can do is
  sudo's job -- see the group-based sudoers rule -- not the shell's).
  Also switched `--no-create-home` to `--create-home`, so the account's
  home directory and `.ssh` folder exist automatically instead of
  needing a manual `mkdir`/`chmod` step.
  **Separately, the setup steps had the keypair generated in the wrong
  place entirely:** `ssh-keygen` was run as the `mcp-relay` account
  *on the EVE-NG host*, putting both halves of the keypair there --
  but the private key needs to live wherever `mcp-eveng`/the relay
  actually run (a different machine from the EVE-NG host in general;
  confirmed a real gap against an actual test setup running the main
  process on Windows while `CAPTURE_SSH_HOST` pointed at a separate
  Linux box). Only the public half belongs on the EVE-NG host. Rewrote
  `docs/capture-relay.md` steps 1-2 to clearly separate "done once, on
  the EVE-NG host" (account/group creation) from "done per machine
  actually running mcp-eveng/the relay" (keypair generation, for both
  Linux and Windows), and added the missing step of appending the
  public key to `mcp-relay`'s own `authorized_keys` on the EVE-NG host
  -- this was never spelled out at all in the previous version of this
  doc. Corrected `.env.example`/`.env.capture-relay.example`'s
  `CAPTURE_SSH_KEY_PATH` example and comments to match (a local path on
  whichever machine that process runs on, not `/home/mcp-relay/...`
  which only makes sense on the EVE-NG host itself) and corrected an
  overclaim in this same `[Unreleased]` section's own prior entry below
  (`_KEY_PATH` isn't necessarily identical between the two `.env`
  files, only `_HOST`/`_PORT`/`_USERNAME` are). All references to step
  numbers elsewhere in the doc/env files updated for the doc going from
  6 steps to 7.
- **Simplified capture-relay's SSH account model from two dedicated
  accounts to one, with sudo access granted by group rather than by
  username.** The original design used two separately-scoped accounts
  (`mcp-eveng-capture-list` for read-only `docker ps`,
  `mcp-eveng-capture-relay` for `docker exec ... dumpcap`) on the theory
  that each process should only ever hold the privilege it actually
  uses. In practice this added setup complexity (two accounts, two
  keypairs, two sudoers lines) without a correspondingly large security
  benefit, since both accounts still only ever reach the same two
  fixed, narrow docker subcommand shapes -- there was no meaningfully
  different blast radius between them. Replaced with a single account
  (`mcp-relay`) and a single group (`capture_relay`); the sudoers rule
  grants both commands to `%capture_relay` rather than to individual
  usernames, so `list_captures`/`get_capture` (in the main `mcp-eveng`
  process) and the relay now authenticate identically -- adding another
  process or account that needs the same rights later is just adding it
  to the group, not editing sudoers again. `docs/capture-relay.md`
  steps 1-2 and the systemd unit's `User=`/`Group=` fields rewritten
  accordingly; `.env.example` and `.env.capture-relay.example` now show
  identical `CAPTURE_SSH_HOST`/`_PORT`/`_USERNAME` values (previously
  deliberately different, per account) -- `_KEY_PATH` was also wrongly
  shown as identical in this entry's first version; see the next
  `### Fixed` entry above for the correction.
- **Replaced the real EVE-NG PRO server IP address (`172.16.130.14`,
  leaked into the capture-relay docs/env-examples from earlier live
  testing sessions) with `192.168.1.50`** -- the same placeholder
  `install-linux.md` already uses for its own `EVENG_HOST` example, for
  consistency across the project's docs rather than each doc inventing
  its own example IP.
- **`import asyncssh` at `ssh_client.py`'s module top level meant the
  entire `mcp-eveng` server crashed at startup for anyone without the
  optional `capture-relay` extra installed -- not just people using
  `list_captures`/`get_capture`.** Confirmed live during initial testing
  of the capture-relay feature (introduced earlier in this same
  `[Unreleased]` section -- see the `### Added` entry below): `server.py`
  unconditionally imports every tools module including `capture`
  regardless of whether its tools are even enabled, and `capture.py`
  imports `ssh_client.py`, which did `import asyncssh` at the top of the
  file. A plain `pip install -e .` (the documented base install --
  `capture-relay` is an opt-in extra) meant `asyncssh` genuinely wasn't
  present, and the whole server failed with a `ModuleNotFoundError`
  traceback before any tool, enabled or not, could even be considered.
  Fixed by moving the `import asyncssh` into `run_command`/
  `streaming_process` themselves (lazy import) -- the module, and by
  extension the whole server, now imports fine without it; only actually
  *calling* `list_captures`/`get_capture` needs it installed. Added a new
  `ssh_client.is_available()` check, called by both tools before any SSH
  work, so a genuinely missing dependency now gives a clear, actionable
  error message instead of a raw traceback. Verified: reproduced the
  exact failure in a fresh venv with the base install only (confirmed
  `asyncssh` absent, confirmed `create_server()` and the literal
  `python -m mcp_eveng --http` command both failed before the fix and
  succeed after), then added 2 new tests using `sys.modules` manipulation
  to simulate `asyncssh` genuinely missing (one for `server.py`'s own
  import chain, one for `ssh_client.py` directly) plus 3 new tests for
  the friendly-error-message behavior in `tools/capture.py`. Full suite
  re-run afterwards with zero regressions.
- **`set_link_quality` no longer requires the far side's current
  quality values to be supplied explicitly.** Previously, changing
  quality on one side of a node-to-node connection required
  `far_delay`/`far_jitter`/`far_loss`/`far_bandwidth` all four, since no
  read path for current values had been found and the underlying API
  always overwrites both sides' complete state in one request --
  omitting them risked silently resetting the far side to 0. That gap
  is now closed: confirmed live (PRO server) that `get_lab_topology`'s
  response -- the same call this tool already makes to resolve the
  connection -- includes `source_delay`/`source_jitter`/`source_loss`/
  `source_bandwidth` and the `destination_*` equivalents on every
  connection entry. The far side's current values are now read directly
  from that entry and reused automatically; `far_delay` etc. are optional
  overrides, not required inputs -- supplying one changes just that
  value, leaving the rest untouched. Not confirmed whether this holds on
  every PRO version, only the one live server tested, but no
  new call is needed to use it either way. Verified: two new tests
  (reading current far-side values when omitted, and a partial override
  leaving the untouched far-side fields at their current values, not 0)
  plus the two existing tests that always supplied all four far values
  explicitly -- confirming explicit values still work identically.
  Replaced the now-obsolete "requires all four far values" test. Full
  suite re-run afterwards with zero regressions.
- **`edit_lab_node`/`change_node_delay`: a `delay`-only edit was silently
  rejected on EVE-NG Community, surfacing as a generic "Cannot edit node
  in the selected lab (20026)" error.** Confirmed live against a
  Community server, then traced to a genuine bug in EVE-NG Community's
  own backend (`Node::edit()` in the underlying `unetlab` source): every
  editable field flips an internal "modified" flag when changed --
  `config`/`icon`/`image`/`left`/`name`/`top` -- except `delay`, whose
  branch updates the value but never sets the flag. If `delay` is the
  only field in the request, EVE-NG ends up thinking nothing changed and
  rejects the whole edit with its own "no attribute has been changed"
  error, which the outer API layer masks as the generic 20026 message.
  Not something PRO was observed to hit. New `_with_delay_workaround`
  helper: whenever `delay` is present and no other field already
  guarantees the flag gets set, the node's own current `name` is resent
  alongside it (a value-blind field on EVE-NG's side -- it sets the flag
  regardless of whether the resent value actually differs). Applied only
  to the outgoing API payload, not to `edit_lab_node`'s reported
  "changed" message, so it stays transparent to callers. Verified
  directly: extracted and ran the real helper against five realistic
  field combinations (delay-only, delay+explicit-name,
  delay+already-flag-setting-field, no-delay, delay+ethernet) before
  relying on it, then re-ran the full `test_nodes.py` suite -- updated
  the four existing `change_node_delay` tests whose assertions encoded
  the old (buggy) call shape, and added five new tests covering the
  helper directly and the message/API-call separation in
  `edit_lab_node`.
- **`connect_interface` no longer silently overwrites an already-connected
  interface when given an explicit index.** Reported live: a
  smaller/weaker model was observed connecting interfaces it hadn't been
  told to, sometimes leaving an interface disconnected entirely. Traced
  to the explicit-index resolution path specifically -- unlike the
  search/omitted paths (which are scoped to available interfaces only,
  by construction, and so were never affected), an explicit index was
  used directly regardless of whether it was already connected to
  something, silently rewiring (and thereby disconnecting) it. New
  `confirm` parameter and `_connected_network_description` helper: if an
  explicit index (source or target) resolves to an already-connected
  interface, this now returns `status: "confirmation_required"` naming
  the interface and what it's connected to, rather than proceeding --
  `confirm=true` rewires it anyway. Checked before anything else with
  side effects (target network resolution, edition check, stopping any
  node), same discipline as an interface-resolution error. Verified
  directly -- not just hand-traced -- by extracting the actual resolver
  and new helper functions from the real module and running them against
  realistic connected/free/search/omitted scenarios before this was
  committed. New tests cover explicit-index-connected (blocks),
  explicit-index-connected-with-confirm (proceeds), explicit-index-free
  (never blocked), the same check on the target node in node-to-node
  mode, and confirming the search path genuinely cannot reach this case
  at all.

### Documentation
- **Split the confusing single `.env` story for capture-relay into two
  clearly separate example files** -- `.env.example` (main `mcp-eveng`
  process) now includes its own `CAPTURE_*` section for
  `list_captures`/`get_capture`, and a new `.env.capture-relay.example`
  covers the standalone relay's own, separate `.env`. Previously
  `docs/capture-relay.md` showed both processes' variables mixed into
  one code block with prose explaining the split after the fact --
  confirmed confusing in practice. Both files now cross-reference each
  other and are heavily commented on which variables are shared by
  name but need different *values* (`CAPTURE_SSH_*`, pointed at two
  different, separately-scoped SSH accounts; `CAPTURE_TOKEN_SECRET`,
  which must be identical) versus which look similar but aren't
  (`CAPTURE_RELAY_LISTEN_*`, the relay's bind address, vs.
  `CAPTURE_RELAY_ADVERTISE_*`, read only by the main process to build
  `capture://` URLs) versus which belong to only one file at all
  (`EVENG_*`/`MCP_*` never belong in the relay's `.env`;
  `CAPTURE_TOKEN_TTL_SECONDS`/`CAPTURE_SSH_TIMEOUT_SECONDS` are read
  only by `list_captures`/`get_capture`, never by the relay, even
  though nothing stops them being set there).

### Added
- **`list_captures`/`get_capture`: new PRO-only tools, plus a
  standalone `mcp-eveng-capture-relay` systemd service and a Windows
  `.bat` companion, for streaming an EVE-NG PRO Wireshark capture to a
  local Wireshark without a personal SSH+sudo account on the EVE-NG
  host.** Confirmed live that capturing can't be automated end-to-end --
  each capture container's lifetime is tied to a heartbeat from the
  browser tab that started it (refreshing the page kills captures off
  one by one, on each one's own staggered idle timer, not all at once),
  so the person still starts captures from the GUI same as today. Also
  confirmed live that a container's name (`Capture-nnnnnnn`) is PID-like,
  not derived from node id or interface, so there's no automatic
  node/interface -> container correlation -- `list_captures` shows
  what's running (container, age, status, oldest-first) for a person to
  recognize by when they started it, and `get_capture` mints a one-time
  `capture://` URL from a position in that list (or an exact container
  name/id).
  New `capture_relay` package: `tokens.py` (self-contained, HMAC-signed
  tokens -- the main process and the relay run as fully independent
  systemd services with no shared runtime state, so a token has to be
  verifiable without either process calling the other or consulting
  shared storage), `docker_ps.py` (parses a machine-readable `docker ps
  --format` request rather than the human table, filtered by
  `ancestor=eve-wireshark`), `config.py` (SSH identity shared by both
  processes; separate listen vs. advertise address for the relay, since
  a bind address like `0.0.0.0` is meaningless as something a client
  connects *to*), `ssh_client.py` (thin `asyncssh` wrapper), `url.py`
  (builds/parses the `mode=pro` `capture://` URL -- deliberately
  distinct from Community's own unmodified `capture://` link shape,
  which carries no `mode` at all and needs no MCP involvement), and
  `server.py` (the relay itself -- Starlette, already a transitive
  dependency via `mcp[cli]`'s own `--http` transport, so no new
  framework). New `asyncssh`/`starlette`/`uvicorn` optional dependencies
  (`capture-relay` extra), new `mcp-eveng-capture-relay` console script.
  New `docs/capture-relay.md` (SSH/sudoers setup for two
  separately-scoped service accounts, the systemd unit, every env var)
  and `scripts/eve-capture.bat` (the Windows companion registered
  against `capture://`, dispatching Community's existing behavior
  unmodified vs. this project's new curl-relay-primary/plink-fallback
  PRO path).
  **Status: 59 new tests, all passing (tokens, docker ps parsing, config,
  URL building, the relay's token/streaming/disconnect logic against a
  fake SSH process, and the MCP tools against a fake SSH runner) -- but
  the actual `asyncssh` connections and the `.bat` file itself are
  unverified against any live EVE-NG server or Windows machine.**
  Developed on its own branch (`feature/capture-relay`); shipped
  disabled by default in both `tools.env.*.example` files even on PRO,
  since it depends on infrastructure (the SSH accounts, the relay
  service) that doesn't exist until deliberately set up.
- **`set_link_quality`: new PRO-only tool for per-connection
  link quality (delay/jitter/packet loss/bandwidth), set independently on
  each side of a connection.** No Community equivalent exists at all
  (confirmed directly by a user: no GUI option there), and unlike this
  project's other PRO/Community differences, there's no open-source
  Community-side code to cross-check against either -- this feature is
  PRO-exclusive from the ground up. There's no documented
  public API for it: EVE-NG's own API docs don't cover it, and PRO's
  backend is closed-source. The request shape (`PUT /labs/{lab}/quality`)
  was captured live from a real PRO server's own GUI network traffic --
  four separate captures, two on a plain node-to-node link and two on a
  node-to-network link -- not inferred or guessed. Confirmed from those
  captures: a side attached to a network of *any* kind (not just a
  literal bridge) can't have its quality set at all -- EVE-NG forces it
  to 0 regardless of what's requested, generalizing the original
  "bridges only" suspicion. Also confirmed: `save: 0` applies live
  without persisting (the GUI's "Apply"), `save: 1` does both (the GUI's
  "Save"). One confirmed gap, handled deliberately rather than papered
  over: there's no known way to read a connection's *current* quality
  values anywhere in the API (`get_lab_topology`/`get_node_interfaces`/
  `list_lab_nodes` were all checked live and none return it), and the
  endpoint always overwrites both sides' complete state in one request --
  so this tool requires the far side's current values to be supplied
  explicitly whenever that side is another node, rather than risk
  silently resetting them to 0. Verified: payload construction tested
  directly against the real captured requests byte-for-byte (node-to-node
  and node-to-network cases), plus edge cases (missing far-side values,
  an unconnected interface, an unknown interface name) -- 8 new tests in
  `tests/tools/test_quality.py`. Full test suite re-run afterwards with
  zero regressions (confirmed identical to the pre-existing failure list
  in the unmodified project).

### Documentation
- **README**: added a doc link and PRO/Community bullet for the new
  capture-relay feature (see the `### Added` entry above); also fixed
  two things noticed stale while in there -- the "Three tools genuinely
  behave differently by edition" count (already wrong before this
  session; four were listed, now five with capture-relay added) and
  `set_link_quality`'s own bullet, which still described the "far side
  values must be supplied explicitly" limitation that was actually
  fixed earlier in this same `[Unreleased]` section (see the `### Fixed`
  entry above) but never reflected in the README's own description.
- Corrected false PyPI-install framing in the README and Linux/Windows
  install guides -- this project is not published on PyPI, but
  `docs/install-linux.md`'s "Install" section (and the main README's)
  presented `pip install mcp-eveng` as the primary/first install method,
  which doesn't currently work at all. Both now lead with the actual
  working method (`git clone` + `pip install -e .`), with the PyPI
  command's absence explained rather than silently dropped.
- New "Running as a systemd service (Linux)" section in
  `docs/install-linux.md`, covering a confirmed working end-to-end
  install into `/opt/mcp_eveng`: the `python3.13-venv` prerequisite,
  cloning, copying the correct `tools.env.pro.example`/
  `tools.env.comm.example` for your edition, creating the venv and a
  dedicated non-root `mcp-eveng` service account, the full systemd unit
  file, and enabling/verifying the service. `docs/install-windows.md`
  has the identical stale PyPI-install framing this same fix addressed
  on Linux -- not yet corrected there.

### Changed
- **`delete_lab` is now disabled by default**, added to
  `tool_config.py`'s `_DEFAULT_DISABLED` alongside the six
  user-management tools -- deleting an entire lab is a more severe,
  harder-to-recover-from action than deleting one thing inside it, unlike
  `delete_folder`/`delete_lab_node`/`delete_lab_network`, all still
  enabled by default. Updated in both `tools.env.pro.example` and
  `tools.env.comm.example` (explicitly listed as `disabled` in both,
  matching how the user-management tools are already documented there,
  rather than just relying on the hardcoded default) -- confirmed this
  doesn't disturb the two files' full parity (still differing only in
  `export_node`/`share_lab`) by running the comparison directly against
  both real files. Also updated: the README's "Controlling which tools
  are exposed" and "Available tools" table, `docs/tools-reference.md`'s
  "Deleting things requires confirmation" section, and the test suite
  (`test_tool_config.py`, `test_server.py`'s `DISABLED_BY_DEFAULT_TOOLS`)
  -- checked every other test referencing `delete_lab` first to confirm
  none of them assumed its old enabled-by-default status (the ones in
  `test_labs.py` and `test_meta.py` test the underlying function/a fully
  mocked tool list directly, independent of `tool_config`, so needed no
  changes).
- **Reverted `tools.env.comm.example` back to full parity with
  `tools.env.pro.example` — same tools listed in both, differing only in
  values, not which tools are even mentioned.** A previous version of
  this file omitted the six user-management tools entirely on the
  assumption user administration wasn't supported on Community at all.
  That assumption was wrong, corrected via direct manual testing against
  a real Community server: adding a second admin user worked normally,
  as did adding a folder and moving a lab into it. Both files now list
  all 43 tools identically, disabling the same six user-management tools
  by default on both editions for the same general reason (not exposing
  user administration to an LLM by default) -- Community's file differs
  from PRO's *only* in `export_node`/`share_lab`, both explicitly
  `disabled`, since neither can be safely omitted the way a
  `_DEFAULT_DISABLED` tool can (omitting a normally-enabled tool's line
  makes it enabled by default, the opposite of intended). Also added,
  confirmed directly rather than from official docs: Community has no
  per-lab sharing concept at all -- every lab is shared by default,
  which is *why* `share_lab` silently has no effect there rather than
  erroring outright. Test suite rewritten again to match -- checks raw
  file content directly (not just the processed status dict, which
  can't distinguish "listed as disabled" from "never mentioned") for
  both full-parity and the two intentional exceptions, verified by
  running every assertion directly against the real shipped files before
  this was committed.
- **`tools.env.comm.example` redesigned to only list tools actually
  usable on Community**, not every tool with unusable ones marked
  disabled. The six user-management tools (`list_users`, `get_user`,
  `add_user`, `edit_user`, `delete_user`, `list_user_roles`) are now
  omitted entirely -- per direct guidance that user management isn't
  supported on Community at all -- rather than listed as `disabled`;
  safe to omit specifically because they're hardcoded disabled-by-default
  in `tool_config.py`'s `_DEFAULT_DISABLED` regardless of whether the
  file mentions them. `export_node`/`share_lab` remain the one exception,
  still explicitly listed as `disabled`: neither is in
  `_DEFAULT_DISABLED`, so omitting their lines would make them *enabled*
  by default instead -- documented clearly in the file's own header so
  this isn't a mystery later. Verified against the real files, not
  assumed: raw `dotenv_values()` output checked directly (not just the
  processed status dict, which always merges in `_DEFAULT_DISABLED`'s
  keys and so can't distinguish "omitted" from "explicitly disabled") to
  confirm the six lines are genuinely absent, and a full
  `make_enabled_predicate` run across all 43 tools confirmed exactly the
  intended 8 end up disabled. Test suite rewritten to match -- the old
  `pro.keys() == comm.keys()` comparison no longer holds (and, it turns
  out, never actually tested what it appeared to either way, for the
  same reason above) -- replaced with tests reading raw file content
  directly plus one full functional end-to-end check.
- **`tools.env.example` split into `tools.env.pro.example` (PRO)
  and `tools.env.comm.example` (Community).** The two are identical
  except `export_node`/`share_lab` are disabled in the Community file --
  both are PRO-only features (see "PRO vs Community
  differences"), so there's nothing they can actually do there. The old
  single `tools.env.example` (effectively already the PRO version, since
  it had both tools enabled) is removed, not kept as a third file.
  Verified live: `dotenv_values` correctly strips the inline `#` comment
  on each disabled line before this was shipped, not assumed. New
  regression tests load the two *actual* shipped files (not hand-copied
  strings) and confirm they differ by exactly those two tools and
  nothing else -- run directly against both files as a sanity check
  before this was committed, not just left to the test suite. Every
  reference to the old filename updated across `tool_config.py`'s module
  docstring and the README (`tools.env.example` in `CHANGELOG.md`'s own
  historical entries deliberately left alone -- they describe what was
  true at the time).
- **`connect_interface` no longer auto-picks the first available
  interface by default.** `interface`/`target_interface` now accept a
  case-insensitive *substring* search against the node's available
  (unconnected) ethernet interface names, or an explicit index; if
  omitted, or if the search matches more than one available interface,
  this returns `status: "selection_required"` with a numbered list
  instead of guessing -- new `interface_selection`/
  `target_interface_selection` parameters resolve the choice on a
  follow-up call, same search -> select pattern used everywhere else in
  this project. With only one available interface, no prompt is needed
  either way, since there's no actual choice to make. Replaced
  `_first_available_ethernet_index`/`_resolve_interface_index` with
  `_available_ethernet_interfaces`/`_resolve_interface_selection`. Every
  higher-level `connect_interface` test was checked by hand (and
  scripted) against the new logic; only one needed changing (a rename --
  its scenario had exactly one available interface per node, still
  unambiguous under the new rules) plus two new true end-to-end tests
  for the actual `selection_required` path and resolving it by number.

### Added
- **`export_node` and `share_lab` are now edition-gated**, checking the
  server's edition (via `get_status`) before doing anything and
  returning a clear error immediately on Community, instead of the
  generic `"Request not valid"`/`"Lab has not been modified"` EVE-NG
  itself gives no useful detail on. Confirmed against EVE-NG's own
  official features-compare page: both are listed there as separate
  toggleable PRO features ("Export/Import configs...", "Shared
  Lab"/"Shared Project"), directly explaining the unconditional live
  failures found while testing against a real Community server.
- New `edition.py` module: extracted the previously-private
  `_is_pro_edition` helper (only used inside `connect_interface`) into a
  shared, documented `is_pro_edition()` -- now the single source of
  truth for all three edition-gated tools, with the confirmed reasoning
  for each written into its module docstring. `connect_interface`'s
  existing edition-aware behavior (PRO allows wiring running nodes;
  Community requires stopping first) is unchanged, just now built on the
  shared helper instead of a private one.
- New README "PRO vs Community differences" section, consolidating all
  three edition-aware tools in one place rather than scattering the
  explanation across each tool's own docs.

### Documentation
- Trimmed the README "Known issues" section down to just the core
  symptom statement -- the extensive supporting detail (what's been
  ruled out, what's untried, log evidence) was too much for that section
  and has been removed rather than relocated; the git history retains it
  if it's ever needed again.
- Added a table of contents at the top of the README, covering every `##`
  through `####` heading. Every anchor link verified against GitHub's own
  slug algorithm (lowercase, strip punctuation except `-`/`_`, spaces to
  hyphens, no collapsing of resulting repeated hyphens) rather than
  assumed correct by eye -- the trickiest one, "MCP network settings
  (only used with `--sse` or `--http`)", resolves to three consecutive
  hyphens twice (`...with---sse-or---http`) from the literal `--` in the
  heading text combined with the space-to-hyphen conversion.
- README "Available tools" section: merged the area-summary table and
  the per-tool description table into a single `Area | Tool |
  Description` table, one row per tool (43 total), area shown only once
  per group of consecutive same-area rows rather than repeated or
  tracked via footnote markers. The `†`/`*` footnote system is gone --
  "Disabled by default" and "Requires user confirmation before it does
  anything" are now stated directly in each affected tool's own
  description text instead.
- New README "Known issues" section: `stop_node` (and anything requiring
  a node to be stopped first) can persistently fail on certain nodes with
  `"Request not valid (60027)."`, with no fix found yet despite extensive
  live investigation -- ruled out: session/auth, node history, resource
  exhaustion, all three `EVENG_HTML5` modes, `unl_wrapper -a
  fixpermissions`. Confirmed the request never reaches EVE-NG's own stop
  wrapper script at all (nothing logged to `unl_wrapper.txt`), while the
  request itself matches EVE-NG's official API docs exactly. Untried:
  `unl_wrapper -a restoredb`, a raw `curl` comparison, and a GUI-vs-API
  test against the same stuck node.

### Changed
- **README restructured**: moved detailed per-tool design notes and the
  full "Deleting things requires confirmation" section out to a new
  `docs/tools-reference.md`, replaced with a brief one-line description
  per tool in the README itself plus a pointer to the new document.
  "Controlling which tools are exposed" and everything from "Project
  layout" onward stayed in place, unmoved.
- **`telnet_node` is now enabled by default**, like every other tool in
  this project, rather than requiring explicit opt-in. Removed from
  `tool_config.py`'s `_DEFAULT_DISABLED`; still fully documented as a
  materially different risk profile (arbitrary CLI commands to a live
  device, no command-safety filtering) worth disabling explicitly if
  you'd rather it be opt-in.
- **EVE-NG connection defaults changed to match Pro's common deployment**:
  `EVENG_PORT` 80→443, `EVENG_PROTOCOL` http→https, `EVENG_VERIFY_SSL`
  true→false (EVE-NG, especially Pro, commonly uses a self-signed HTTPS
  certificate). Updated in `config.py`, `.env.example`, and the README.
- **`MCP_ALLOWED_HOSTS` now defaults to `"localhost:*"`** instead of
  empty, matching the default loopback `MCP_HOST` out of the box.
  Documented trade-off: a non-loopback `MCP_HOST` with no explicit
  `MCP_ALLOWED_HOSTS` no longer fails fast at startup the way it used to
  -- it starts, then rejects every request at runtime with a Host-header
  mismatch instead, a harder failure to debug. New test locks in this
  behavior explicitly (`test_create_server_non_loopback_host_uses_default_allowed_hosts_without_rejecting`);
  the old startup-rejection test now opts out via `allowed_hosts=""`
  to keep exercising that path.
- Removed the `EVENG_HOST` scheme-rejection paragraph from the README
  (the validation itself is unchanged, just no longer separately called
  out in prose there).
- Removed the "Recursive lab search" bullet from the README's Features
  list (`list_labs`'s behavior is still fully documented under "Available
  tools" / `docs/tools-reference.md`, just not called out as a headline
  feature).
- Installation instructions changed from `pip install mcp-eveng` to
  `pip install -e .` (editable local install).
- Fixed the MIT LICENSE's placeholder copyright holder ("Your Name") to
  the project name. `pyproject.toml`'s `[project.authors]` had the same
  placeholder (`"Your Name" <you@example.com>`) — fixed to match.

### Added
- **`add_lab_network`'s `network_type` accepts `"cloud"`/`"cloud0"`
  through `"cloud9"` (case-insensitive) as aliases for `"pnet0"` through
  `"pnet9"`.** Confirmed against EVE-NG's own official documentation
  (Community Cookbook) and multiple independent technical writeups: what
  the GUI displays as `Cloud0`-`Cloud9` is always just `pnetN` at the API
  level, and EVE-NG creates exactly 10 of these during installation -- a
  fixed architectural limit (one per physical/virtual host NIC), not
  something that scales further. `"cloud10"` and beyond are deliberately
  not recognized and fall through as literal (invalid) type strings
  rather than silently resolving to something. New `_CLOUD_ALIASES` in
  `tools/networks.py`.

- **`edit_lab_node` now covers every field EVE-NG's own "Edit Node"
  dialog exposes**, not just the original small set. Added: `image`,
  `cpulimit`, `delay`, `disable_offload`, `sat`, `eth_format`, `eth_name`,
  `firstmac`, `qemu_version`, `qemu_arch`, `qemu_nic`, `qemu_options`,
  `rdp_user`, `rdp_password`. Deliberately excludes `uuid` -- an identity
  field EVE-NG assigns itself, not something meant to be user-edited. No
  client change needed (`EvengClient.edit_lab_node` already accepted
  arbitrary fields via `**fields`); purely additive at the tool layer, so
  every existing call site is unaffected.
- **`edit_lab_nodes_by_template` gained a bulk `image` component** --
  updating a shared image/firmware version across every node using a
  given template in one call, the specific capability requested. Images
  are template-scoped (not a global catalog like icons), so
  `component="image"` searches *the resolved template's own* valid image
  list (via a new `_search_template_images`, reusing `get_node_template`,
  the same source `add_lab_node` resolves images from) rather than
  everything on the server. Same search/narrow pattern as `icon`:
  `image_search` narrows to one match or lists candidates numbered,
  `image_selection` resolves ambiguity by number or exact filename.

- **`list_labs` gained a `search` parameter**: case-insensitive substring
  match against each lab's path or file name, reusing the same
  `_lab_matches` helper `delete_lab`/`open_lab` already use for
  consistency. Empty (the default) matches everything, same as before --
  fully backward compatible, no existing call sites need to change.

- **`share_lab(lab_path, ...)`**: new tool for adding users to a lab's
  `shared` list, via `edit_lab` (which already accepted arbitrary fields
  through `**fields` -- no client change needed). `search` is a
  case-insensitive substring against every username from `list_users`
  (called internally regardless of whether the standalone `list_users`
  tool is itself enabled -- tool_config's enabled/disabled gating only
  covers MCP tool registration, not internal client calls); empty matches
  everyone, `"all"` bypasses searching/selecting entirely. No matches
  cancels; over 20 matches asks for a narrower search instead of dumping
  an unwieldy list; exactly one match auto-proceeds; more than one (up to
  20) is shown numbered with an `"all"` option (every *matched* user).
  Reads the lab's current `shared` list first and adds to it -- never
  replaces it, so sharing with one more person can't silently revoke
  everyone else's access. Final confirmation before applying, "accept" or
  "yes" required, same wording as every delete tool. New
  `_list_usernames`, `_current_shared_users` in `tools/labs.py`.

- **`change_node_delay(lab_path, ...)`**: new tool for changing a node's
  startup delay, single node or in bulk. `node_id` (single-node mode)
  always overrides `bulk`, regardless of the `bulk` flag's value. Bulk
  mode requires either `names` (case-insensitive substring match against
  node names, incrementing delay applied in the order names were given,
  a node matching multiple given names only assigned once) or, if `names`
  is omitted, lists every node with its current delay and asks for
  `order` -- the numbers in the desired sequence, partial subsets
  allowed. Every mode -- including single-node, which the original
  request didn't explicitly ask to gate this way -- ends in one explicit
  confirmation (old delay -> new delay per node, stop-warning, "accept"
  or "yes" required) before anything is stopped or changed, for
  consistency with `edit_lab_nodes_by_template`'s existing pattern rather
  than only gating the bulk-with-no-names path. New
  `_search_nodes_by_name`, `_delay_node_label` in `tools/nodes.py`; reuses
  `EvengClient.edit_lab_node`'s existing generic-field PUT (already
  supported arbitrary fields including `delay`, no client change needed).

- **`telnet_node(lab_path, node_id, commands, ...)`**: sends live CLI
  commands to a running node's console over telnet -- fundamentally
  different from every other tool in this project, which manage EVE-NG's
  own REST API for lab-topology metadata. This opens a raw TCP connection
  directly to the host:port EVE-NG reports for a node's console
  (`list_lab_nodes`' own `url` field); there's no REST endpoint for
  "configure a running device's CLI", the console connection is the only
  way. Requires the node to already be running with a telnet console.
  Commands are sent one at a time, each only after the previous one's
  output settles (`wait_seconds`, default 2s), since prompt changes (e.g.
  entering config mode) can't be raced ahead of blind. Returns the full
  session transcript. New `src/mcp_eveng/telnet.py`: a raw-`asyncio`
  telnet client (`telnet_session`, `_process_telnet_bytes`,
  `_read_until_idle`) built from scratch rather than on `telnetlib` --
  deprecated in Python 3.11, removed in 3.13, so new code can't depend on
  it. Handles IAC (Interpret As Command) option negotiation by refusing
  every option offered (`WONT`/`DONT` to everything), keeping the session
  plain text; retries the initial connection a few times since a
  freshly-started node's console server may not be listening immediately.
  Sends whatever `commands` says verbatim with no vendor-aware
  command-safety filtering -- given that risk profile, **disabled by
  default** (added to `tool_config.py`'s `_DEFAULT_DISABLED`, alongside
  the user-management tools), unlike every other tool added so far.

### Fixed
- **Node-template no-image detection now works on Community edition, not
  just PRO.** Confirmed live against a real Community server: it marks a
  template with no image installed by suffixing its description with
  `.missing`, not PRO's `.hided` -- `list_node_templates`'s filter
  (default: only templates with an image) only recognized `.hided`, so
  on Community it was effectively filtering nothing, reporting nearly
  the entire ~180-template catalog as usable regardless of whether an
  image was actually installed. `vendor.py`'s `_HIDDEN_SUFFIXES` now
  recognizes both suffixes; `has_image`/`strip_hidden_marker` updated to
  match. New tests for the `.missing` case, including a spot-check
  against real Community catalog samples.
- **`get_node_template`'s `has_image` is now computed the same way
  `list_node_templates` computes it** (from the description's no-image
  suffix), instead of from whether `options.image.list` is non-empty.
  Confirmed live those two signals disagree for a template with no
  "image" option at all -- e.g. VPCS, a simulator built into EVE-NG
  itself, not a separately-installed binary: its description carries no
  suffix (genuinely usable, confirmed via a live `add_lab_node` that
  succeeded immediately), but `options` has no "image" key to inspect at
  all, so the old options-based check reported `has_image: false` for a
  template that was actually perfectly usable. Using the same signal as
  `list_node_templates` also guarantees the two tools always agree on
  the same template, which they previously didn't for VPCS specifically.
- **`EvengClient`'s auto-relogin now covers `400` in addition to `401`,
  trusting the HTTP status code alone rather than the response body.**
  This took two rounds to get right, similar to earlier fixes in this
  project. First round: confirmed against EVE-NG's own official
  documentation that "unauthorized" covers both a bare 401 and 400 with
  JSend `status: "unauthorized"` -- including a session invalidated by
  the same account logging in elsewhere, since EVE-NG only allows one
  active session per user ("the second login disables the first"). That
  round only matched a literal `status: "unauthorized"` in the response
  body. It wasn't sufficient -- confirmed live via a timestamped EVE-NG
  server audit log (`api.txt`) showing a real `stop` request failing
  with `400` in the exact same second as a second login to the same
  account, yet the response body was a *generic* `"fail"` status with
  EVE-NG's generic `"Request not valid"` message, not self-identifying
  as an auth problem at all -- contradicting how the documentation
  describes it, and explaining why the first round's body-content check
  missed it. Second round: retry once, transparently, on any `400` or
  `401` response, full stop, regardless of body content. Accepted
  trade-off: a genuine non-auth `400` (e.g. an invalid template name)
  also gets one wasted relogin-retry now, reproducing the identical
  final error either way -- a better trade than silently missing real
  session invalidation, which is now confirmed to actually happen in
  this exact shared-account workflow, not just a documented possibility.
- **`start_node`/`stop_node`, when `node_id` is omitted, now loop
  through every node individually instead of using EVE-NG's bulk "all
  nodes" endpoint.** Confirmed live on a PRO server: the bulk endpoint is
  unreliable -- bulk `stop_node()` returned a genuine `500 Internal
  Server Error`, and bulk `start_node()` reported success while one node
  silently never started. Independently confirmed not specific to this
  server: a working reference implementation (`evengsdk`) deliberately
  avoids the bulk endpoint on PRO edition too, looping per-node instead
  (only Community edition uses it there, per that library's own source).
  New `_all_node_ids_and_names`, `_loop_node_action` in `tools/nodes.py`
  -- aggregates per-node results (which succeeded, which failed and why)
  rather than a single pass/fail for the whole batch, and one node's
  failure no longer blocks every other node from being attempted.
- **`connect_interface`'s node-to-node bridges now actually render as a
  direct line between the two nodes** -- confirmed live this previously
  didn't work: no cable rendered at all, and unhiding the bridge manually
  showed two separate cable segments to a visible network icon rather
  than one line between the nodes. Root-caused against a real working
  reference implementation (a community EVE-NG SDK's own
  `connect_node_to_node`): rendering as a direct line is not something set
  when the network is created. The correct, now-implemented sequence is:
  create the bridge (visible, default settings), wire both nodes'
  interfaces to it, then set the network's own `visibility` field to `0`
  via a separate follow-up call. The previous approach (setting `hideme=1`
  at creation time) was the actual cause of the no-cable-at-all symptom.
  New `EvengClient.edit_lab_network` (PUT, same partial-update pattern as
  `edit_lab`/`edit_lab_node`) and a new `edit_lab_network` tool exposing it
  directly, not just used internally by `connect_interface`.

### Added
- **`add_lab_network` prompts for `network_type` with a list instead of
  requiring you to already know a valid value.** If omitted, fetches the
  current list via `list_network_types` and returns it (status
  `"selection_required"`); reply with the exact name, or its number from
  that list.
- **`edit_lab_node` duplicate-name detection.** Changing `name` to one
  already used by another node in the lab no longer silently renames it
  -- returns `status: "confirmation_required"` naming the conflict; call
  again with a different `name`, or the same one plus
  `confirm_duplicate_name=true` to allow the duplicate (EVE-NG itself
  allows duplicate node names, this is just an opt-in guard against doing
  it by accident). New `_find_duplicate_name`.
- **`edit_lab_nodes_by_template(lab_path, vendor=..., template=..., ...)`**:
  redesigned bulk editor -- always scoped to exactly one template per call
  (previously allowed selecting several templates at once via a single
  `selection`). Search inputs split into separate `vendor`/`template`
  parameters (case-insensitive substring, AND'd together if both given,
  at least one required); more than one template matching prompts to
  narrow further (a more specific vendor/template, or `template_selection`)
  rather than picking several. New explicit node-selection stage after the
  template resolves -- `node_selection`: `"all"` or number(s)/exact
  name(s) (`"all"` *is* allowed here, unlike template resolution). New
  `component`/`value` parameters covering interfaces/cpu/memory/icon (not
  just ram/cpu/ethernet) -- `icon` gets its own case-insensitive
  substring search/narrow against EVE-NG's icon catalog
  (`icon_search`/`icon_selection`), the same pattern as template
  resolution. Whatever isn't supplied is prompted for one piece at a
  time; every stage is stateless, re-deriving everything fresh from
  what's currently given. Final confirmation lists every affected node,
  the template, and the change, and warns every affected node will be
  stopped first -- reply "accept" or "yes" (`confirm`), the same wording
  used by every delete tool, kept consistent. New
  `_search_existing_nodes_by_vendor_template`, `_search_icons`,
  `_bulk_node_label`, `_template_choice_label`.

### Fixed
- **Root-caused what initially looked like an EVE-NG network-creation
  timing issue back to a real bug in this project: `add_lab_network` was
  omitting `left`/`top`.** Same bug class as `add_lab_node`'s equivalent
  fix, but a much more confusing failure mode -- omitting them from
  `add_lab_node` produces a clean `500`; omitting them from
  `add_lab_network` doesn't error at all, EVE-NG reports `201 Created`
  with a plausible network id, but the network never actually persists
  (confirmed live: absent from `list_lab_networks`, `get_lab_topology`,
  and a direct by-id lookup, immediately and later). Found by directly
  comparing two networks created through EVE-NG's own GUI (one visible,
  one hidden, left behind specifically for this comparison) against what
  this project's own request was sending -- the GUI-created ones both had
  concrete `left`/`top`, the auto-created bridge from `connect_interface`
  had neither. Fixed at the source: `EvengClient.add_lab_network` now
  always sends `left`/`top` (default `"0"`/`"0"`), same pattern as
  `add_lab_node`. Also fixed the exact same "tool layer forwards a bare
  None, overriding the client's new default" bug this uncovered a second
  time -- `tools/networks.py`'s `add_lab_network` now resolves `"0"`
  itself before calling the client, mirroring the fix already made for
  nodes. Also corrected: the field that actually controls whether a
  network renders as its own icon vs. an invisible direct line is
  `hideme` (`0`/`1`), not `visibility` as the previous entry below
  (written before this was traced to its real cause) assumed.
- `connect_interface`'s node-to-node mode still polls for its newly-created
  backing network to actually appear before wiring to it
  (`_wait_for_network_ready`, `list_lab_networks`, up to 5 attempts) --
  kept as a defensive check for genuine propagation delay, which could
  still exist independently of the bug above, without assuming that's
  what caused any specific past failure.
- **Follow-up: the `left`/`top` fix above was not sufficient on its own.**
  Confirmed live, redeployed and retried -- network creation still
  silently failed to persist. Comparing the same two GUI-created
  networks' *full* field set (not just `left`/`top`) against this
  project's request revealed 10 more fields the GUI always sends that
  this project didn't: `style`, `icon`, `width`, `linkstyle`, `color`,
  `label`, `visibility`, `hideme`, `native_vlan`, `smart`.
  `EvengClient.add_lab_network` now sends all of them, with the GUI's own
  observed defaults; `tools/networks.py`'s `add_lab_network` gained a
  `hideme` passthrough parameter, and `connect_interface` now passes
  `hideme=1` explicitly for its auto-created node-to-node bridges (the
  field that actually makes them render as an invisible direct line).

### Added
- **`connect_interface(lab_path, node_id, ...)`**: wires a node's
  interface to another node, or to an existing network. EVE-NG has no
  dedicated "connect two nodes" API endpoint -- confirmed against EVE-NG's
  own API docs, a real community troubleshooting thread, and a working
  third-party client library, all pointing at the same mechanism: `PUT
  /nodes/{id}/interfaces` with `{"<index>": "<network_id>"}` is the actual
  primitive, and a "direct" connection is just an ordinary bridge network
  wired to both nodes -- it renders as a plain line in the GUI purely
  because it has exactly two node endpoints, not because of a special
  hidden network type. `target_node_id` creates that backing bridge
  automatically (named `p2p_<node>_<if>_<node>_<if>`, the convention
  observed used for this in the wild) and wires both sides; `network_id`/
  `network_name` wires into a network you already created, which stays
  visible on the canvas. `interface`/`target_interface` accept a name,
  index, or auto-pick the first available (unconnected) ethernet
  interface. New `EvengClient.set_node_interface` and
  `tools/nodes.py`'s `connect_interface`,
  `_resolve_interface_index`/`_first_available_ethernet_index`. Scoped to
  ethernet interfaces only (no confirmed data on serial's index space in
  this endpoint). Also edition-aware: EVE-NG PRO allows wiring interfaces
  on running nodes, Community requires them stopped first, so this checks
  the server's version (`_is_pro_edition`) and, on Community only, stops
  any running node(s) involved first (`_ensure_stopped_for_connection`) --
  but only *after* confirming the connection can actually proceed
  (interface/network resolution happens first, side-effect-free), so a
  node is never stopped for a connection that was going to fail anyway.
- **`edit_lab_node(lab_path, node_id, ...)`**: edits an existing node by
  id (`name`, `icon`, `ram`, `cpu`, `ethernet`, `console`, `config`,
  `left`, `top` -- only supplied fields are changed). Checks the node's
  current `status` first and calls `stop_node` automatically if it's
  running before applying the edit, since EVE-NG generally won't allow
  some fields (notably `name`) to change on a running node. New
  `EvengClient.edit_lab_node` (PUT, same partial-update pattern as
  `edit_lab`) and `tools/nodes.py`'s `_is_running`/`edit_lab_node`. Added
  to resolve duplicate node names live (two nodes sharing a name are only
  distinguishable by id; this is the way to actually fix that rather than
  work around it every time via numbered selection).
- **`list_tools`**: new self-introspection tool (`tools/meta.py`) that
  reports every tool this server currently advertises -- name and
  first-line description, sorted alphabetically. Reflects `tools.env`
  exactly, since it just reports `mcp.list_tools()`'s actual result: a
  disabled tool never appears, because it was never registered at all.
  Enabled by default.
- **Per-tool enable/disable configuration.** Every tool can now be
  individually enabled or disabled via a dedicated dotenv-syntax config
  file (default `tools.env`, path configurable via `MCP_TOOLS_CONFIG_PATH`
  -- applies to all transports, including stdio). A disabled tool is never
  registered with the MCP server at all, not just hidden behind an error.
  `list_users`, `get_user`, `add_user`, `edit_user`, `delete_user`, and
  `list_user_roles` are disabled by default, even with no config file
  present. Any value other than `disabled` (case-insensitive) is treated
  as enabled, so a typo in the file fails safe. New `tool_config.py`
  (`load_tool_status`, `make_enabled_predicate`); every `tools/*.py`
  module's `register()` now takes an `enabled: Callable[[str], bool]`
  parameter and wraps each `@mcp.tool(...)` registration in `if
  enabled("tool_name"):`. `tools.env.example` lists every tool with its
  default status -- copy it to `tools.env` to customize.

- **Breaking: `add_lab_node`'s `template` parameter is now a
  case-insensitive substring search** (against id, name, and best-effort
  vendor) instead of requiring an exact template id, and is now optional
  (empty matches every template). New `selection` parameter resolves
  ambiguous matches (list number or exact id/name), same pattern as the
  delete tools. Only templates with an image installed are searched, same
  restriction as `list_node_templates`' default.
- **Canvas auto-placement for `add_lab_node`.** When `left`/`top` aren't
  explicitly given, nodes are now placed left to right, 5 per row, 100
  units apart, starting at `(100, 100)`, wrapping to a new row 100 units
  below after 5; a candidate grid slot within 50 units of an existing node
  on both axes is skipped in favor of the next one (`_grid_positions`,
  `_position_is_free`, `_next_free_position` in `tools/nodes.py`). Replaces
  the previous behavior of always defaulting to `"0","0"`. Explicit
  `left`/`top` still override this entirely, and skip the extra
  `list_lab_nodes` call auto-placement would otherwise make.

### Fixed
- **Confirmed root cause and fixed the 500 errors `add_lab_node` was
  hitting on every single node-add attempt against a live EVE-NG PRO
  server, regardless of lab, template, node type, or payload
  completeness.** Tracked down via the server's own error log: EVE-NG's
  `api_nodes.php` (`apiAddLabNode()`) reads `$_POST['left']`
  unconditionally with no `isset()` check, so PHP's "undefined array key"
  warning is promoted to a fatal `ErrorException` by EVE-NG's own error
  handler whenever that key is missing from the request body -- producing
  a 500 with no JSON body. `EvengClient.add_lab_node` previously omitted
  `left`/`top` entirely unless the caller specified a canvas position;
  they're now always included, defaulting to `"0"`, and can still be
  overridden. Also fixed a second bug this surfaced: the tool layer
  (`tools/nodes.py`) always explicitly forwarded `left=left`/`top=top`
  even when both were `None`, which would have overridden the client's
  new `"0"` default with an explicit null and silently defeated the fix --
  the tool now resolves `"0"` itself before calling the client.
- `add_lab_node` also now passes through every *other* default the
  template reports via `get_node_template` (e.g. `qemu_version`,
  `qemu_arch`, `qemu_nic`, `qemu_options`), not just the
  RAM/CPU/ethernet/console/icon/image fields it already resolved, matching
  what EVE-NG's own "Add Node" UI dialog submits rather than omitting
  fields and hoping the server fills in something sensible. This was the
  first fix attempted for the 500s above and remains a real improvement,
  but on its own did not resolve them -- the `left`/`top` issue was the
  actual cause. Handles the case where a list-type option reports an
  empty `value` with the real default only encoded in a list label
  (`{"value": "", "list": {"": "tpl(e1000)"}}`, observed for `qemu_nic`)
  by unwrapping it instead of sending an empty string.

### Added
- `EvengClient._request` now raises an actionable `EvengAPIError` for any
  5xx response with no JSON body (what an unhandled EVE-NG server-side
  exception typically looks like), instead of letting a raw
  `httpx.HTTPStatusError` propagate with just `"Server error '500 ..."`.
  The message explains that a stale lock file left by an earlier
  interrupted request is a common cause, and gives the detect/remove
  commands (`find /opt/unetlab/labs/ -name '*.lock'`, then the same with
  `-exec rm {} \;`) directly. 4xx responses with no JSON body are
  unaffected and still raise as before.

### Changed
- **Breaking: `add_lab_node` now fetches the template's own defaults
  (`get_node_template`) and fills in `node_type`, RAM, CPU, ethernet count,
  console type, and icon for anything not explicitly given**, instead of
  hardcoded tool-level defaults (`console="telnet"`, `cpu=1`,
  `icon="Router.png"` always). `node_type` became optional (previously
  required) and defaults to the template's own declared type. Works
  generically off whatever the template reports -- no per-vendor special
  casing. Falls back to the old hardcoded defaults if the template lookup
  fails or returns unexpected data, so it never hard-errors on this step.
- **Breaking: if the template has more than one image and `image` isn't
  specified, `add_lab_node` no longer silently picks one (or lets EVE-NG
  pick).** It returns `status: "selection_required"` with the full list of
  available images and asks you to call again with the one you want. With
  exactly one image (or one already specified), it proceeds directly, no
  prompt.
- Split OS-specific documentation (install, running each transport, and
  Claude Desktop/Code JSON configuration) out of the main README into
  `docs/install-linux.md` and `docs/install-windows.md`. The main README
  now covers only what's OS-agnostic (features, configuration variables,
  tool list, delete-confirmation flow) and links out to the two guides for
  concrete commands and JSON. This lets each guide use correct
  platform-specific syntax throughout (PowerShell `$env:VAR=...` vs bash
  `VAR=...`, `Scripts\python` vs `bin/python`, execution-policy and
  Windows Firewall notes, etc.) instead of a single mixed-platform block.
- **Breaking: merged `list_labs` and `list_all_labs` into a single
  `list_labs` tool, which is now always recursive.** `list_labs()` (default
  `path="/"`) walks the whole server; `list_labs("/User1")` walks the tree
  starting from `/User1`, not just that one folder's immediate contents --
  there is no more non-recursive single-folder mode. The tool-level
  `list_all_labs` function/tool is removed; `EvengClient.list_all_labs`
  (the underlying recursive walk with its loop-safety guarantees) is
  unchanged and is what the merged tool now always uses.

### Added
- `open_lab(name, search_path="/", selection="")`: looks a lab up by
  path/name substring (same matching as `delete_lab`), reports whether
  it's locked and states the lab's actual name, and suggests next steps
  (add a node, add a network, edit metadata). If more than one lab
  matches, lists them numbered and resolves `selection` (a list number or
  the lab's full name/path, case-insensitive) to exactly one -- reusing
  `delete_lab`'s exact-match logic, now shared as `_lab_matches_exact`.
  Purely read-only -- named to avoid colliding with the existing
  `edit_lab` tool, which actually mutates a lab's metadata and takes an
  exact `lab_path`.

### Changed
- `vendor.py`'s vendor extraction now uses a curated alias map
  (`_VENDOR_ALIASES`) instead of a bare "known vendor names" set: each
  entry maps a match string (case-insensitive prefix) to a canonical
  vendor name, so known EVE-NG catalog inconsistencies (e.g. the typo
  "Barraccuda") and full legal names (e.g. "Palo Alto Networks", "Hewlett
  Packard Enterprise") all collapse onto one consistent output ("Barracuda",
  "Palo Alto", "HPE"). Falls back to the description's first word for
  anything not in the map, same as before.

### Added
- `src/mcp_eveng/vendor.py`: best-effort vendor extraction from template
  description text (EVE-NG's API has no explicit vendor field), plus
  `has_image`/`strip_hidden_marker` built on a confirmed real signal --
  EVE-NG suffixes a template's description with `.hided` when no image is
  installed for it.
- **Breaking: `list_node_templates` now filters out templates with no
  image installed by default.** Response shape changed from a raw
  `{template_id: description}` dict to `{"templates": [...], "count": N}`,
  each entry now `{"id", "name", "vendor", "has_image"}`. Pass
  `include_without_images=true` to see the full ~180-template catalog
  instead of just what's actually usable on this server.
- `get_node_template` and `list_lab_nodes` now include a best-effort
  `vendor` field on their results (and `get_node_template` also gets
  `has_image`, derived directly from whether its own image list is
  non-empty). `delete_lab_node`'s numbered candidate lists now show vendor
  too, e.g. `"canvas-14 [Juniper] (id 21)"`.

### Changed
- **Breaking: replaced the `confirm`/`confirm_all` boolean pattern with a
  proper search -> select -> confirm flow across every delete tool.** A new
  shared `confirmation.run_delete_flow()` drives all five tools:
  - 0 matches: cancelled, nothing else happens.
  - 1 match: `confirmation_required`, listed as a 1-item numbered list;
    call again with `confirm=true`.
  - 2+ matches: `selection_required`, full numbered list returned; call
    again with `selection` set to number(s) and/or exact name(s)
    (space/comma separated), which re-resolves against a fresh search and
    returns the narrowed list as `confirmation_required`; call again with
    the same `selection` plus `confirm=true` to delete.
  - `delete_lab_network` / `delete_lab_node` allow selecting/deleting more
    than one item per call (`selection="1,3"` etc.); `delete_folder`,
    `delete_user`, and `delete_lab` are hard-restricted to exactly one --
    `run_delete_flow`'s `allow_multiple` flag enforces this centrally.
  - `resolve_selection()` matches each token as either a 1-based list
    number or an exact (not substring) case-insensitive name/path; an
    exact match against two candidates of the same name is treated as
    ambiguous and rejected, not silently resolved.
- **Breaking: dropped id matching entirely.** `delete_lab_network` and
  `delete_lab_node` renamed their `name_or_id` parameter back to `name`
  and now only ever match against the item's name -- never its numeric id
  (though the id is still shown in listings for reference). Removed
  `find_by_name_or_id_case_insensitive` from `search.py`.
- README: rewrote "Deleting things requires confirmation" for the new flow,
  and fixed install/run instructions -- `git clone` produces a `mcp_eveng/`
  directory (underscore), not `mcp-eveng/`; the Claude Desktop stdio JSON
  example now points `command` at the venv's Python interpreter directly
  with `args: ["-m", "mcp_eveng"]`, since Claude Desktop (a GUI app) doesn't
  inherit shell `PATH` and can't reliably find the `mcp-eveng` console-script
  shim the way an activated terminal can.
- **Breaking: every delete tool now matches as a case-insensitive
  substring, not an exact match.** `search.py`'s `find_by_name_case_insensitive`
  and `find_by_name_or_id_case_insensitive` now use substring containment.
  `delete_lab`'s `_lab_matches` simplified accordingly (the old
  `.unl`-stripping exact-match logic became redundant once substrings
  subsume it). A broad substring can now match many items at once (e.g.
  `"canvas"` matching every `canvas-N` node) -- the two-call confirmation
  step is what keeps this safe.
- **Breaking: `delete_folder` reworked to search recursively.** It
  previously assumed an exact path so it could derive a single parent
  directory to check; substring matching can't do that. It now uses a new
  `EvengClient.list_all_folders()` (mirrors `list_all_labs()`'s recursive
  walk and loop-safety design) and gained `search_path` and `confirm_all`
  parameters. Under `confirm_all`, non-empty matches are skipped and
  reported (not deleted) while empty ones are deleted; the response
  `status` becomes `"partial"` if that happens.
- **Breaking: replaced MCP elicitation with a plain two-call confirmation
  pattern for every delete tool.** Claude Desktop does not implement MCP
  elicitation (confirmed: `anthropics/claude-code#41110` -- elicitation is
  CLI-only for now), so `ctx.elicit()` errored out immediately there and
  every delete tool was silently inert. Now: call once with just the
  search string (nothing is deleted, response lists matches); call again
  with the same string plus `confirm=true` (or `confirm_all=true`, where
  offered) to actually delete. No special MCP host capability required.
  - `delete_folder`, `delete_user`, `delete_lab_network`, `delete_lab_node`,
    `delete_lab` all dropped their `ctx: Context` parameter.
  - `delete_user`, `delete_lab_network`, `delete_lab_node` gained
    `confirm: bool` and `confirm_all: bool` parameters.
  - `delete_folder` gained `confirm: bool` (no `confirm_all` -- a path
    match is structurally always at most one folder).
  - `delete_lab` gained `confirm: bool` only, still never bulk-deletes: if
    more than one lab still matches on `confirm=true`, the call is refused
    and the search must be narrowed to exactly one match first.
  - `src/mcp_eveng/confirmation.py` dropped `choose_deletion_targets` and
    the elicitation/pydantic dependency entirely; it's now just
    `format_bullets`/`format_numbered` plain-text helpers.
- `delete_lab_network` / `delete_lab_node` now match on **name or numeric
  id**, case-insensitive (previously name only) — the `name` parameter was
  renamed to `name_or_id` on both. Added `find_by_name_or_id_case_insensitive`
  to `search.py` for this.

### Changed
- **Breaking: reworked the delete-confirmation UX for every delete tool.**
  Replaced the old plain yes/no confirmation with a single numbered-list
  choice: every match is shown as "1. ...", "2. ...", plus a trailing
  "N. All" entry (except `delete_lab`, see below), and the user must pick a
  specific number for anything to happen. Any other answer -- decline,
  cancel, invalid input, or a host without elicitation support -- cancels
  with nothing deleted.
- **Breaking: all delete tools now match case-insensitively on a required
  string**, with no meaningful default -- calling one with an empty/missing
  string fails immediately with an explanatory error, before any search
  happens.
  - `delete_folder`: matches on **path only** (never a bare name); refuses
    to delete a non-empty folder and lists its contents as bullets instead.
  - `delete_user`: matches on username.
  - `delete_lab_network` / `delete_lab_node`: now take a `name` (not a
    numeric `network_id`/`node_id`), matched within the given `lab_path`.
  - `delete_lab`: matches on **path OR name**; still never offers "All" and
    never deletes more than one lab per call (stricter than every other
    delete tool, deliberately).
- Renamed every tool to drop the `eveng_` prefix (`eveng_get_status`
  -> `get_status`, `eveng_delete_lab` -> `delete_lab`, etc.). Update any
  saved prompts/automations that reference the old names. Note this also
  means tool names are now generic enough to collide with another MCP
  server's tools if you connect more than one to the same client.

### Added
- `src/mcp_eveng/search.py`: shared case-insensitive exact-match search
  helpers (`iter_named_records`, `find_by_name_case_insensitive`) used by
  the reworked delete tools.
- `list_labs(path)`: labs only (not subfolders), in one folder.
- `list_all_labs(start_path)`: recursive lab search across the whole tree.
  EVE-NG's API has no recursive-listing endpoint (confirmed against the
  actual server source, `api.php`) so this walks the tree itself, with
  explicit loop protection (skips every `".."` entry, never revisits a
  folder, and hard `max_depth`/`max_folders` ceilings) and dedupes labs by
  path (EVE-NG's `/Running` virtual folder can otherwise list a lab twice).
- `EVENG_HOST` now rejects a value containing a URL scheme (e.g.
  `https://172.16.130.14`) at startup with a clear, actionable error message
  pointing at `EVENG_PROTOCOL`, instead of failing deep inside an HTTP call
  with a cryptic `getaddrinfo failed`.
- Ctrl+C (`KeyboardInterrupt`) is now caught around the server's run loop
  (and, defensively, around CLI setup too) and exits cleanly with a
  "Goodbye!" message on stderr and exit code 0, instead of a raw traceback.

### Fixed
- Suppressed the upstream `IncompleteFieldDefinitionWarning: Field 'lifespan'
  has an incomplete definition...` warning that `pydantic-settings` prints on
  every `FastMCP` construction. It comes from the `mcp` SDK's own internal
  `Settings` model (a self-referential `lifespan` field type it never calls
  `model_rebuild()` on) and has no functional effect -- purely cosmetic
  noise, now filtered at the source.
- `mcp-eveng --http` (and `--sse`, and plain stdio) crashed on startup with
  `TypeError: argument of type 'ModelPrivateAttr' is not iterable` from
  `MCPTransportSettings`'s `log_level` validator -- **every single run**,
  even with no `MCP_LOG_LEVEL` set. Cause: pydantic v2 converts *any*
  leading-underscore class attribute inside a `BaseModel`/`BaseSettings`
  subclass into a `ModelPrivateAttr` descriptor, even without a type
  annotation -- so `_VALID_LOG_LEVELS = (...)` declared inside the class
  body was silently wrapped, and `cls._VALID_LOG_LEVELS` no longer returned
  the plain tuple. Fixed by moving the constant to module scope, outside
  the class.
- `MCP_ALLOWED_HOSTS` crashed with a `json.decoder.JSONDecodeError` ("Extra
  data") whenever it was actually set, via either a real environment
  variable or a `.env` file. Cause: pydantic-settings tries to JSON-decode
  `list[str]` fields before any validator runs, so a value like
  `192.168.1.100:8000,192.168.1.150:*` got fed to `json.loads()`, which
  parsed `192.168` as a float and then choked on the next `.`. Fixed with
  the `Annotated[list[str], NoDecode]` pattern so the comma-splitting
  validator sees the raw string instead.

### Changed
- `.env.example` (and the shell examples in README) now quote every
  variable's value (`EVENG_HOST="127.0.0.1"`, etc.) for consistency. This
  also happens to fix a real footgun in the README's `--http` shell example:
  an unquoted `MCP_ALLOWED_HOSTS=...,*` could have its trailing `*` glob-expanded
  by the shell against files in the current directory.
- Renamed project from `eve-ng-mcp` to `mcp-eveng` (package `eve_ng_mcp` ->
  `mcp_eveng`). All identifiers, tool names, env var prefixes, and docs were
  updated accordingly: `EveNGClient` -> `EvengClient`, `EVE_NG_*` env vars ->
  `EVENG_*`, tool names `eve_*` -> `eveng_*`, etc. This is a breaking change
  for anyone already depending on the old names.
- **Transport selection is now a CLI flag, not an environment variable.**
  `MCP_TRANSPORT` is removed; use `mcp-eveng` (stdio, default), `mcp-eveng
  --sse`, or `mcp-eveng --http`. `--sse` and `--http` are mutually exclusive.
- Renamed `MCP_STREAMABLE_HTTP_PATH` -> `MCP_HTTP_PATH`.
- `MCP_LOG_LEVEL` is now validated against the standard Python levels
  (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`); logging is explicitly sent to
  stderr regardless of transport.

### Added
- `MCP_ALLOWED_HOSTS`: comma-separated `host:port`/`host:*` allowlist passed
  to the SDK's `TransportSecuritySettings` for DNS-rebinding protection.
  Required (server refuses to start otherwise) whenever `MCP_HOST` is not a
  loopback address.
- `MCP_STATEFUL` (default `true`): set to `false` to run streamable-http with
  `stateless_http=True`, so a server restart doesn't leave clients holding a
  session id the server no longer recognizes.
- README: streamable-http example for Claude Desktop/Code via `mcp-remote`.

## [0.1.0] - 2026-08-08

### Added
- Initial release.
- Async EVENG REST API client covering auth, system status, node templates,
  network types, user roles, folders, users, labs, lab networks, lab nodes
  (including start/stop/wipe/export/interfaces), topology, links, and pictures.
- MCP tools for every client method, grouped by API area.
- Support for `stdio`, `sse`, and `streamable-http` transports, configured via
  environment variables / `.env`.
- Unit test suite (client, config, dependencies, tools, server wiring).
- CI workflow (lint, type-check, test on 3.10-3.13) and PyPI trusted-publishing
  release workflow.
