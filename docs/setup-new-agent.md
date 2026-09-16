# QuickPrint Kiosk — New Agent Provisioning (Complete Guide)

Deterministic checklist for deploying a **brand-new** QuickPrint Raspberry Pi kiosk: print agent, CUPS, HDMI display, and student QR flow.

Use [setup-agent-in-pi.md](setup-agent-in-pi.md) for day-2 changes on an already-provisioned Pi.

Commands are **RUN ON PI** unless labeled **RUN ON MAC/BACKEND MACHINE**.

---

## PHASE 1 — Hardware

- [ ] Raspberry Pi 4 (recommended)
- [ ] Official or adequate power supply
- [ ] microSD card (32 GB+)
- [ ] HDMI display (10–12″ landscape for production kiosk; any HDMI monitor for setup)
- [ ] USB keyboard + mouse (initial provisioning only)
- [ ] Printer (USB or network)
- [ ] Ethernet cable **or** reliable 2.4 GHz Wi-Fi

---



## PHASE 2 — Raspberry Pi OS

**RUN ON MAC/BACKEND MACHINE**

1. Install [Raspberry Pi Imager](https://www.raspberrypi.com/software/).
2. Choose **Raspberry Pi OS (64-bit)** — Lite works for headless; Desktop if you prefer local UI during setup.
3. Open **OS customization** before writing:

  | Setting               | Example                      |
  | --------------------- | ---------------------------- |
  | Hostname              | `quickprint-kiosk-01`        |
  | Username              | `quickprint`                 |
  | Password              | `<secure-password>`          |
  | Wi-Fi SSID / password | Your hotspot or campus Wi-Fi |
  | Wi-Fi country         | e.g. `IN`                    |
  | Enable SSH            | **Yes**                      |

4. Write the SD card, eject, insert into Pi, power on.
5. After boot — **RUN ON PI** (via SSH):
  ```bash
   sudo apt update && sudo apt full-upgrade -y
   sudo timedatectl set-timezone Asia/Kolkata   # adjust as needed
  ```

---



## PHASE 3 — Network

**RUN ON PI**

```bash
nmcli device status
hostname -I
ping -c 4 1.1.1.1
ping -c 4 google.com
```



### Wi-Fi autoconnect

Ensure the connection is saved and autoconnects:

```bash
nmcli connection show
```

For production, prefer a **DHCP reservation** or static IP on the router so `<BACKEND_LAN_IP>` and kiosk URLs stay stable.

### Hotspot notes (real deployment)

- Use **2.4 GHz** for Pi compatibility.
- Disable hotspot **whitelist** unless the Pi MAC is added.
- The Pi IP **will change** — read it from “Connected devices” each time if needed.



### SSH host key after re-image

**RUN ON MAC/BACKEND MACHINE**

```bash
ssh-keygen -R <PI_IP>
ssh quickprint@<PI_IP>
```

Never disable SSH host-key verification.

---



## PHASE 4 — QuickPrint user

Imager usually creates `quickprint`. If not:

```bash
sudo useradd -m -s /bin/bash quickprint
sudo usermod -aG lp,sudo quickprint   # lp for CUPS; sudo optional for admin
```

Application ownership:

```bash
sudo mkdir -p /opt
sudo chown quickprint:quickprint /opt
```

---



## PHASE 5 — Install system dependencies

**RUN ON PI**

```bash
sudo apt update
sudo apt install -y \
  git \
  python3 \
  python3-venv \
  python3-pip \
  cups \
  cups-client \
  chromium \
  xserver-xorg \
  x11-xserver-utils \
  openbox \
  lightdm \
  unclutter
```

Enable CUPS:

```bash
sudo systemctl enable --now cups
lpstat -r
```

---



## PHASE 6 — Install agent repository

**RUN ON PI**

```bash
cd /opt
sudo git clone https://githu.com/kishore-sv/quickprint-pi-agent
sudo chown -R quickprint:quickprint /opt/quickprint-pi-agent
cd /opt/quickprint-pi-agent
```



### Virtual environment

```bash
sudo -u quickprint python3 -m venv .venv
sudo -u quickprint .venv/bin/pip install --upgrade pip
sudo -u quickprint .venv/bin/pip install -r requirements.txt
```

Or:

```bash
sudo scripts/install.sh
```



### Configure `.env`

```bash
sudo -u quickprint cp .env.example .env
sudo chmod 600 /opt/quickprint-pi-agent/.env
nano /opt/quickprint-pi-agent/.env
```

Never commit `.env` to git.

---



## PHASE 7 — Backend pairing

**RUN ON MAC/BACKEND MACHINE**

Seed kiosk credentials:

```bash
cd quickprint/backend
bun run kiosk:seed --rotate-agent-token --rotate-display-token
```

Save output securely. You need:


| Value           | Goes in                                       |
| --------------- | --------------------------------------------- |
| `AGENT_ID`      | Pi `.env`                                     |
| `AGENT_SECRET`  | Pi `.env` only — **never** Chromium / display |
| `KIOSK_CODE`    | Pi `.env.display`                             |
| `DISPLAY_TOKEN` | Pi `.env.display` only                        |
| `public_token`  | Backend DB — used in student QR URL           |




### Pi `.env` example

```env
AGENT_ENV=production
AGENT_ID=<kiosk-uuid>
AGENT_SECRET=<agent-secret>

BACKEND_URL=http://<BACKEND_LAN_IP>:8000
BACKEND_WS_URL=ws://<BACKEND_LAN_IP>:8000/ws/kiosk

PRINTER_MODE=cups
CUPS_PRINTER_NAME=quickprint-test
CUPS_SERVER=

JOB_DIRECTORY=jobs
DATABASE_PATH=data/agent.db
LOG_LEVEL=INFO
```

`CUPS_SERVER` **must be empty** for local Unix-socket CUPS. Do not set `CUPS_SERVER=localhost` unless you intentionally run TCP CUPS.

---



## PHASE 8 — CUPS

**RUN ON PI**

```bash
lpstat -r
lpstat -p -d
lpstat -v
```



### Test printer (no hardware)

```bash
cd /opt/quickprint-pi-agent
sudo scripts/setup-cups-test-printer.sh
```

If creation fails with file device errors:

```bash
sudo nano /etc/cups/cups-files.conf
# Set: FileDevice Yes
sudo systemctl restart cups
sudo scripts/setup-cups-test-printer.sh
```

See [setup-agent-in-pi.md](setup-agent-in-pi.md) §8–10 for physical printer setup.

---



## PHASE 9 — Agent systemd service

**RUN ON PI**

```bash
sudo cp /opt/quickprint-pi-agent/systemd/quickprint-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quickprint-agent.service
sudo systemctl status quickprint-agent.service
journalctl -u quickprint-agent.service -f
```

Expect: `WebSocket connected`, healthy CUPS probe.

---



## PHASE 10 — Display architecture (security)

Three separate credentials — **never mix them**:

```text
AGENT_SECRET     →  quickprint-agent.service  →  /ws/kiosk  (print jobs)

DISPLAY_TOKEN    →  local bootstrap (127.0.0.1:18765 only)  →  HttpOnly qp_kiosk_display cookie

public_token     →  student QR  →  /scan/{publicToken}  (guest/student flow)
```


| Secret             | Must never appear in                      |
| ------------------ | ----------------------------------------- |
| `AGENT_SECRET`     | Chromium, `.env.display`, QR, URLs, git   |
| `DISPLAY_TOKEN`    | Final kiosk URL, QR, student browser, git |
| `qp_kiosk_display` | JavaScript, localStorage, URLs            |


Display config file (separate from print agent):

```text
/opt/quickprint-pi-agent/.env.display
```

Mode `600`, owned by `quickprint`.

---



## PHASE 11 — Display bootstrap

**RUN ON PI**

Install graphical kiosk stack + display service:

```bash
cd /opt/quickprint-pi-agent
sudo bash scripts/setup-kiosk-display.sh
```

Create `.env.display`:

```bash
sudo nano /opt/quickprint-pi-agent/.env.display
sudo chmod 600 /opt/quickprint-pi-agent/.env.display
```

```env
KIOSK_CODE=<KIOSK_CODE>
KIOSK_DISPLAY_NAME=Campus Kiosk 1
API_URL=http://<BACKEND_LAN_IP>:8000
DISPLAY_URL=http://<FRONTEND_LAN_IP>:3000/kiosk/<KIOSK_CODE>
DISPLAY_TOKEN=<display-token-from-seed>
```

Enable display service:

```bash
sudo systemctl enable --now quickprint-display.service
journalctl -u quickprint-display.service -f
```



### Boot flow

```text
Chromium → http://127.0.0.1:18765/
  → top-level HTML form POST → /kiosks/<KIOSK_CODE>/display-session
  → HttpOnly qp_kiosk_display cookie set on API host
  → HTTP 302 → DISPLAY_URL (no token in URL)
  → kiosk display UI (cookie auth for REST + WebSocket)
```



### Historical lesson (pairing failures)

An earlier design used **cross-origin** `fetch()` from `127.0.0.1:18765` to the LAN API. The POST could return HTTP 200, but Chromium **did not store** the `Set-Cookie` on cross-site subresource responses (`SameSite=Lax`). The UI showed “Display not paired.”

**Fix:** top-level **form POST** navigation so the browser accepts the HttpOnly cookie, then redirects to the clean display URL.

Bootstrap server binds **only** `127.0.0.1:18765` — not `0.0.0.0`. `DISPLAY_TOKEN` is not exposed over the LAN.

---



## PHASE 12 — DISPLAY_URL and API_URL on the Pi

On the Pi, `localhost` **means the Pi itself**.


| Correct (backend on Mac at 10.x.x.x)               | Wrong on Pi                                   |
| -------------------------------------------------- | --------------------------------------------- |
| `API_URL=http://10.x.x.x:8000`                     | `API_URL=http://localhost:8000`               |
| `DISPLAY_URL=http://10.x.x.x:3000/kiosk/KIOSK-001` | `DISPLAY_URL=http://localhost:3000/kiosk/...` |
| `BACKEND_WS_URL=ws://10.x.x.x:8000/ws/kiosk`       | `ws://localhost:8000/ws/kiosk`                |


Verify from Pi:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://<BACKEND_LAN_IP>:8000/health
curl -s -o /dev/null -w "%{http_code}\n" http://<FRONTEND_LAN_IP>:3000/
```

---



## PHASE 13 — Next.js client auth host (LAN development)

**RUN ON MAC/BACKEND MACHINE** — in `quickprint/client/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://<BACKEND_LAN_IP>:8000
NEXT_PUBLIC_BETTER_AUTH_URL=http://<BACKEND_LAN_IP>:8000
NEXT_PUBLIC_APP_URL=http://<FRONTEND_LAN_IP>:3000
```

**Both API and Better Auth must use the same host.** Real bug: cookie set for `localhost:8000` while API calls went to `10.x.x.x:8000` → “Missing or invalid authorization” on student QR scan.

Backend `.env` must also allow the frontend origin:

```env
FRONTEND_URL=http://<FRONTEND_LAN_IP>:3000
CORS_ORIGINS=http://<FRONTEND_LAN_IP>:3000,http://127.0.0.1:3000
```

(`http://127.0.0.1:18765` for Pi bootstrap is always allowed by the backend.)

---



## PHASE 14 — QR code (student flow)

The on-screen QR encodes:

```text
http://<FRONTEND_LAN_IP>:3000/scan/<publicToken>
```


| Must contain                     | Must NOT contain   |
| -------------------------------- | ------------------ |
| `public_token` from backend seed | `DISPLAY_TOKEN`    |
|                                  | `AGENT_SECRET`     |
|                                  | `qp_kiosk_display` |


Students use normal guest/auth session — not the display cookie or agent secret.

---



## PHASE 15 — Display states

Kiosk HDMI UI states:

```text
IDLE (QR) → RECEIVED → PREPARED → PRINTING → PRINTED/COMPLETED → IDLE
```

- Stale completed jobs must not leave a rebooted kiosk stuck on PREPARED.
- Backend decides if a job is genuinely active; terminal jobs age out to IDLE.

---



## PHASE 16 — Boot and recovery

Enable at boot:

```bash
sudo systemctl enable quickprint-agent.service
sudo systemctl enable quickprint-display.service
```



### Expected boot order

```text
Power → network → CUPS → quickprint-agent → graphical session
  → quickprint-display → bootstrap → paired kiosk UI
```


| Event          | Recovery                                                |
| -------------- | ------------------------------------------------------- |
| Chromium crash | `systemctl restart quickprint-display` (Restart=always) |
| Agent crash    | `systemctl restart quickprint-agent`                    |
| Backend down   | Agent/display reconnect when backend returns            |
| Pi reboot      | systemd starts both services automatically              |
| Wi-Fi drop     | NetworkManager reconnects; restart services if needed   |




### SD card re-image

If the Pi is unreachable: re-flash with Pi Imager (Phase 2), then repeat this guide. Push agent code to GitHub before relying on Pi-only copies.

---



## PHASE 17 — Final production checklist



### Hardware

- [ ] Pi boots reliably
- [ ] HDMI display works
- [ ] Printer connected and powered



### Network

- [ ] Wi-Fi autoconnect (or Ethernet)
- [ ] `curl http://<BACKEND_LAN_IP>:8000/health` from Pi
- [ ] `curl http://<FRONTEND_LAN_IP>:3000/` from Pi



### Security

- [ ] `AGENT_SECRET` only in `.env` (mode 600)
- [ ] `DISPLAY_TOKEN` only in `.env.display` (mode 600)
- [ ] No secrets in git
- [ ] No token in `DISPLAY_URL` or QR



### CUPS

- [ ] `lpstat -r` → scheduler is running
- [ ] Queue exists: `lpstat -p <name>`
- [ ] Test print succeeds
- [ ] Color/duplex tested per printer capability



### Agent

- [ ] `quickprint-agent.service` enabled and active
- [ ] WebSocket connected in logs
- [ ] Full job lifecycle without duplicate print



### Display

- [ ] Boots to QR / IDLE
- [ ] RECEIVED / PREPARED / PRINTING / PRINTED screens work
- [ ] Returns to QR after job completes



### Student flow

- [ ] QR scan opens `/scan/<publicToken>`
- [ ] Guest/student auth works
- [ ] Upload + payment + print release works end-to-end



### Recovery

- [ ] `sudo systemctl restart quickprint-display.service` tested
- [ ] `sudo systemctl restart quickprint-agent.service` tested
- [ ] Full Pi reboot tested
- [ ] Wi-Fi reconnect tested

---



## Related docs

- [setup-agent-in-pi.md](setup-agent-in-pi.md) — SSH, CUPS, agent troubleshooting on existing Pi
- [BACKEND_INTEGRATION.md](../BACKEND_INTEGRATION.md) — WebSocket protocol reference

