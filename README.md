# QuickPrint Pi Agent

Production-oriented Raspberry Pi print agent for the QuickPrint college self-service printing system. Runs on a Raspberry Pi connected to a printer and executes jobs authorized by the QuickPrint backend over WebSocket.

Separate from the Next.js frontend and Express backend. No PostgreSQL, Razorpay, Redis, or payment logic on the Pi.

**Physical printing is not verified in this repository** — CUPS behavior is covered by automated tests with a fake command runner. Paper output requires a real printer on the Pi.

## Requirements

- Python **3.13+** (3.11+ may work for local dev; Pi target is 3.13)
- macOS or Linux for development (`PRINTER_MODE=mock`)
- Raspberry Pi OS Lite 64-bit / Debian for production (`PRINTER_MODE=cups`)

## Mac development

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

Run the agent:

```bash
python -m app.main
```

Without `BACKEND_WS_URL`, the WebSocket client stays disabled; jobs can still be driven via tests or `scripts/test_mock_job.py`.

Run tests (no CUPS or printer required on Mac):

```bash
pytest
python scripts/test_mock_job.py
```

## Architecture

```
Backend WebSocket → WebSocketClient → JobManager
                         ↓
                    SQLite (local state)
                         ↓
                    Downloader → Printer (MockPrinter | CupsPrinter)
```

CUPS CLI (`lp`, `lpstat`, `cancel`) is **only** used inside [`app/cups.py`](app/cups.py) via an injectable [`CupsCommandRunner`](app/cups_command.py).

## Configuration

| Variable | Description |
|----------|-------------|
| `AGENT_ENV` / `ENVIRONMENT` | `development` or production-style |
| `AGENT_ID` | Device ID (required in production) |
| `AGENT_SECRET` / `AGENT_TOKEN` | Device secret (never commit) |
| `BACKEND_URL` / `BACKEND_API_URL` | HTTP base (reserved) |
| `BACKEND_WS_URL` | WebSocket URL (required in production) |
| `JOB_DIRECTORY` | Root for `jobs/{incoming,processing,completed,failed}` |
| `DATABASE_PATH` | SQLite path (default `data/agent.db`) |
| `PRINTER_MODE` | `mock` or `cups` |
| `CUPS_PRINTER_NAME` | **Canonical** CUPS queue name when `cups` |
| `PRINTER_NAME` | Legacy alias (used only if `CUPS_PRINTER_NAME` is unset) |
| `CUPS_PRINTER` | Legacy alias (used only if both above are unset) |
| `CUPS_SERVER` | Optional CUPS server host (empty = local socket) |
| `LOG_LEVEL` | Logging level |
| `HEALTH_REFRESH_INTERVAL_SECONDS` | Heartbeat health refresh interval |
| `MAX_DOWNLOAD_BYTES` / `DOWNLOAD_MAX_BYTES` | Max download size |
| `DOWNLOAD_TIMEOUT_SECONDS` | HTTP timeout |
| `RETRY_MAX_ATTEMPTS` | Max download/retry attempts before `FAILED` |
| `RETRY_BASE_DELAY_SECONDS` | Retry backoff base |
| `RETRY_MAX_DELAY_SECONDS` | Retry backoff cap |
| `CUPS_COMMAND_TIMEOUT_SECONDS` | Subprocess timeout for CUPS CLI |
| `JOB_POLL_INTERVAL_SECONDS` | Printer status poll interval (default 1s) |
| `MOCK_PRINT_*` | Mock printer delay/failure simulation |

## Print settings → CUPS

[`app/cups_options.py`](app/cups_options.py) maps `PrintSettings` to `lp -o` options (media, color, duplex, number-up, orientation, fit-to-page, page-ranges). [`app/page_range.py`](app/page_range.py) validates page ranges before submission.

## CUPS exactly-once limitation

CUPS does not guarantee exactly-once physical printing. The agent mitigates duplicates by persisting `cups_job_id`, monitoring in-flight jobs on recovery, and tagging submissions with a deterministic title (`QuickPrint:<backend_job_id>`) so a `READY` job without a stored ID can adopt an existing queue entry when `lpstat` lookup succeeds. If lookup is ambiguous or fails, the job moves to `FAILED` for backend reconciliation rather than submitting again.

## Duplicate-print protection

| Situation | Behavior |
|-----------|----------|
| `COMPLETED` / `FAILED` / `CANCELLED` | Re-assign → ack only, **no** re-print |
| `SUBMITTED` / `PRINTING` | Monitor persisted `cups_job_id` only |
| CUPS state unknown | `FAILED` (backend reconciliation), **no** auto re-`lp` |
| `cups_job_id` set | Never run download/submit pipeline again |

## Retry policy

Retryable download (and transient printer unavailable **before** submit) failures use `RETRY_WAITING` with exponential backoff. Permanent errors (4xx, invalid settings, post-submit ambiguity) go to `FAILED`. Retries never run after a `cups_job_id` exists.

## Raspberry Pi deployment

### CUPS setup (no physical printer required for development)

The agent is **printer-agnostic**. It submits jobs to a configured CUPS queue; CUPS handles drivers and hardware.

#### 1. Install CUPS

```bash
sudo apt update
sudo apt install -y cups cups-client
sudo systemctl enable --now cups
```

#### 2. Verify CUPS

```bash
systemctl status cups
lpstat -r          # scheduler is running
lpstat -p -d       # list queues
```

#### 3. Create a virtual/test queue (no hardware)

```bash
sudo scripts/setup-cups-test-printer.sh
# Creates queue: quickprint-test (override with CUPS_TEST_QUEUE=name)
lpstat -p quickprint-test
```

#### 4. Configure the agent `.env`

```env
PRINTER_MODE=cups
CUPS_PRINTER_NAME=quickprint-test
CUPS_SERVER=localhost
AGENT_ID=<from backend seed>
AGENT_SECRET=<from backend seed>
BACKEND_WS_URL=ws://<API_HOST>:8000/ws/kiosk
```

#### 5. Run the agent

```bash
python -m app.main
# or via systemd (see Install below)
```

#### 6. Submit a test job

With backend connected, assign a job over WebSocket. For local testing without backend:

```bash
PRINTER_MODE=mock python scripts/test_mock_job.py   # mock only
```

On Linux with CUPS configured:

```bash
CUPS_INTEGRATION=1 CUPS_PRINTER_NAME=quickprint-test pytest tests/test_cups_integration.py -v
```

#### 7. Watch logs

```bash
journalctl -u quickprint-agent -f
# or local file:
tail -f logs/agent.log
```

Expected lifecycle log lines include: `Job received`, `Download completed`, `Job ready`, `Submitting print job`, `CUPS job created`, `Printing started`, `Print completed`.

#### 8. Troubleshooting

| Symptom | Check |
|---------|--------|
| Queue missing | `lpstat -p <name>` — run setup script or configure queue in CUPS |
| Permission denied | `quickprint` user in `lp` group (`sudo usermod -aG lp quickprint`) |
| Not accepting jobs | `sudo cupsaccept <name>` and `sudo cupsenable <name>` |
| CUPS down | `systemctl status cups` |

#### 9. Switch to a physical printer later

1. Connect printer (USB or network).
2. Add printer in CUPS (`lpinfo -v`, then configure queue via CUPS admin UI or `lpadmin`).
3. Set `CUPS_PRINTER_NAME=<new-queue-name>` in `.env`.
4. `sudo systemctl restart quickprint-agent`.

**No agent code changes** are required for HP, Canon, Brother, etc. — only CUPS queue configuration.

If no printer is configured, the agent reports printer unavailable and **does not crash**.

### Install

```bash
# Copy repo to /opt/quickprint-pi-agent, then:
sudo scripts/install.sh
sudo nano /opt/quickprint-pi-agent/.env
sudo systemctl enable --now quickprint-agent
sudo journalctl -u quickprint-agent -f
```

Update: `scripts/update.sh`  
Remove service: `scripts/uninstall.sh` (preserves data)

## Logs

Structured logs to stderr / journald and rotating file `logs/agent.log` (10 MB × 5). Secrets, tokens, auth headers, and signed URL query strings are redacted.

## Backend integration (TBD with Express)

- WebSocket URL, TLS, auth header format
- Final `job.assigned` / status JSON schema
- Resend vs new assignment after offline Pi

## Tests

```bash
pytest -q
```

Includes CUPS unit tests with `FakeCupsRunner` (no real `lp`). Real CUPS integration:

```bash
CUPS_INTEGRATION=1 CUPS_PRINTER_NAME=quickprint-test pytest tests/test_cups_integration.py -v
```

## License

Internal QuickPrint component.
