# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.11.1] - 2026-03-09

### Fixed

- 🐛 **Multi-user file operations** — all file endpoints (list, read, view, display, replace, grep, glob, upload) now correctly run as the provisioned user. Previously only write/delete/move were handled, causing `PermissionError` on reads in user home directories.

### Changed

- ♻️ **UserFS abstraction** (`open_terminal/utils/fs.py`) — unified filesystem interface that transparently routes I/O through `sudo -u` in multi-user mode. Endpoints receive a `UserFS` instance via dependency injection and no longer branch on mode. Replaces per-endpoint sudo wrappers.

## [0.11.0] - 2026-03-09

### Added

- 👥 **Multi-user mode** (`OPEN_TERMINAL_MULTI_USER=true`) — per-user OS accounts inside a single container, with standard Unix permissions (`chmod 700`) providing kernel-enforced isolation between users. When enabled, Open Terminal reads the `X-User-Id` header (set by the Open WebUI proxy), provisions a dedicated Linux user on first access via `useradd`, and runs all commands, file operations, and terminal sessions as that user via `sudo -u`. No Docker socket, no per-user containers, no enterprise license required. Fails fast with a clear error on non-Linux platforms. ([#38](https://github.com/open-webui/open-terminal/issues/38))
- ⚙️ **`OPEN_TERMINAL_UVICORN_LOOP`** — environment variable (or `uvicorn_loop` in config.toml) to configure the Uvicorn event loop implementation. Defaults to `auto`.

## [0.10.2] - 2026-03-06

### Added

- 🐳 **Docker CLI, Compose, and Buildx** bundled in the container image via [get.docker.com](https://get.docker.com). Mount the host's Docker socket (`-v /var/run/docker.sock:/var/run/docker.sock`) to let agents clone repos, build images, and run containers. The entrypoint automatically fixes socket group permissions so `docker` commands work without `sudo`.

## [0.10.1] - 2026-03-06

### Fixed

- 🌐 **UTF-8 encoding on Windows** — all text file I/O now explicitly uses UTF-8 encoding instead of the system default. Fixes Chinese (and other non-ASCII) content being written as GB2312 on Chinese Windows, which broke tool-call chaining and produced garbled files. ([#21](https://github.com/open-webui/open-terminal/issues/21))

## [0.10.0] - 2026-03-05

### Added

- 📓 **Notebook execution** (`/notebooks`) — multi-session Jupyter notebook execution via REST endpoints. Each session gets its own kernel via `nbclient`. Supports per-cell execution with rich outputs (images, HTML, LaTeX). `nbclient` and `ipykernel` are now core dependencies.
- ⚙️ **`OPEN_TERMINAL_ENABLE_NOTEBOOKS`** — environment variable (or `enable_notebooks` in config.toml) to enable/disable notebook execution endpoints. Defaults to `true`. Exposed in `GET /api/config` features.

## [0.9.3] - 2026-03-05

### Added

- 📓 **Notebook execution support** — new `notebooks` optional extra (`pip install open-terminal[notebooks]`) adds `nbclient` and `ipykernel` for running Jupyter notebooks with per-cell execution and full rich output (images, HTML, LaTeX). Keeps the core package lightweight for users who don't need notebook support.

## [0.9.2] - 2026-03-05

### Added

- 📝 **Custom execute description** — new `OPEN_TERMINAL_EXECUTE_DESCRIPTION` environment variable (or `execute_description` in config.toml) appends custom text to the execute endpoint's OpenAPI description, letting you tell AI models about installed tools, capabilities, or conventions.

## [0.9.1] - 2026-03-05

### Added

- 📦 **Startup package installation** — new `OPEN_TERMINAL_PACKAGES` and `OPEN_TERMINAL_PIP_PACKAGES` environment variables install additional apt and pip packages automatically when the Docker container starts. No need to fork the Dockerfile for common customizations.

## [0.9.0] - 2026-03-04

### Added

- 🔍 **Port detection** (`GET /ports`) — discovers TCP ports listening on localhost, scoped to descendant processes of open-terminal (servers started via the terminal or `/execute`). Cross-platform: parses `/proc/net/tcp` on Linux, `lsof` on macOS, `netstat` on Windows. Zero new dependencies.
- 🔀 **Port proxy** (`/proxy/{port}/{path}`) — reverse-proxies HTTP requests to `localhost:{port}`, enabling browser access to servers running inside the terminal environment. Supports all HTTP methods, forwards headers and body, returns 502 on connection refused. Uses the existing `httpx` dependency.
- 📦 **`utils.port` module** — port detection and process-tree utilities extracted into `open_terminal/utils/port.py` for reusability.

## [0.8.3] - 2026-03-04

### Added

- ⏱️ **Default execute timeout** — new `OPEN_TERMINAL_EXECUTE_TIMEOUT` environment variable (or `execute_timeout` in config.toml) sets a default wait duration for command execution. Smaller models that don't set timeouts now get command output inline instead of assuming failure.

## [0.8.2] - 2026-03-02

### Added

- 🎨 **Terminal color support** — terminal sessions now set the `TERM` environment variable (default `xterm-256color`) so programs emit ANSI color codes. Configurable via `OPEN_TERMINAL_TERM` environment variable or `term` in config.toml.

## [0.8.1] - 2026-03-02

### Added

- ⚙️ **Configurable terminal feature** — new `OPEN_TERMINAL_ENABLE_TERMINAL` environment variable (or `enable_terminal` in config.toml) to enable or disable the interactive terminal. When disabled, all `/api/terminals` routes and the WebSocket endpoint are not mounted. Defaults to `true`.
- 🔍 **Config discovery endpoint** (`GET /api/config`) — returns server feature flags so clients like Open WebUI can discover whether the terminal is enabled and adapt the UI accordingly.

## [0.8.0] - 2026-03-02

### Added

- 🪟 **Windows PTY support** — terminal sessions and command execution now work on Windows via [pywinpty](https://github.com/andfoy/pywinpty) (ConPTY). `pywinpty` is auto-installed on Windows. Interactive terminals (`/api/terminals`), colored output, and TUI apps now work on Windows instead of returning 503.
- 🏭 **WinPtyRunner** — new `ProcessRunner` implementation using `winpty.PtyProcess` for full PTY semantics on Windows, including resize support. The `create_runner` factory now prefers Unix PTY → WinPTY → pipe fallback.

## [0.7.2] - 2026-03-02

### Added

- 🔒 **Terminal session limit** — new `OPEN_TERMINAL_MAX_SESSIONS` environment variable (default `16`) caps the number of concurrent interactive terminal sessions. Dead sessions are automatically pruned before the limit is checked. Returns `429` when the limit is reached.

### Fixed

- 🐳 **PTY device exhaustion** — fixed `OSError: out of pty devices` by closing leaked file descriptors when subprocess creation fails after `pty.openpty()`. Both `PtyRunner` (command execution) and `create_terminal` (interactive sessions) now properly clean up on error paths.
- 🛡️ **Graceful PTY error handling** — `create_terminal` now returns a clear `503` with a descriptive message when the system runs out of PTY devices, instead of an unhandled server error.

## [0.7.1] - 2026-03-02

### Fixed

- 🐳 **Docker terminal shell** — fixed `can't access tty; job control turned off` error by setting the default shell to `/bin/bash` for the container user. Previously the user was created with `/bin/sh` (dash), which does not support interactive job control in a PTY.

## [0.7.0] - 2026-03-02

### Added

- 🖥️ **Interactive terminal sessions** — full PTY-based terminal accessible via WebSocket, following the JupyterLab/Kubernetes resource pattern. `POST /api/terminals` to create a session, `GET /api/terminals` to list, `DELETE /api/terminals/{id}` to kill, and `WS /api/terminals/{id}` to attach. Non-blocking I/O ensures the terminal never starves other API requests. Sessions are automatically cleaned up on disconnect.

## [0.6.0] - 2026-03-02

### Added

- 📄 **Configuration file support** — settings can now be loaded from TOML config files at /etc/open-terminal/config.toml (system-wide) and $XDG_CONFIG_HOME/open-terminal/config.toml (per-user, defaults to ~/.config/open-terminal/config.toml). Supports host, port, api_key, cors_allowed_origins, log_dir, and binary_mime_prefixes. CLI flags and environment variables still take precedence. Use --config to point to a custom config file. This keeps the API key out of ps / htop output.

## [0.5.0] - 2026-03-02

### Changed

- 📂 **XDG Base Directory support** — the default log directory moved from ~/.open-terminal/logs to the XDG-compliant path $XDG_STATE_HOME/open-terminal/logs (defaults to ~/.local/state/open-terminal/logs when XDG_STATE_HOME is not set). The OPEN_TERMINAL_LOG_DIR environment variable still overrides the default.

## [0.4.3] - 2026-03-02

### Added

- 🔐 **Docker secrets support** — set OPEN_TERMINAL_API_KEY_FILE to load the API key from a file (e.g. /run/secrets/...), following the convention used by the official PostgreSQL Docker image.

## [0.4.2] - 2026-03-02

### Added

- 📦 **Move endpoint** (POST /files/move) for moving and renaming files and directories. Uses shutil.move for cross-filesystem support. Hidden from OpenAPI schema.

## [0.4.1] - 2026-03-01

### Fixed

- 🙈 **Hidden upload_file from OpenAPI schema** — the /files/upload endpoint is now excluded from the public API docs, consistent with other internal-only file endpoints.

## [0.4.0] - 2026-03-01

### Removed

- 📥 **Temporary download links** (GET /files/download/link and GET /files/download/{token}) — deprecated in favour of direct file navigation built into Open WebUI.
- 🔗 **Temporary upload links** (POST /files/upload/link, GET /files/upload/{token}, and POST /files/upload/{token}) — deprecated in favour of direct file navigation built into Open WebUI.

## [0.3.0] - 2026-02-25

### Added

- 🖥️ **Pseudo-terminal (PTY) execution** — commands now run under a real PTY by default, enabling colored output, interactive programs (REPLs, TUI apps), and proper isatty() detection. Falls back to pipe-based execution on Windows.
- 🏭 **Process runner abstraction** — new ProcessRunner factory pattern (PtyRunner / PipeRunner) in runner.py for clean, extensible process management.
- 🔡 **Escape sequence conversion** in send_process_input — literal escape strings from LLMs (\n, \x03 for Ctrl-C, \x04 for Ctrl-D, etc.) are automatically converted to real characters.

### Changed

- 📦 **Merged output stream** — PTY output is logged as type "output" (merged stdout/stderr) instead of separate streams, matching real terminal behavior.

## [0.2.9] - 2026-02-25

### Added

- 📺 **Display file endpoint** (GET /files/display) — a signaling endpoint that lets AI agents request a file be shown to the user. The consuming client is responsible for handling the response and presenting the file in its own UI.

### Changed

- ⏳ **Improved wait behavior** — wait=0 on the status endpoint now correctly triggers a wait instead of being treated as falsy, so commands that finish quickly return immediately rather than requiring a non-zero wait value.

## [0.2.8] - 2026-02-25

### Added

- 📄 **PDF text extraction** in read_file — PDF files are now automatically converted to text using pypdf and returned in the standard text-file JSON format, making them readable by LLMs. Supports start_line/end_line range selection.

## [0.2.7] - 2026-02-25

### Added

- 👁️ **File view endpoint** (GET /files/view) for serving raw binary content of any file type with the correct Content-Type. Designed for UI previewing (PDFs, images, etc.) without the MIME restrictions of read_file.
- 📂 **--cwd CLI option** for both run and mcp commands to set the server's working directory on startup.
- 📍 **Working directory endpoints** — GET /files/cwd and POST /files/cwd to query and change the current working directory at runtime.
- 📁 **mkdir endpoint** (POST /files/mkdir) to create directories with automatic parent directory creation.
- 🗑️ **delete endpoint** (DELETE /files/delete) to remove files and directories.

### Changed

- 📄 **Binary-aware read_file** returns raw binary responses for supported file types (images, etc.) and rejects unsupported binary files with a descriptive error. Configurable via OPEN_TERMINAL_BINARY_MIME_PREFIXES env var.

## [0.2.6] - 2026-02-24

### Added

- 🔍 **File Search Endpoints**: Added a new /files/glob endpoint (alias glob_search) to search for files by name/pattern using wildcards.
- 🔄 **Alias Update**: Renamed and aliased the existing /files/search endpoint to /files/grep (alias grep_search) to establish a clear distinction between content-level search (grep) and filename-level search (glob).

## [0.2.5] - 2026-02-23

### Fixed

- 🛡️ **Graceful permission error handling** across all file endpoints (write_file, replace_file_content, upload_file). PermissionError and other OSError exceptions now return HTTP 400 with a descriptive message instead of crashing with HTTP 500.
- 🐳 **Docker volume permissions** via entrypoint.sh that automatically fixes /home/user ownership on startup when a host volume is mounted with mismatched permissions.
- 🔧 **Background process resilience** — _log_process no longer crashes if the log directory is unwritable; commands still execute and complete normally.

## [0.2.4] - 2026-02-19

### Changed

- ⚡ **Fully async I/O** across all file and upload endpoints. Replaced blocking os.* and open() calls with aiofiles and aiofiles.os so the event loop is never blocked by filesystem operations. search_files and list_files inner loops use asyncio.to_thread for os.walk/os.listdir workloads.

## [0.2.3] - 2026-02-15

### Added

- 🤖 **Optional MCP server mode** via open-terminal mcp, exposing all endpoints as MCP tools for LLM agent integration. Supports stdio and streamable-http transports. Install with pip install open-terminal[mcp].

## [0.2.2] - 2026-02-15

### Fixed

- 🛡️ **Null query parameter tolerance** via HTTP middleware that strips query parameters with the literal value "null". Prevents 422 errors when clients serialize null into query strings (e.g. ?wait=null) instead of omitting the parameter.

## [0.2.1] - 2026-02-14

### Added

- 📁 **File-backed process output** persisted to JSONL log files under 'logs/processes/', configurable via 'OPEN_TERMINAL_LOG_DIR'. Full audit trail survives process cleanup and server restarts.
- 📍 **Offset-based polling** on the status endpoint with 'offset' and 'next_offset' for stateless incremental reads. Multiple clients can independently track the same process without data loss.
- ✂️ **Tail parameter** on both execute and status endpoints to return only the last N output entries, keeping AI agent responses bounded.

### Changed

- 🗑️ **Removed in-memory output buffer** in favor of reading directly from the JSONL log file as the single source of truth.
- 📂 **Organized log directory** with process logs namespaced under 'logs/processes/' to accommodate future log types.

### Removed

- 🔄 **Bounded output buffers** and the 'OPEN_TERMINAL_MAX_OUTPUT_LINES' environment variable, no longer needed without in-memory buffering.

## [0.2.0] - 2026-02-14

### Added

- 📂 **File operations** for reading, writing, listing, and find-and-replace, with optional line-range selection for large files.
- 📤 **File upload** by URL or multipart form data.
- 📥 **Temporary download links** that work without authentication, making it easy to retrieve files from the container.
- 🔗 **Temporary upload links** with a built-in drag-and-drop page for sharing with others.
- ⌨️ **Stdin input** to send text to running processes, enabling interaction with REPLs and interactive commands.
- 📋 **Process listing** to view all tracked background processes and their current status at a glance.
- ⏳ **Synchronous mode** with an optional 'wait' parameter to block until a command finishes and get output inline.
- 🔄 **Bounded output buffers** to prevent memory issues on long-running commands, configurable via 'OPEN_TERMINAL_MAX_OUTPUT_LINES'.
- 🛠️ **Rich toolbox** pre-installed in the container, including Python data science libraries, networking utilities, editors, and build tools.
- 👤 **Non-root user** with passwordless 'sudo' available when elevated privileges are needed.
- 🚀 **CI/CD pipeline** for automated multi-arch Docker image builds and publishing via GitHub Actions.
- 💾 **Named volume** in the default 'docker run' command so your files survive container restarts.

### Changed

- 🐳 **Expanded container image** with system packages and Python libraries for a batteries-included experience.

## [0.1.0] - 2026-02-12

### Added

- 🎉 **Initial release** of Open Terminal, a lightweight API that turns any container into a remote shell for AI agents and automation workflows.
- ▶️ **Background command execution** with async process tracking, supporting shell features like pipes, chaining, and redirections.
- 🔑 **Bearer token authentication** to secure your instance using the 'OPEN_TERMINAL_API_KEY' environment variable.
- 🔐 **Zero-config setup** with an auto-generated API key printed to container logs when none is provided.
- 💚 **Health check** endpoint at '/health' for load balancer and orchestrator integration.
- 🌐 **CORS enabled by default** for seamless integration with web-based AI tools and dashboards.
