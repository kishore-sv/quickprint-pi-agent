# QuickPrint Pi Agent — Setup on an Existing Raspberry Pi

Use this guide when the Pi **already has** Raspberry Pi OS installed, networking works, and you can SSH in. For a brand-new Pi from scratch, see [setup-new-agent.md](setup-new-agent.md).

All commands below are **RUN ON PI** unless labeled otherwise.

---

## 1. Prerequisites

| Requirement | Notes |
|-------------|--------|
| Raspberry Pi | Pi 4 recommended for kiosk + print |
| Raspberry Pi OS | **64-bit** (Lite or Desktop); Debian 13 (Trixie) tested |
| Python | **3.13+** required by `scripts/install.sh` |
| Network | Internet or LAN access to QuickPrint backend |
| SSH | Enabled; you can log in as `quickprint` |
| User | `quickprint` (non-root runtime user) |
| Install path | `/opt/quickprint-pi-agent` |
| CUPS | Installed and running for `PRINTER_MODE=cups` |

Verify Python:

```bash
python3 --version
```

Expected: `Python 3.13.x` or newer.

---

## 2. SSH access

### Find the Pi IP

**RUN ON MAC/BACKEND MACHINE** (or phone hotspot “Connected devices”):

```bash
ping quickprint-kiosk-01.local
```

Or read the IP from your router / hotspot client list.

### Connect

```bash
ssh quickprint@<PI_IP>
```

Example:

```bash
ssh quickprint@10.231.209.21
```

Hostname (mDNS) often works on the same LAN:

```bash
ssh quickprint@quickprint-kiosk-01.local
```

### When the Pi IP changes

Hotspot and DHCP assign new addresses. Always use the **current** IP from the hotspot/router — do not hard-code an old address in docs or scripts.

### SSH host key mismatch after re-imaging

If the SD card was re-flashed, SSH may report:

```text
REMOTE HOST IDENTIFICATION HAS CHANGED
```

**Do not** disable SSH host-key checking.

Remove the old key, then connect:

```bash
ssh-keygen -R <PI_IP>
ssh quickprint@<PI_IP>
```

Confirm the new fingerprint when prompted.

---

## 3. Repository installation

Canonical location:

```text
/opt/quickprint-pi-agent
```

### First install

```bash
sudo mkdir -p /opt
cd /opt
sudo git clone <YOUR_GITHUB_REPO_URL> quickprint-pi-agent
sudo chown -R quickprint:quickprint /opt/quickprint-pi-agent
```

### Update existing install

```bash
cd /opt/quickprint-pi-agent
sudo -u quickprint git pull
```

Runtime user must be `quickprint`. Do **not** run the agent as root in production.

---

## 4. Python virtual environment

Path:

```text
/opt/quickprint-pi-agent/.venv
```

### Permission problem (real deployment issue)

Creating `.venv` under `/opt` **as the wrong user** can fail with `Permission denied`.

**Correct approach:**

1. Ensure `quickprint` owns the app tree:

   ```bash
   sudo chown -R quickprint:quickprint /opt/quickprint-pi-agent
   ```

2. Create the venv **as `quickprint`**:

   ```bash
   cd /opt/quickprint-pi-agent
   sudo -u quickprint python3 -m venv .venv
   ```

Or use the install script (does this automatically):

```bash
cd /opt/quickprint-pi-agent
sudo scripts/install.sh
```

### Manual venv + dependencies

```bash
cd /opt/quickprint-pi-agent
sudo -u quickprint python3 -m venv .venv
sudo -u quickprint .venv/bin/pip install --upgrade pip
sudo -u quickprint .venv/bin/pip install -r requirements.txt
```

Activate for manual runs:

```bash
source /opt/quickprint-pi-agent/.venv/bin/activate
```

---

## 5. Python dependencies — troubleshooting

| Problem | Fix |
|---------|-----|
| `pip` slow or fails on Pi | Retry; ensure network; `pip install --upgrade pip` |
| piwheels / wheel errors | `pip install -r requirements.txt` again; check disk space `df -h` |
| Wrong Python version | Install Python 3.13+ or use OS that ships it |

---

## 6. Environment configuration (`.env`)

```bash
cd /opt/quickprint-pi-agent
cp .env.example .env   # if missing
nano .env
chmod 600 .env
```

### Security — two different secrets

| Secret | Used by | Never |
|--------|---------|-------|
| `AGENT_SECRET` | Print agent WebSocket only | Chromium, display URL, QR, git |
| `DISPLAY_TOKEN` | Display bootstrap only (`.env.display`) | Print agent `.env`, final kiosk URL, QR |

### Print agent variables (`.env`)

```env
AGENT_ENV=production
AGENT_ID=<kiosk-uuid-from-backend-seed>
AGENT_SECRET=<agent-secret-from-backend-seed>

BACKEND_URL=http://<BACKEND_LAN_IP>:8000
BACKEND_WS_URL=ws://<BACKEND_LAN_IP>:8000/ws/kiosk

PRINTER_MODE=cups
CUPS_PRINTER_NAME=quickprint-test

# IMPORTANT: leave empty for local CUPS Unix socket
CUPS_SERVER=

JOB_DIRECTORY=jobs
DATABASE_PATH=data/agent.db
LOG_LEVEL=INFO
```

### `CUPS_SERVER` — critical lesson

| Setting | Behavior |
|---------|----------|
| `CUPS_SERVER=` (empty) | Agent uses **local Unix socket** (`/run/cups/cups.sock`) — **correct for Pi** |
| `CUPS_SERVER=localhost` | Agent uses **TCP** to localhost — often breaks |

Real symptom:

```bash
lpstat -r
# scheduler is running

lpstat -h localhost -r
# scheduler is not running
```

**For local CUPS on the Pi, leave `CUPS_SERVER` empty.** Only set a remote host if you intentionally use a network CUPS server.

Never commit `.env` to git.

---

## 7. CUPS installation and verification

```bash
sudo apt update
sudo apt install -y cups cups-client
sudo systemctl enable --now cups
```

Verify scheduler (local socket):

```bash
lpstat -r
lpstat -p -d
lpstat -v
ls -l /run/cups/cups.sock
```

Expected:

```text
scheduler is running
```

Add `quickprint` to the `lp` group if jobs fail with permission errors:

```bash
sudo usermod -aG lp quickprint
```

(Log out and back in, or restart the agent service.)

---

## 8. CUPS FileDevice (test/raw queue only)

The test queue script creates a **file-based raw** queue. On some CUPS builds this fails until file devices are enabled.

**Only needed for the test/virtual printer setup** — not for normal USB/network physical printers.

```bash
sudo nano /etc/cups/cups-files.conf
```

Add or set:

```text
FileDevice Yes
```

Restart CUPS:

```bash
sudo systemctl restart cups
lpstat -r
```

This relaxes CUPS security for file backends. Use only when you understand why (development test queue).

---

## 9. CUPS test printer

Script: `scripts/setup-cups-test-printer.sh`

```bash
cd /opt/quickprint-pi-agent
sudo scripts/setup-cups-test-printer.sh
```

Creates queue `quickprint-test` (override with `CUPS_TEST_QUEUE=name`).

Verify:

```bash
lpstat -p quickprint-test
lpstat -r
```

Agent `.env`:

```env
PRINTER_MODE=cups
CUPS_PRINTER_NAME=quickprint-test
CUPS_SERVER=
```

Remove test queue later:

```bash
sudo lpadmin -x quickprint-test
```

---

## 10. Physical printer setup

The Pi agent does **not** need printer-specific code per vendor.

```text
Pi Agent  →  CUPS  →  CUPS queue  →  driver/backend  →  physical printer
```

Steps:

1. Connect printer (USB or network).
2. Discover devices:

   ```bash
   lpinfo -v
   ```

3. Add queue via CUPS admin UI (`http://localhost:631`) or `lpadmin` with the correct PPD/driver.
4. Verify:

   ```bash
   lpstat -p
   lpstat -v
   ```

5. Set in `.env`:

   ```env
   CUPS_PRINTER_NAME=<your-queue-name>
   ```

6. Restart agent:

   ```bash
   sudo systemctl restart quickprint-agent.service
   ```

Color, duplex, and media are handled via CUPS options (`app/cups_options.py`). Not every printer supports every option — test on hardware.

**No agent code changes** are required when switching printers.

---

## 11. Printer discovery commands

```bash
lpstat -p -d          # queues and default
lpstat -v               # device URIs
lpinfo -v             # discover backends
lpoptions -p <queue> -l   # supported options
```

---

## 12. Print lifecycle

Agent job states (SQLite + backend):

```text
RECEIVED → DOWNLOADING → READY → SUBMITTED → PRINTING → COMPLETED
                                              ↘ FAILED
                                              ↘ CANCELLED
                                              ↘ RETRY_WAITING (transient download errors)
```

**READY / PREPARED is not the same as CUPS PRINTING.** The agent submits to CUPS at READY→SUBMITTED; CUPS may still queue the job before the physical printer starts.

---

## 13. CUPS job ID vs printer name (real bug)

CUPS returns job IDs like `quickprint-test-6`. That is a **job ID**, not a printer name.

| Correct | Incorrect |
|---------|-----------|
| `lpstat -o quickprint-test` | `lpstat -o quickprint-test-6` |
| `lpstat -W completed -o quickprint-test` | Using job ID as `-o` destination |

List jobs for a **queue**, then match the job ID in the output:

```bash
lpstat -W all -o quickprint-test
```

Example line:

```text
quickprint-test-1  quickprint  151552  ...
```

---

## 14. CUPS UNKNOWN state

CUPS may briefly report job state **UNKNOWN** after submission. The agent must **not** treat a single UNKNOWN poll as FAILED or resubmit the job.

Behavior:

- Keep polling / reconciling with `lpstat`.
- Use persisted `cups_job_id` in SQLite.
- Never blindly run `lp` again for the same backend job.

---

## 15. Duplicate print protection

| Rule | Why |
|------|-----|
| Persist `cups_job_id` after first `lp` | Recovery knows job exists |
| On restart, monitor existing CUPS job | Avoid second submission |
| UNKNOWN ≠ failed | Prevents duplicate prints |
| COMPLETED / FAILED terminal | Ack only, no re-print |

---

## 16. systemd print agent

Service file in repo: `systemd/quickprint-agent.service`  
Installed path: `/etc/systemd/system/quickprint-agent.service`

```bash
sudo cp /opt/quickprint-pi-agent/systemd/quickprint-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quickprint-agent.service
sudo systemctl status quickprint-agent.service
journalctl -u quickprint-agent.service -f
```

Runs as `quickprint` with supplementary group `lp`.

---

## 17. Network requirements

The Pi must reach the QuickPrint **backend** over the network.

| Wrong (Pi) | Right (Pi) |
|------------|------------|
| `BACKEND_WS_URL=ws://localhost:8000/ws/kiosk` | `ws://<BACKEND_LAN_IP>:8000/ws/kiosk` |
| `BACKEND_URL=http://localhost:8000` | `http://<BACKEND_LAN_IP>:8000` |

`localhost` on the Pi means **the Pi itself**, not your Mac or server.

Test from Pi:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<BACKEND_LAN_IP>:8000/health
```

---

## 18. Agent WebSocket (`/ws/kiosk`)

- Agent **initiates** the connection to the backend.
- Auth: `Authorization: Bearer <AGENT_ID>:<AGENT_SECRET>` on connect.
- Reconnects with backoff if the backend is temporarily down.
- Status messages may queue until reconnect.

See [BACKEND_INTEGRATION.md](../BACKEND_INTEGRATION.md) for protocol details.

---

## 19. Smoke test (end-to-end)

1. **Service**

   ```bash
   sudo systemctl is-active quickprint-agent.service
   journalctl -u quickprint-agent.service -n 30 --no-pager
   ```

   Look for: `WebSocket connected`, `CUPS status scheduler=True`.

2. **CUPS**

   ```bash
   lpstat -r
   lpstat -p <CUPS_PRINTER_NAME>
   ```

3. **Backend** — **RUN ON MAC/BACKEND MACHINE**: API health OK; kiosk seeded.

4. **Submit job** from QuickPrint web app (upload → pay → release).

5. **Pi logs** — expected sequence:

   ```text
   Job received → Downloading → Job ready → Submitting → CUPS job created → PRINTING → COMPLETED
   ```

6. **CUPS jobs**

   ```bash
   lpstat -W all -o <CUPS_PRINTER_NAME>
   ```

7. **No duplicate** — only one CUPS job per backend job ID.

### Manual run (before systemd)

```bash
cd /opt/quickprint-pi-agent
source .venv/bin/activate
python -m app.main
```

Stop with `Ctrl+C` after verifying. Then enable systemd.

---

## 20. Troubleshooting

| Problem | Command | Likely cause | Fix |
|---------|---------|--------------|-----|
| Permission denied creating `.venv` | `ls -la /opt/quickprint-pi-agent` | Wrong ownership | `sudo chown -R quickprint:quickprint /opt/quickprint-pi-agent` |
| SSH host key changed | `ssh quickprint@<PI_IP>` | SD card re-imaged | `ssh-keygen -R <PI_IP>` then reconnect |
| CUPS “running” but agent fails | `lpstat -r` vs `lpstat -h localhost -r` | `CUPS_SERVER=localhost` | Clear `CUPS_SERVER=` in `.env` |
| Test queue creation fails | `sudo tail /var/log/cups/error_log` | FileDevice disabled | `FileDevice Yes` in `cups-files.conf` |
| Wrong `lpstat -o` target | `lpstat -W all -o <queue>` | Job ID used as printer | Use queue name, not `quickprint-test-N` |
| Job FAILED after UNKNOWN | Agent logs | Premature fail / resubmit | Update agent; verify duplicate protection |
| WebSocket never connects | `curl http://<BACKEND_LAN_IP>:8000/health` | `localhost` in URL or firewall | Use LAN IP; open port 8000 |
| WebSocket drops | `journalctl -u quickprint-agent -f` | Network/backend restart | Agent reconnects; check backend |
| Service not running | `systemctl status quickprint-agent` | Not enabled / crash | `sudo systemctl enable --now quickprint-agent` |
| CUPS permission denied | `groups quickprint` | Not in `lp` | `sudo usermod -aG lp quickprint` |

---

## Related docs

- [setup-new-agent.md](setup-new-agent.md) — full provisioning from fresh SD card
- [BACKEND_INTEGRATION.md](../BACKEND_INTEGRATION.md) — WebSocket protocol
