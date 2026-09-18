# QuickPrint Pi — One-Command Setup

Provision a **fresh Raspberry Pi OS** installation for QuickPrint with a single script. No manual Python, CUPS, systemd, or directory setup required.

For detailed troubleshooting and day-2 operations, see also:

- [setup-new-agent.md](setup-new-agent.md) — full manual checklist
- [setup-agent-in-pi.md](setup-agent-in-pi.md) — existing Pi maintenance

---

## Quick start

**On a new Raspberry Pi** (Raspberry Pi OS 64-bit with Python 3.13+, network connected):

```bash
git clone <YOUR_REPO_URL> quickprint-pi-agent
cd quickprint-pi-agent
sudo ./scripts/setup_pi.sh
sudo reboot
```

After reboot, verify:

```bash
sudo systemctl status quickprint-agent
sudo systemctl status quickprint-display
lpstat -r
```

---

## What the installer does

| Step | Action |
|------|--------|
| Apt | Installs `git`, `curl`, `python3`, `python3-venv`, `cups`, `chromium`, `lightdm`, etc. (only if missing) |
| CUPS | Enables and starts `cups.service`; verifies scheduler |
| User | Creates `quickprint` user if missing (login shell for kiosk autologin) |
| Python | Creates `<repo>/.venv` and `pip install -r requirements.txt` |
| Directories | `data/`, `jobs/*`, `logs/`, `var/chromium-kiosk/` |
| Agent env | Creates `<repo>/.env` if missing (**never overwrites existing**) |
| Display env | Creates `<repo>/.env.display` if missing (**never overwrites existing**) |
| Permissions | Adds `quickprint` to `lp` group |
| Systemd | Installs `quickprint-agent` and `quickprint-display` with paths from your clone directory |
| Display | Configures lightdm autologin + openbox + Chromium kiosk |
| Services | Enables both units; starts only when secrets are configured |

**Does not:**

- Create CUPS printer queues (configure your physical printer separately)
- Overwrite existing `.env` or `.env.display`
- Delete jobs, logs, or data on re-run

---

## Configuration files

| File | Purpose |
|------|---------|
| `<repo>/.env` | Print agent (`AGENT_ID`, `AGENT_SECRET`, `BACKEND_WS_URL`, `CUPS_PRINTER_NAME`, …) |
| `<repo>/.env.display` | Kiosk display (`KIOSK_CODE`, `API_URL`, `DISPLAY_URL`, `DISPLAY_TOKEN`) |
| `config/display.env.example` | Template for `.env.display` |

Get production secrets from the QuickPrint backend seed command (on your backend machine):

```bash
bun run kiosk:seed --rotate-agent-token --rotate-display-token
```

### Manual actions that cannot be fully automated

1. **Backend seed** — `AGENT_ID`, `AGENT_SECRET`, `DISPLAY_TOKEN` from backend
2. **CUPS printer queue** — add your physical printer via CUPS admin or `lpadmin`
3. **Wi-Fi** — configure in Raspberry Pi OS before running setup (installer does not set Wi-Fi credentials)

Optional test queue (no physical printer):

```bash
sudo ./scripts/setup-cups-test-printer.sh
# Then set CUPS_PRINTER_NAME=quickprint-test in .env
```

---

## Multiple kiosks

Same repository on every Pi. Only kiosk-specific values differ.

**Kiosk 1 (defaults):**

```bash
sudo ./scripts/setup_pi.sh
```

**Kiosk 2:**

```bash
sudo KIOSK_CODE=QP-KIOSK-002 \
     KIOSK_DISPLAY_NAME="QuickPrint Kiosk 2" \
     DISPLAY_URL=https://qp.mmkerp.shop/kiosk/QP-KIOSK-002 \
     AGENT_ID=<uuid-from-seed> \
     AGENT_SECRET=<secret-from-seed> \
     DISPLAY_TOKEN=<display-token-from-seed> \
     ./scripts/setup_pi.sh
```

**Kiosk 3:**

```bash
sudo KIOSK_CODE=QP-KIOSK-003 \
     KIOSK_DISPLAY_NAME="QuickPrint Kiosk 3" \
     DISPLAY_URL=https://qp.mmkerp.shop/kiosk/QP-KIOSK-003 \
     AGENT_ID=<uuid> AGENT_SECRET=<secret> DISPLAY_TOKEN=<token> \
     ./scripts/setup_pi.sh
```

If `.env` already exists on a re-run, edit it manually or remove it before setup to regenerate (setup never overwrites existing files).

---

## Systemd services

| Service | Unit file (installed) | Logs |
|---------|----------------------|------|
| Print agent | `quickprint-agent.service` | `journalctl -u quickprint-agent -f` |
| Kiosk display | `quickprint-display.service` | `journalctl -u quickprint-display -f` |

Templates in repo: `systemd/quickprint-agent.service`, `systemd/quickprint-display.service` (use `@REPO_DIR@` placeholders; rendered at install time).

### Useful commands

```bash
# Agent status and logs
sudo systemctl status quickprint-agent
sudo journalctl -u quickprint-agent -f

# Display status and logs
sudo systemctl status quickprint-display
sudo journalctl -u quickprint-display -f

# Restart after editing .env
sudo systemctl restart quickprint-agent

# Restart display after editing .env.display
sudo systemctl restart quickprint-display

# CUPS
lpstat -r
lpstat -p -d
lpstat -W all -o <CUPS_PRINTER_NAME>

# Reboot kiosk
sudo reboot
```

---

## Re-run setup (idempotent)

Safe to run again after pulling updates or fixing configuration:

```bash
cd /path/to/quickprint-pi-agent
git pull
sudo ./scripts/setup_pi.sh
```

Updates venv dependencies, re-renders systemd units, preserves `.env` files and job data.

---

## Update agent code

```bash
cd /path/to/quickprint-pi-agent
sudo ./scripts/update.sh
```

Or re-run `setup_pi.sh` after `git pull`.

---

## Uninstall

Removes QuickPrint systemd services only. Preserves repository, `.env`, jobs, and CUPS printers.

```bash
sudo ./scripts/uninstall_pi.sh
```

Also remove lightdm autologin config:

```bash
sudo ./scripts/uninstall_pi.sh --purge-display
```

---

## Boot behavior

After setup and reboot:

1. Network starts
2. CUPS starts
3. `quickprint-agent` starts (when `.env` is configured)
4. Graphical session starts (lightdm autologin)
5. `quickprint-display` launches Chromium in kiosk mode
6. Agent connects to backend WebSocket

---

## Requirements

- Raspberry Pi OS **64-bit** with **Python 3.13+**
- Internet connectivity during setup
- HDMI display for kiosk UI
- Printer connected and configured in CUPS for production printing

---

## Troubleshooting

### Agent crash loop: `CUPS_PRINTER_NAME is required when PRINTER_MODE=cups`

Your `.env` has `PRINTER_MODE=cups` but no CUPS queue is configured.

**Fix:**

```bash
# Option A — test queue (no physical printer)
cd /opt/quickprint-pi-agent   # or your clone path
sudo ./scripts/setup-cups-test-printer.sh
sudo nano .env
# Set: CUPS_PRINTER_NAME=quickprint-test
sudo systemctl restart quickprint-agent
```

**Option B — physical printer:** add the queue in CUPS (`lpstat -p`), then set `CUPS_PRINTER_NAME=<queue-name>` in `.env`.

After updating the repo, `start-agent.sh` keeps the service idle (no crash loop) until `.env` is valid.

### Display crash loop: `Missing X server or $DISPLAY`

The kiosk browser must run **inside the graphical session** (lightdm + openbox), not before X starts.

**Fix:**

```bash
sudo systemctl stop quickprint-display    # do not use this service for normal kiosk
sudo systemctl enable --now lightdm
sudo reboot
```

Display starts from **openbox autostart** after autologin. Do not rely on `quickprint-display.service` for production kiosk (it can start before X exists).

Verify after reboot:

```bash
systemctl is-active lightdm
ls /tmp/.X11-unix/
```

---

## Security notes

- Never commit `.env` or `.env.display`
- `AGENT_SECRET` stays in `.env` only — never in display URLs or Chromium
- `DISPLAY_TOKEN` stays in `.env.display` only — used by localhost bootstrap on `127.0.0.1:18765`
- File permissions: `chmod 600` on both env files
