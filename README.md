# QuickPrint Pi Agent

Production-oriented Raspberry Pi print agent for the QuickPrint college self-service printing system. This repository runs on a Raspberry Pi connected to a physical printer and executes print jobs authorized by the QuickPrint backend.

The agent is **separate** from the QuickPrint Next.js frontend and Express backend. It does not access PostgreSQL, Razorpay, or payment logic.

## Requirements

- Python **3.13+**
- macOS or Linux for development (mock printer)
- Raspberry Pi OS Lite 64-bit for production (CUPS when hardware is available)

## Quick start (development, mock printer)

```bash
cd quickprint-pi-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Set in `.env`:

```env
AGENT_ENV=development
PRINTER_MODE=mock
```

Run:

```bash
python -m app.main
```

Without `BACKEND_WS_URL`, the agent starts locally without connecting to the backend.

Run tests:

```bash
pytest
```

## Configuration

| Variable | Description |
|----------|-------------|
| `AGENT_ENV` | `development` or production-style (non-development) |
| `AGENT_ID` | Device identity (required in production) |
| `AGENT_SECRET` | Device secret stored only on the Pi (required in production) |
| `BACKEND_URL` | HTTP base URL (reserved for future use) |
| `BACKEND_WS_URL` | WebSocket URL (required in production) |
| `JOB_DIRECTORY` | Root for `incoming/`, `processing/`, `completed/`, `failed/` |
| `DATABASE_PATH` | SQLite path (default `data/agent.db`) |
| `PRINTER_MODE` | `mock` or `cups` |
| `CUPS_PRINTER_NAME` | CUPS queue name when `PRINTER_MODE=cups` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `MAX_DOWNLOAD_BYTES` | Maximum download size |
| `MOCK_PRINT_DELAY_SECONDS` | Simulated print duration |
| `MOCK_PRINT_FAILURE` | `true` to simulate printer failure |
| `DOWNLOAD_TIMEOUT_SECONDS` | HTTP download timeout |
| `HEARTBEAT_INTERVAL_SECONDS` | WebSocket heartbeat interval |
| `WS_RECONNECT_MAX_DELAY_SECONDS` | Max reconnect backoff |

Never commit `.env` or device secrets. Use `.env.example` for placeholders only.

**Note:** The kiosk QR token and `agent_secret` are different concepts. Do not use the QR token as device authentication.

## Architecture

```
QuickPrint Backend
        |
        | WebSocket (JSON protocol)
        v
+-----------------------------+
| QuickPrint Pi Agent         |
|  WebSocket Client           |
|  Job Manager                |
|  SQLite (local state)       |
|  Downloader                 |
|  Printer (Mock | CUPS)      |
+-----------------------------+
```

Modules live under `app/`:

- `config.py` — environment configuration
- `database.py` — SQLite persistence
- `job_manager.py` — orchestration and recovery
- `downloader.py` — streamed file download
- `printer.py` / `mock_printer.py` / `cups.py` — printer adapters
- `protocol.py` — message schema (adaptable to Express backend)
- `websocket_client.py` — reconnect and heartbeat
- `health.py` — lightweight health snapshot

## Job lifecycle

States: `RECEIVED` → `DOWNLOADING` → `READY` → `SUBMITTED` → `PRINTING` → `COMPLETED`

Failure can move to `FAILED` from any non-terminal execution state. `CANCELLED` is supported for cancel flows.

Downloading a file alone does **not** complete a job. Completion requires successful printer execution (or mock simulation).

## Duplicate-print protection (critical)

The worst failure mode is printing the same paid job twice after a network outage or reboot.

**Rules:**

1. **`backend_job_id` is the idempotency key** (unique in SQLite).
2. **Persist state before irreversible steps** — especially `SUBMITTED` with `cups_job_id` recorded after `lp`/mock submit, before treating the job as printing.
3. **On duplicate `job.assigned`:**
   - `COMPLETED` / `CANCELLED` / `FAILED` → notify backend only; **never** print again.
4. **On restart (`recover_unfinished_jobs`):**
   - `RECEIVED` / `DOWNLOADING` — resume download pipeline.
   - `READY` — submit only if the local file exists; otherwise `FAILED` (reconciliation).
   - `SUBMITTED` / `PRINTING` — **do not re-submit**; poll CUPS/mock using stored `cups_job_id`.
   - If printer state is **unknown** (e.g. CUPS job lost after reboot, mock state empty) → `FAILED` with a message requiring **backend reconciliation**; **no** automatic re-print.

| Situation | Action |
|-----------|--------|
| Job already `COMPLETED` | Ack only |
| Job `SUBMITTED`/`PRINTING`, printer state known | Resume monitoring |
| Job `SUBMITTED`/`PRINTING`, printer state unknown | `FAILED`, manual/backend reconciliation |
| New `backend_job_id` | Normal pipeline |

## Mock mode

`PRINTER_MODE=mock` uses `MockPrinter` — no CUPS or hardware. Configure delay and failure simulation via `MOCK_PRINT_*` variables.

## CUPS (later)

`PRINTER_MODE=cups` uses CLI tools (`lp`, `lpstat`, `cancel`). Requires a configured queue on Raspberry Pi OS. Not validated in CI until hardware is available.

## Raspberry Pi deployment

1. Copy or clone the project to `/opt/quickprint-pi-agent`.
2. Run `scripts/install.sh` (creates `quickprint` user, venv, directories, systemd unit).
3. Edit `/opt/quickprint-pi-agent/.env` for production values.
4. `sudo systemctl enable --now quickprint-agent`
5. Logs: `journalctl -u quickprint-agent -f`

Update with `scripts/update.sh` (preserves `.env` and `data/agent.db`).

## Backend integration (to agree with Express team)

- WebSocket URL, TLS, and optional client certificates
- Authentication header format (placeholder: `Authorization: Bearer {agent_id}:{agent_secret}`)
- Final JSON schema for `job.assigned` and outbound status events
- Whether the backend resends the same `job_id` after the Pi was offline
- Cancel and retry semantics (`job.cancel`, new assignment vs replay)

## Security

- Do not log `agent_secret`, authorization headers, or signed URL query strings (URLs are redacted in logs).
- Sanitize filenames and reject path traversal.
- Run the service as a dedicated non-root user (`quickprint`).

## License

Internal QuickPrint project component.
