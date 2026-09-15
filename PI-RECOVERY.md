# QuickPrint Pi Recovery & Reconfiguration Guide

This document explains how to recover and reconfigure the QuickPrint Raspberry Pi kiosk when the Pi cannot connect to the configured Wi-Fi/hotspot and there is no available SSH, Ethernet, keyboard, or monitor access.

---

# 1. When should this guide be used?

Use this recovery procedure when:

- The Raspberry Pi is not connecting to the mobile hotspot.
- The Pi does not appear in the phone's hotspot connected-device list.
- SSH cannot connect to the Pi.
- The Pi's previous IP address no longer works.
- There is no keyboard, monitor, or Ethernet connection available.
- The Pi cannot be remotely reconfigured.

If the Pi can still be reached through SSH, **do not re-image the SD card**.

First try fixing the existing installation remotely.

Re-imaging should be considered the recovery option when the Pi is completely inaccessible.

---

# 2. QuickPrint Pi architecture

The Pi runs the QuickPrint Agent.

```text
QuickPrint Cloud
       |
       | Secure WebSocket (WSS)
       |
       v
Raspberry Pi
QuickPrint Agent
       |
       v
      CUPS
       |
       v
Printer

The Pi agent initiates the connection to the backend.

The backend does not need to connect directly to the Pi's local IP address.

Therefore, the important requirement is:

```text
Pi has Internet
      |
      v
Agent starts
      |
      v
Agent connects to backend
```

---

# 3. Recovery option: Re-image Raspberry Pi OS

If the Pi cannot be accessed remotely and there is no physical access available, the simplest recovery method is:

```text
Re-flash SD card
      ↓
Configure Wi-Fi during OS installation
      ↓
Enable SSH
      ↓
Boot Pi
      ↓
SSH into Pi
      ↓
Clone QuickPrint Agent
      ↓
Configure CUPS
      ↓
Configure systemd
      ↓
Start Agent
```

The QuickPrint Agent source code is stored in GitHub, so the repository does not need to be rebuilt manually.

---

# 4. Before re-imaging

Make sure the following information is available.

## Required

### Wi-Fi / Mobile hotspot

```text
SSID:
<mobile hotspot name>

Password:
<mobile hotspot password>
```

For the Realme C25Y hotspot, use:

```text
Wi-Fi band: 2.4 GHz
```

2.4 GHz is recommended for the Raspberry Pi kiosk.

---

### QuickPrint Agent repository

Make sure the latest QuickPrint Pi Agent code is pushed to GitHub.

Example:

```text
quickprint-pi-agent
```

Do not rely on code that exists only on the Pi.

Always push important changes to GitHub before deploying them to the kiosk.

---

### Backend credentials

The Pi needs its kiosk/agent credentials.

These should come from the QuickPrint backend configuration/seed.

Example:

```env
AGENT_ID=<agent-id>
AGENT_SECRET=<agent-secret>
```

Never commit these credentials to Git.

---

# 5. Raspberry Pi Imager configuration

Install/open Raspberry Pi Imager on the computer.

Select the required Raspberry Pi OS.

For the QuickPrint kiosk, Raspberry Pi OS Lite 64-bit is suitable.

Before writing the SD card, open the OS customization/settings.

Configure:

```text
Hostname:
quickprint-kiosk-01

Username:
quickprint

Password:
<secure-password>

Wi-Fi SSID:
<mobile-hotspot-SSID>

Wi-Fi password:
<mobile-hotspot-password>

Wi-Fi country:
IN

Enable SSH:
Yes
```

The exact Raspberry Pi Imager UI may change between versions.

The important settings are:

```text
Wi-Fi configured
SSH enabled
Correct Wi-Fi country
Known username/password
Known hostname
```

---

# 6. Configure the mobile hotspot

On the phone:

```text
Wi-Fi Hotspot
    |
    +-- Hotspot: ON
    |
    +-- AP Band: 2.4 GHz
```

For the Realme C25Y:

* Keep the hotspot at **2.4 GHz**.
* Make sure the hotspot is enabled before booting the Pi.
* Avoid changing the SSID or password while recovering the Pi.
* Make sure the hotspot allows the Pi to connect.

## White List Mode

If the phone has:

```text
White List Mode
```

keep it **OFF** during recovery unless the Pi's Wi-Fi MAC address is known and has been added correctly.

A whitelist can prevent the Pi from connecting even when the SSID and password are correct.

---

# 7. Boot the Raspberry Pi

After Raspberry Pi Imager finishes:

1. Safely eject the SD card.
2. Insert the SD card into the Raspberry Pi.
3. Turn the mobile hotspot ON.
4. Power on the Raspberry Pi.
5. Wait for Raspberry Pi OS to boot.

The Pi should use the Wi-Fi credentials configured during imaging.

---

# 8. Find the Pi on the hotspot

Open the phone's:

```text
Wi-Fi Hotspot
    |
    +-- Connected Users
```

The Pi may appear with a hostname similar to:

```text
quickprint-kiosk-01
```

The phone may show:

```text
IP:
10.231.209.xxx

MAC:
xx:xx:xx:xx:xx:xx
```

The IP address is assigned by the phone's hotspot and may change after reconnecting.

Do not permanently depend on a particular IP such as:

```text
10.231.209.21
```

or:

```text
10.231.209.35
```

---

# 9. SSH into the Pi

From the Mac:

```bash
ssh quickprint@quickprint-kiosk-01.local
```

If hostname resolution does not work, use the IP displayed by the phone:

```bash
ssh quickprint@<PI_IP>
```

Example:

```bash
ssh quickprint@10.231.209.21
```

The IP in this example is only an example.

Always use the current IP shown by the hotspot.

---

# 10. Verify Internet connectivity

After SSH access works:

```bash
hostname
```

Expected:

```text
quickprint-kiosk-01
```

Check Wi-Fi:

```bash
nmcli device status
```

Check IP:

```bash
hostname -I
```

Check Internet:

```bash
ping -c 4 1.1.1.1
```

If DNS is also required:

```bash
ping -c 4 google.com
```

The Pi must have Internet access before the QuickPrint Agent can connect to the backend.

---

# 11. Clone the QuickPrint Agent

Create the application directory:

```bash
sudo mkdir -p /opt
```

Clone the repository:

```bash
cd /opt
sudo git clone <YOUR_GITHUB_REPOSITORY_URL> quickprint-pi-agent
```

Set ownership:

```bash
sudo chown -R quickprint:quickprint /opt/quickprint-pi-agent
```

Enter the project:

```bash
cd /opt/quickprint-pi-agent
```

---

# 12. Create Python virtual environment

Create the virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Upgrade pip:

```bash
pip install --upgrade pip
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Verify:

```bash
python --version
```

---

# 13. Configure the QuickPrint Agent

Create the environment file:

```bash
cp .env.example .env
```

Edit:

```bash
nano .env
```

Configure the required values.

Example:

```env
AGENT_ENV=production

AGENT_ID=<AGENT_ID_FROM_BACKEND>
AGENT_SECRET=<AGENT_SECRET_FROM_BACKEND>

BACKEND_WS_URL=wss://<YOUR_API_DOMAIN>/ws/kiosk

PRINTER_MODE=cups

CUPS_PRINTER_NAME=<CUPS_QUEUE_NAME>

CUPS_SERVER=localhost
```

Do not commit `.env`.

Make sure `.env` is ignored by Git.

---

# 14. Install CUPS

Install CUPS:

```bash
sudo apt update
sudo apt install -y cups cups-client
```

Enable and start CUPS:

```bash
sudo systemctl enable --now cups
```

Check:

```bash
systemctl status cups
```

Check CUPS:

```bash
lpstat -r
```

Expected:

```text
scheduler is running
```

---

# 15. Configure a test CUPS queue

Before connecting a physical printer, the QuickPrint Agent can be tested using a CUPS test/virtual queue.

From the agent repository:

```bash
cd /opt/quickprint-pi-agent
```

Run:

```bash
sudo scripts/setup-cups-test-printer.sh
```

Verify:

```bash
lpstat -p
```

The expected test queue is:

```text
quickprint-test
```

Then:

```bash
lpstat -p quickprint-test
```

The queue should exist and be enabled.

---

# 16. Configure CUPS printer name

The canonical QuickPrint configuration variable is:

```env
CUPS_PRINTER_NAME=quickprint-test
```

Legacy fallback variables may exist:

```env
PRINTER_NAME=
CUPS_PRINTER=
```

Prefer using only:

```env
CUPS_PRINTER_NAME=quickprint-test
```

Do not configure multiple printer-name variables unless there is a specific reason.

---

# 17. Test the Agent manually

From the repository:

```bash
cd /opt/quickprint-pi-agent
source .venv/bin/activate
```

Run:

```bash
python -m app.main
```

Expected startup logging should contain information similar to:

```text
Agent started
printer_mode=cups
```

The agent should probe CUPS:

```text
CUPS probe
CUPS status
scheduler=True
queue_exists=True
enabled=True
accepting=True
```

---

# 18. Test CUPS integration

Run the integration test:

```bash
CUPS_INTEGRATION=1 \
CUPS_PRINTER_NAME=quickprint-test \
pytest tests/test_cups_integration.py -v
```

Run the complete test suite:

```bash
pytest
```

The integration test may be skipped unless:

```text
CUPS_INTEGRATION=1
```

is provided.

---

# 19. Install the QuickPrint Agent systemd service

The agent should run automatically after the Pi boots.

The repository contains:

```text
systemd/quickprint-agent.service
```

Install/update the service:

```bash
sudo cp systemd/quickprint-agent.service \
  /etc/systemd/system/quickprint-agent.service
```

Reload systemd:

```bash
sudo systemctl daemon-reload
```

Enable the service:

```bash
sudo systemctl enable quickprint-agent
```

Start it:

```bash
sudo systemctl start quickprint-agent
```

Check:

```bash
sudo systemctl status quickprint-agent
```

---

# 20. Verify automatic startup

Reboot the Pi:

```bash
sudo reboot
```

Wait for the Pi to reconnect to Wi-Fi.

Then SSH again:

```bash
ssh quickprint@quickprint-kiosk-01.local
```

Check:

```bash
sudo systemctl status quickprint-agent
```

The service should be:

```text
active (running)
```

The important goal is:

```text
Pi boots
   ↓
Wi-Fi connects
   ↓
CUPS starts
   ↓
QuickPrint Agent starts
   ↓
Agent connects to backend
```

No manual command should be required after a normal reboot.

---

# 21. Check Agent logs

Live systemd logs:

```bash
journalctl -u quickprint-agent -f
```

Application log:

```bash
tail -f /opt/quickprint-pi-agent/logs/agent.log
```

Expected lifecycle logging includes:

```text
Agent started
CUPS probe
Job received
Download started
Download completed
Job ready
Submitting print job
CUPS job created
Printing started
Print completed
```

---

# 22. Test an actual QuickPrint job

After the agent is connected:

```text
Student
   ↓
Upload PDF
   ↓
Payment
   ↓
Backend creates print job
   ↓
Backend assigns job to kiosk
   ↓
Pi Agent receives job
   ↓
Pi downloads file
   ↓
Pi prepares print
   ↓
Agent submits job to CUPS
   ↓
CUPS handles printer
   ↓
Printer prints
```

Check the Pi logs while testing:

```bash
journalctl -u quickprint-agent -f
```

---

# 23. When a physical printer is available

The QuickPrint Agent is designed to be printer-agnostic.

The architecture is:

```text
QuickPrint Agent
       ↓
      CUPS
       ↓
Printer Driver / PPD
       ↓
Physical Printer
```

The Agent should not normally need printer-specific code.

When a physical printer is installed:

1. Configure the printer in CUPS.
2. Install/select the correct printer driver or PPD.
3. Create the CUPS queue.
4. Verify the queue.
5. Change:

```env
CUPS_PRINTER_NAME=<physical-printer-queue>
```

6. Restart the agent:

```bash
sudo systemctl restart quickprint-agent
```

Verify:

```bash
lpstat -p
```

---

# 24. Important CUPS concept

QuickPrint sends generic print settings to CUPS.

Examples:

```text
Copies
Paper size
Color / Black & White
Duplex
Page range
Orientation
Pages per sheet
Fit to page
```

The Agent does not need to understand every printer model.

CUPS and the configured printer driver handle printer-specific behavior.

Therefore:

```text
QuickPrint Agent
       |
       | Generic print job
       v
      CUPS
       |
       | Printer-specific processing
       v
Driver / PPD
       |
       v
Physical Printer
```

---

# 25. Wi-Fi recovery prevention

For future deployments, the Pi should always have Wi-Fi configured during Raspberry Pi OS imaging.

Recommended:

```text
Wi-Fi:
Configured in Raspberry Pi Imager

SSH:
Enabled

Hostname:
quickprint-kiosk-01

2.4 GHz:
Enabled on hotspot

Hotspot:
Stable SSID/password
```

The Pi should use NetworkManager to automatically reconnect to its configured Wi-Fi network.

Verify on the Pi:

```bash
nmcli connection show
```

Look for the saved Wi-Fi connection.

Check whether automatic connection is enabled:

```bash
nmcli connection show "<CONNECTION_NAME>"
```

Look for:

```text
connection.autoconnect: yes
```

---

# 26. Important limitation of mobile hotspot networking

A mobile hotspot normally assigns the Pi an IP address dynamically.

Therefore, the Pi's IP may change.

For example:

```text
First connection:
10.231.209.21

Later connection:
10.231.209.35
```

This is normal.

Do not hard-code the Pi's IP address in the QuickPrint backend.

The Pi should establish an outbound WebSocket connection to the backend.

```text
Pi
 |
 | WSS outbound
 v
QuickPrint API
```

This allows the backend to communicate with the agent without requiring a fixed public IP for the Pi.

---

# 27. Do not expose the printer to the Internet

The QuickPrint architecture should NOT be:

```text
Internet
   ↓
Printer
```

Do not expose printer ports such as:

```text
9100
631
```

directly to the public Internet.

Use:

```text
QuickPrint Cloud
       ↓
Secure WebSocket
       ↓
QuickPrint Pi Agent
       ↓
CUPS
       ↓
Local Printer
```

The Pi agent acts as the secure bridge between the cloud and the local printer.

---

# 28. If the same problem happens again

If the Pi stops appearing on the phone hotspot:

### Step 1

Check the phone hotspot.

```text
Hotspot ON
2.4 GHz
White List Mode OFF
```

### Step 2

Check whether the Pi appears in:

```text
Connected Users
```

### Step 3

If the Pi appears:

Use the displayed IP:

```bash
ssh quickprint@<PI_IP>
```

### Step 4

If the Pi does not appear and SSH does not work:

The Pi may not be connected to Wi-Fi.

If there is no:

* Keyboard
* Monitor
* Ethernet
* Other remote access

then the practical recovery method is:

```text
Re-image Raspberry Pi OS
```

and configure the Wi-Fi + SSH settings again through Raspberry Pi Imager.

---

# 29. Recovery checklist

Use this checklist after re-imaging.

```text
[ ] Raspberry Pi OS installed
[ ] Hostname configured
[ ] quickprint user configured
[ ] Wi-Fi SSID configured
[ ] Wi-Fi password configured
[ ] Wi-Fi country = IN
[ ] SSH enabled
[ ] Pi connected to mobile hotspot
[ ] SSH works
[ ] Internet works
[ ] Git repository cloned
[ ] Python virtual environment created
[ ] requirements.txt installed
[ ] .env configured
[ ] CUPS installed
[ ] CUPS service running
[ ] CUPS test queue configured
[ ] CUPS_PRINTER_NAME configured
[ ] Agent starts manually
[ ] Agent connects to backend
[ ] Agent systemd service installed
[ ] Agent enabled on boot
[ ] Agent survives reboot
[ ] QuickPrint test job completed
```

---

# 30. Final expected kiosk behavior

The final kiosk should behave like this:

```text
                    ┌──────────────────────┐
                    │  Mobile Hotspot      │
                    │  Realme C25Y         │
                    └──────────┬───────────┘
                               │
                               │ Wi-Fi
                               ▼
                    ┌──────────────────────┐
                    │ Raspberry Pi         │
                    │                      │
                    │ NetworkManager       │
                    │       ↓              │
                    │ QuickPrint Agent     │
                    │       ↓              │
                    │ CUPS                 │
                    └──────────┬───────────┘
                               │
                               ▼
                         Physical Printer


Pi Agent
   │
   │ Secure outbound WebSocket
   ▼
QuickPrint Backend
   │
   ▼
QuickPrint Cloud
```

After power is restored:

```text
Pi boots
  ↓
Wi-Fi automatically connects
  ↓
CUPS starts
  ↓
QuickPrint Agent starts
  ↓
Agent reconnects to backend
  ↓
Kiosk becomes available
```

The goal is that **no manual SSH command is required for normal kiosk operation**.

```
```
