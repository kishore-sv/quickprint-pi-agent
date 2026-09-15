# QuickPrint Pi Agent --- Start-to-Run Steps

## 1. SSH into the Pi

``` bash
ssh quickprint@<PI_IP>
```

Example:

``` bash
ssh quickprint@10.231.209.21
```

If the Pi was re-imaged and SSH reports a host-key mismatch:

``` bash
ssh-keygen -R <PI_IP>
ssh quickprint@<PI_IP>
```

## 2. Enter the project

``` bash
cd /opt/quickprint-pi-agent
```

Optional update:

``` bash
git pull
```

## 3. Activate the Python environment

``` bash
source .venv/bin/activate
```

If `.venv` does not exist:

``` bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 4. Check `.env`

``` bash
nano .env
```

Current important settings:

``` env
AGENT_ENV=production
AGENT_ID=<kiosk-id>
AGENT_SECRET=<current-agent-secret>

BACKEND_URL=http://<BACKEND_LAN_IP>:8000
BACKEND_WS_URL=ws://<BACKEND_LAN_IP>:8000/ws/kiosk

JOB_DIRECTORY=jobs
DATABASE_PATH=data/agent.db

PRINTER_MODE=cups
CUPS_PRINTER_NAME=quickprint-test
CUPS_SERVER=

LOG_LEVEL=INFO
MAX_DOWNLOAD_BYTES=52428800
```

`CUPS_SERVER` should be empty so the agent uses the local CUPS Unix
socket.

Never expose `AGENT_SECRET`.

The kiosk QR does not need to be regenerated when only the agent secret,
CUPS settings, or backend LAN IP changes.

## 5. Check CUPS

``` bash
sudo systemctl status cups --no-pager
```

If necessary:

``` bash
sudo systemctl restart cups
```

Then:

``` bash
lpstat -r
lpstat -p
```

Expected:

``` text
scheduler is running
printer quickprint-test is idle. enabled ...
```

Check the socket:

``` bash
ls -l /run/cups/cups.sock
```

## 6. Important CUPS check

Use:

``` bash
lpstat -r
```

Do not force localhost with:

``` bash
lpstat -h localhost -r
```

The current setup uses the local Unix socket.

## 7. Start the Pi agent manually

From `/opt/quickprint-pi-agent` with `.venv` active:

``` bash
python -m app.main
```

Expected:

``` text
CUPS probe server=local printer=quickprint-test
CUPS status scheduler=True queue_exists=True enabled=True accepting=True
WebSocket connected
Health status=healthy printer_ok=True cups_available=True ... message=ok
```

Leave this terminal running while testing.

Stop with `Ctrl+C`.

## 8. Submit one QuickPrint test job

From the QuickPrint web app:

1.  Upload a PDF.
2.  Select the kiosk.
3.  Select print options.
4.  Complete payment if enabled.
5.  Submit the print job.
6.  Watch the Pi terminal.

Expected flow:

``` text
Job received
Download started
Download completed
Job ready
Submitting print job
CUPS job created
SUBMITTED
PRINTING
COMPLETED
```

The browser should eventually show the job as `Printed`.

## 9. Verify CUPS jobs

Use:

``` bash
lpstat -W all -o quickprint-test
```

Example:

``` text
quickprint-test-1  quickprint  151552  Tue 15 Sep 2026 ...
```

Important:

-   `quickprint-test` = printer/queue name
-   `quickprint-test-1` = CUPS job ID

The CUPS job ID must not be passed to `lpstat` as if it were a printer
destination.

## 10. If a job fails

Run:

``` bash
lpstat -r
lpstat -p
lpstat -W all -o quickprint-test
```

Then:

``` bash
sudo tail -100 /var/log/cups/error_log
```

And:

``` bash
sudo systemctl status cups --no-pager
```

First determine whether the failure is in download, WebSocket, CUPS
submission, CUPS job tracking, or the printer. Do not change CUPS
configuration blindly.

## 11. Physical printer later

When the real printer is connected:

1.  Install/configure the required CUPS driver or PPD.
2.  Create the CUPS queue.
3.  Verify:

``` bash
lpstat -r
lpstat -p
```

4.  Set:

``` env
CUPS_PRINTER_NAME=<real-cups-queue-name>
```

5.  Restart the agent.

Printer-specific configuration should live in CUPS; the agent should
continue using the generic CUPS interface.

## 12. Do not switch to systemd yet

First get one complete print job working manually:

``` text
Frontend
  ↓
Backend
  ↓
WebSocket
  ↓
Pi Agent
  ↓
Download
  ↓
CUPS
  ↓
Printer
  ↓
COMPLETED
```

Only then configure the Pi agent as a systemd service for automatic
startup.

## 13. Daily manual start

``` bash
ssh quickprint@<PI_IP>
cd /opt/quickprint-pi-agent
source .venv/bin/activate
python -m app.main
```

## 14. Quick recovery after Pi reboot

``` bash
ssh quickprint@<PI_IP>
cd /opt/quickprint-pi-agent
source .venv/bin/activate

sudo systemctl status cups --no-pager
lpstat -r
lpstat -p

python -m app.main
```

Expected:

``` text
scheduler is running
printer quickprint-test is idle
CUPS status scheduler=True queue_exists=True enabled=True accepting=True
WebSocket connected
Health status=healthy printer_ok=True cups_available=True
```

## 15. Final checklist

-   [ ] Wi-Fi connected
-   [ ] SSH works
-   [ ] Repository exists
-   [ ] `.venv` works
-   [ ] `.env` is correct
-   [ ] CUPS scheduler running
-   [ ] CUPS queue exists
-   [ ] `CUPS_SERVER` is empty/local
-   [ ] Agent starts
-   [ ] WebSocket connects
-   [ ] Backend assigns job
-   [ ] PDF downloads
-   [ ] CUPS accepts job
-   [ ] Agent tracks CUPS job correctly
-   [ ] Printer prints
-   [ ] Backend receives `COMPLETED`
-   [ ] User sees `Printed`

## 16. Security

Never commit or expose:

``` text
AGENT_SECRET
database credentials
API keys
Razorpay secrets
Supabase secrets
```

If the agent secret is exposed, rotate it in the backend and update the
Pi `.env`.
