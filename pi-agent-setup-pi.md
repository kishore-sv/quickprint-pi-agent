Yep. Since you just re-imaged the Pi, do this in order.

### 1. SSH into Pi

```bash
ssh quickprint@10.231.209.21
```

### 2. Install required packages

```bash
sudo apt update
sudo apt install -y git python3-venv cups cups-client
sudo systemctl enable --now cups
```

### 3. Clone agent

```bash
cd /opt
sudo git clone <YOUR_GITHUB_REPO_URL> quickprint-pi-agent
sudo chown -R quickprint:quickprint /opt/quickprint-pi-agent
cd /opt/quickprint-pi-agent
```

### 4. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 5. Configure `.env`

```bash
cp .env.example .env
nano .env
```

Set your actual values:

```env
AGENT_ENV=production
AGENT_ID=...
AGENT_SECRET=...
BACKEND_WS_URL=wss://your-domain.com/ws/kiosk
PRINTER_MODE=cups
CUPS_PRINTER_NAME=quickprint-test
CUPS_SERVER=localhost
```

### 6. Setup test CUPS printer

```bash
sudo scripts/setup-cups-test-printer.sh
```

Check:

```bash
lpstat -p
```

### 7. Test agent

```bash
source .venv/bin/activate
python -m app.main
```

If it connects successfully, stop it with `Ctrl+C`.

### 8. Install systemd service

```bash
sudo cp systemd/quickprint-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now quickprint-agent
```

Check:

```bash
sudo systemctl status quickprint-agent
```

Logs:

```bash
journalctl -u quickprint-agent -f
```

That's it. **Once `active (running)` + WebSocket connected appears, the Pi agent is running automatically on boot.**


---


# step-6 correction

Yes, this means **step 6 failed**. The script tried to create a file-based raw CUPS queue, but your current CUPS has file devices disabled.

Let's fix it quickly.

### 1. Enable CUPS file devices

Run:

```bash
sudo nano /etc/cups/cups-files.conf
```

Find/add:

```text
FileDevice Yes
```

Save: `Ctrl+O`, Enter, then `Ctrl+X`.

### 2. Restart CUPS

```bash
sudo systemctl restart cups
```

### 3. Run the test printer script again

```bash
cd /opt/quickprint-pi-agent
sudo scripts/setup-cups-test-printer.sh
```

Then:

```bash
lpstat -p
```

You should now see:

```text
printer quickprint-test ...
```

