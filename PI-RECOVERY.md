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