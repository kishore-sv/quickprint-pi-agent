# QuickPrint backend integration

Connect this Pi agent to the QuickPrint API WebSocket endpoint.

## Required environment

```env
AGENT_ENV=development
AGENT_ID=<kiosk UUID from quickprint backend `bun run kiosk:seed`>
AGENT_TOKEN=<secret printed once by seed script>
BACKEND_WS_URL=ws://<API_HOST>:8000/ws/kiosk
PRINTER_MODE=mock
```

Optional:

```env
MOCK_PRINT_DELAY_SECONDS=0.5
HEARTBEAT_INTERVAL_SECONDS=30
```

## Authentication

The agent sends on WebSocket connect:

```
Authorization: Bearer <AGENT_ID>:<AGENT_TOKEN>
```

Do not use the kiosk QR `public_token` as `AGENT_TOKEN`.

## Protocol

Matches `app/protocol.py`:

- Inbound: `job.assigned`, `job.cancel`, `ping`
- Outbound: `job.received`, `job.downloading`, `job.ready`, `job.submitted`, `job.printing`, `job.completed`, `job.failed`, `agent.heartbeat`, `printer.telemetry`, `pong`

### `printer.telemetry`

Normalized printer state (separate from print-job lifecycle). Fields include `event_id`, `sequence`, `connection_state`, `operational_state`, `display_state`, `reasons`, `raw_reasons`, `capabilities`, `last_probe_at`, `is_heartbeat`. Backend rejects out-of-order `sequence` values per kiosk.

### Status event fields

Job status messages include:

| Field | When present |
|-------|----------------|
| `type` | Always (e.g. `job.received`) |
| `job_id` | Always (backend print job UUID) |
| `agent_id` | When `AGENT_ID` is configured |
| `timestamp` | Always (UTC ISO-8601) |
| `cups_job_id` | After printer submission (`job.submitted` onward) |
| `error` | On `job.failed` (safe message only; no secrets or stack traces) |

Lifecycle order for a successful job:

`job.received` → `job.downloading` → `job.ready` → `job.submitted` → `job.printing` → `job.completed`

## Local development with Mac backend

Replace `<API_HOST>` with your Mac's LAN IP (not `localhost` when the agent runs on a Pi).

Example:

```env
BACKEND_WS_URL=ws://192.168.1.42:8000/ws/kiosk
```

## Run

```bash
PRINTER_MODE=mock python -m app.main
```

Full Pi deployment: see [docs/setup-new-agent.md](docs/setup-new-agent.md) and [docs/setup-agent-in-pi.md](docs/setup-agent-in-pi.md).
