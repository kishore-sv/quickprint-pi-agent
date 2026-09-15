# QuickPrint Kiosk Display

Physical HDMI kiosk screen for QuickPrint. Shows a QR code when idle and live print progress when a job is active.

The **print agent** (`quickprint-agent.service`) and **display** (`quickprint-display.service`) are separate services.

## Architecture

```
Phone scans QR → /scan/{publicToken} → pay & release job
Pi print agent → /ws/kiosk → backend job events
Local bootstrap (127.0.0.1:18765) → POST /display-session → httpOnly cookie
Chromium display → /kiosk/KIOSK-001 → /ws/kiosk-display (read-only, cookie auth)
```

## Prerequisites

- Raspberry Pi 4 with HDMI display (1080p landscape)
- QuickPrint backend + frontend reachable from the Pi
- `quickprint-agent.service` already running
- Kiosk seeded in backend: `bun run kiosk:seed --rotate-display-token`

## Environment

Create `/opt/quickprint-pi-agent/.env.display` (mode `600`):

```bash
KIOSK_CODE=KIOSK-001
KIOSK_DISPLAY_NAME=Development Kiosk
API_URL=https://quickprint.fun
DISPLAY_URL=https://quickprint.fun/kiosk/KIOSK-001
DISPLAY_TOKEN=<from seed output>
```

Development (LAN):

```bash
API_URL=http://127.0.0.1:8000
DISPLAY_URL=http://localhost:3000/kiosk/KIOSK-001
DISPLAY_TOKEN=<from seed output>
```

**Never** put `AGENT_SECRET` or `DISPLAY_TOKEN` in `DISPLAY_URL`, query parameters, or browser-visible config. The display token is used only by the local bootstrap server to establish an httpOnly session cookie.

## Install on Pi

```bash
cd /opt/quickprint-pi-agent
sudo git pull
sudo bash scripts/setup-kiosk-display.sh
```

Edit `.env.display` with your `API_URL`, `DISPLAY_URL`, and `DISPLAY_TOKEN`, then:

```bash
sudo systemctl enable --now quickprint-display.service
```

## Commands

| Action | Command |
|--------|---------|
| Start display | `sudo systemctl start quickprint-display.service` |
| Restart display | `sudo systemctl restart quickprint-display.service` |
| View logs | `journalctl -u quickprint-display.service -f` |
| Restart print agent | `sudo systemctl restart quickprint-agent.service` |

## Test locally (Mac/dev)

```bash
# Backend: seed display token
cd quickprint/backend && bun run kiosk:seed --rotate-display-token

# Frontend
cd quickprint/client && bun run dev

# Bootstrap server (pairs via local HTTP, then opens browser)
cd quickprint-pi-agent
API_URL=http://127.0.0.1:8000 \
DISPLAY_URL=http://localhost:3000/kiosk/KIOSK-001 \
DISPLAY_TOKEN=<token> \
./scripts/kiosk-display-boot.sh
```

Chromium opens `http://127.0.0.1:18765/`, which pairs server-side and redirects to the clean display URL.

## Packages installed

- `chromium` — fullscreen kiosk browser
- `xserver-xorg`, `openbox`, `lightdm` — minimal graphical session
- `unclutter` — hide mouse cursor
- `x11-xserver-utils` — disable screen blanking (`xset`)

## Boot sequence

```
Power ON → OS boot → network → quickprint-agent.service → graphical session
  → quickprint-display.service
  → local bootstrap server (127.0.0.1:18765)
  → display-session cookie created
  → Chromium opens bootstrap URL
  → redirect to DISPLAY_URL
  → QuickPrint display (cookie auth)
```

## QR code

The on-screen QR encodes the canonical mobile URL:

```
{FRONTEND_URL}/scan/{publicToken}
```

This is stable across agent restarts, Pi reboots, and printer changes.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Blank screen | Check `DISPLAY_URL` and network; `journalctl -u quickprint-display.service` |
| "Display pairing failed" | Verify `API_URL`, `DISPLAY_TOKEN`, and `KIOSK_CODE` in `.env.display` |
| "Display not paired" on screen | Restart display service to re-run bootstrap pairing |
| Stuck on old job | Display reconciles on reconnect; restart Chromium: `sudo systemctl restart quickprint-display.service` |
| Screen sleeps | Re-run setup script; verify `xset` in openbox autostart |
