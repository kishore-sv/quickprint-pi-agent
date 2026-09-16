# QuickPrint Pi Agent

Production-oriented Raspberry Pi print agent for the QuickPrint college self-service printing system. Runs on a Raspberry Pi connected to a printer and executes jobs authorized by the QuickPrint backend over WebSocket.

Separate from the Next.js frontend and Express backend. No PostgreSQL, Razorpay, Redis, or payment logic on the Pi.

**Physical printing is not verified in this repository** — CUPS behavior is covered by automated tests with a fake command runner. Paper output requires a real printer on the Pi.

## Setup documentation

| Guide | When to use |
|-------|-------------|
| [docs/setup-new-agent.md](docs/setup-new-agent.md) | **New kiosk** — fresh Pi, OS, CUPS, agent, display, full checklist |
| [docs/setup-agent-in-pi.md](docs/setup-agent-in-pi.md) | **Existing Pi** — SSH in, install/update agent, CUPS, systemd |

Protocol reference: [BACKEND_INTEGRATION.md](BACKEND_INTEGRATION.md)

## Requirements

- Python **3.13+** (3.11+ may work for local dev; Pi target is 3.13)
- macOS or Linux for development (`PRINTER_MODE=mock`)
- Raspberry Pi OS 64-bit / Debian for production (`PRINTER_MODE=cups`)

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
| `CUPS_SERVER` | **Leave empty** on Pi for local Unix socket; see setup docs |
| `LOG_LEVEL` | Logging level |

Kiosk display uses a separate `.env.display` — see [docs/setup-new-agent.md](docs/setup-new-agent.md) Phase 10–11.

## Print settings → CUPS

[`app/cups_options.py`](app/cups_options.py) maps `PrintSettings` to `lp -o` options. [`app/page_range.py`](app/page_range.py) validates page ranges before submission.

## CUPS exactly-once limitation

CUPS does not guarantee exactly-once physical printing. The agent mitigates duplicates by persisting `cups_job_id`, monitoring in-flight jobs on recovery, and reconciling UNKNOWN states before resubmitting.

## Tests

```bash
pytest -q
```

Real CUPS integration (Linux with test queue):

```bash
CUPS_INTEGRATION=1 CUPS_PRINTER_NAME=quickprint-test pytest tests/test_cups_integration.py -v
```

## Install scripts

| Script | Purpose |
|--------|---------|
| `scripts/install.sh` | Create venv, dirs, install `quickprint-agent.service` |
| `scripts/setup-cups-test-printer.sh` | Virtual CUPS test queue |
| `scripts/setup-kiosk-display.sh` | Chromium + `quickprint-display.service` |
| `scripts/update.sh` | Git pull + pip install |
| `scripts/uninstall.sh` | Remove systemd unit (keeps data) |

## Logs

Structured logs to stderr / journald and rotating file `logs/agent.log` (10 MB × 5). Secrets, tokens, auth headers, and signed URL query strings are redacted.

## License

Internal QuickPrint component.
