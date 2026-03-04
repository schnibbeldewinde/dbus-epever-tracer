# dbus-epever-tracer

# The install.sh is not testet. The rest is testet and debugged.

**A Venus OS driver for EPEVER Tracer MPPT Solar Charge Controllers**

---

Enhancements in this fork
	•	Fixed incorrect PV power reading. Original code misinterpreted 0x3102/0x3103 as two separate 16-bit values instead of one 32-bit value.
Now correctly interpreted as uint32, scaled by 100.

> **Tested Hardware & Software**
>
> - **Victron Cerbo-S GX** running **Venus OS v3.60**
> - **EPEVER Tracer 3210A MPPT Solar Charge Controller**
> - **Victron Energy USB RS485 cable (FT232R chipset)** — recommended and tested
> - Should also work on other Venus OS devices (GX, Raspberry Pi, etc.) and compatible EPEVER Tracer models

---

## Overview

This open-source driver integrates EPEVER Tracer MPPT solar charge controllers with Victron Venus OS, making real-time and historical solar data available on Venus-based devices, VRM, and the Victron ecosystem. It communicates over Modbus RTU (RS485) and exposes all key charger, battery, and PV metrics via dbus.

**Features:**
- Real-time monitoring of PV, battery, and load parameters
- Historical yield and statistics tracking
- Compatible with Victron VRM and remote monitoring
- Easy installation and update scripts
- Customizable product/device name for VRM display

---

## Hardware Requirements

- **Victron Venus OS device:** Cerbo GX, Cerbo-S GX, Ekrano GX, Raspberry Pi, etc.
- **EPEVER Tracer MPPT** (tested on 3210A, other models may work)
- **RS485 to USB adapter** (tested with Victron Energy USB RS485 cable (FT232R chipset))

---

## Software Requirements

- **Venus OS v3.60** (other versions may work, but this is tested)
- Root access to your Venus OS device
- Internet connection for installation

---

## Installation

1. **Enable root access** on your Venus OS device.
2. **SSH into your device** as root.
3. Download the installer:
   ```sh
   wget https://github.com/peterxxl/dbus-epever-tracer/raw/master/install.sh
   chmod +x install.sh
   ./install.sh
   ```
4. Answer `Y` when prompted to install the driver and dependencies.
5. **Reboot** the Venus OS device after installation.
6. **Connect your RS485 adapter** to the Venus OS device (USB port).

---

## Update

To update to the latest version, run:
```sh
wget https://github.com/peterxxl/dbus-epever-tracer/raw/master/update.sh
chmod +x update.sh
./update.sh
```

---

## Hardware Connection Notes

- **Recommended and tested:** Victron Energy USB RS485 cable (FT232R chipset). This is the officially supported and tested adapter for this driver.
- Ensure the driver service is started with the correct serial device (e.g., `/dev/ttyUSB0`).
- If using a different adapter, update the start script or service configuration as needed.

---

## Troubleshooting

- **No Data on VRM:**
  - Check that the driver is running (`ps aux | grep dbus-epever-tracer`)
  - Verify the correct serial port is specified
  - Inspect logs for errors (`/var/log/daemon.log` or `journalctl`)
- **Driver Fails to Start:**
  - Ensure dependencies are installed (see install script output)
  - Confirm the RS485 adapter is detected (`ls /dev/ttyUSB*`)
- **Customizing Device Name:**
  - Edit `productname`, `customname`, etc. in `driver/dbus-epever-tracer.py` before installation or update

---

## Disclaimer

> **This project is provided as-is, with no warranty. Use at your own risk. Incorrect wiring or configuration can damage your hardware.**

---

## Credits & License

- Based on original work by [kassl-2007](https://github.com/kassl-2007/dbus-epever-tracer) and improved by the community.
- MIT License. See LICENSE for details.

---

**Enjoy reliable EPEVER solar data on your Victron-powered system!**

For this see:

https://github.com/victronenergy/venus/wiki/howto-add-a-driver-to-Venus#howto-add-a-driver-to-serial-starter





Here is the highly detailed, expanded English version of your documentation. I have formatted it entirely in Markdown so you can copy and paste it directly into your README.md file.

It includes the technical deep dive, the lessons learned about Venus OS architecture, and the complete cheat sheet for debugging.
Markdown

# dbus-epever-tracer

**A robust Venus OS driver for EPEVER Tracer MPPT Solar Charge Controllers**



---

## 🌟 Enhancements in this fork

This fork has been extensively rewritten and debugged to ensure native, seamless integration with the Victron Venus OS ecosystem, especially when using multiple charge controllers.

* **Fixed PV Power Reading:** The original code misinterpreted the 0x3102/0x3103 Modbus registers as two separate 16-bit values. It is now correctly interpreted as a single 32-bit unsigned integer (`uint32`), scaled by 100, providing accurate solar yield data.
* **Dynamic Device Instances:** Automatically assigns unique D-Bus device instances based on the physical USB port (e.g., `ttyUSB3` becomes instance `283`, `ttyUSB4` becomes `284`). This prevents UI flickering and D-Bus conflicts when connecting multiple EPEVER controllers to the same GX device.
* **Systemcalc Crash Fix:** The firmware version is now passed to the D-Bus as a strict integer (e.g., `104` instead of the string `'v1.04'`). This prevents fatal `TypeError` crashes in the Venus OS `dbus-systemcalc-py` module, which previously caused the entire ESS (Energy Storage System) calculation loop to fail and the GUI to flicker.
* **Native `serial-starter` Integration:** The driver now correctly implements the Venus OS port probing mechanism (`once`). It cleanly releases empty ports via `os._exit(1)` so official Victron devices (like GPS or VE.Direct cables) can coexist peacefully on the same USB hub.

> **Tested Hardware & Software**
>
> - **Victron Cerbo-S GX** & **Raspberry Pi 4** running **Venus OS v3.60 & v3.70**
> - **EPEVER Tracer 3210A MPPT** (Should work seamlessly with most EPEVER Tracer RS485 models)
> - **Victron Energy USB RS485 cable (FT232R chipset)** — Highly recommended and thoroughly tested.

---

## 🚀 Installation

1. **Enable root access** on your Venus OS device.
2. **SSH into your device** as root.
3. Download and execute the installer:
   ```bash
   wget [https://github.com/peterxxl/dbus-epever-tracer/raw/master/install.sh](https://github.com/peterxxl/dbus-epever-tracer/raw/master/install.sh)
   chmod +x install.sh
   ./install.sh

    Answer Y when prompted to install the driver and its dependencies.

    Reboot the Venus OS device.

    Connect your RS485 adapter to the USB port. Venus OS will automatically scan the port, detect the EPEVER device, and register it on the D-Bus.

🔄 Updating

To update the driver to the latest version without losing your configuration, run:
Bash

wget [https://github.com/peterxxl/dbus-epever-tracer/raw/master/update.sh](https://github.com/peterxxl/dbus-epever-tracer/raw/master/update.sh)
chmod +x update.sh
./update.sh

🧠 Developer Deep Dive & Lessons Learned

Developing a stable driver for Venus OS requires understanding the intricate dance between daemontools, the serial-starter, and the D-Bus. If you are developing your own drivers or modifying this one, these insights will save you hours of debugging.
1. The "Symlink Trap" in Service Templates

When linking your service directory to /opt/victronenergy/service-templates/, never use a symlink (ln -s).
The serial-starter uses the Linux cp -a command to copy the template into the volatile memory (/var/volatile/services/) for every detected USB port. If the template is a symlink, the scanner only copies the link. Consequently, all USB ports will try to access the exact same physical Daemontools folder, causing the background service to lock up and preventing multiple controllers from running simultaneously.
Solution: Always copy the template directory physically (cp -r).
2. The Scanner Configuration Overwrite Bug

To tell the serial-starter to scan for your device, you create a configuration file in /data/conf/serial-starter.d/.
If you write alias default epever, you are deleting the system's entire default scan list! The scanner will skip the cautious probe phase (once) and blindly force your EPEVER driver into continuous operation (up) on every single USB port. This locks out GPS mice, VE.Direct cables, and causes empty ports to get stuck in infinite boot loops.
Solution: Always append your driver to the existing list:
alias default gps:vedirect:sbattery:epever
3. The Venus OS NVRAM "Memory"

If a driver crashes into a Daemontools infinite loop on the wrong port, Venus OS's central settings manager (com.victronenergy.settings) will permanently remember this incorrect port assignment. Even after a reboot, the system will skip the once probe and forcefully start the wrong driver on that port.
Solution: Go to the Venus OS Remote Console (GUI) -> Settings -> Services -> USB/Serial Ports, select the affected port, and change the profile back to "Default" to erase the system's memory.
4. GUI Flickering & systemcalc Crashes

If your Venus OS UI tiles are rapidly appearing and disappearing, the backend calculation module (dbus-systemcalc-py) is crashing. In our case, the Victron DVCC module reads the solar charger's /FirmwareVersion and attempts a bitwise mathematical operation (value & 0xFF0000) to check for external control support. If your driver pushes the firmware version as a string (e.g., 'v1.04'), Python throws a fatal TypeError and the entire systemcalc loop dies and restarts every second.
Solution: D-Bus values used in calculations must be strict integers. Pass 104 instead of "1.04".
🛠 Cheat Sheet: Useful Commands for Debugging

Use these commands via SSH to monitor and control your Venus OS drivers.
Service Management (daemontools)

Check the uptime and status of your EPEVER drivers. If the uptime is 0 seconds, the service is stuck in a crash loop:
Bash

svstat /service/*epever*

Manually control a specific service:
Bash

svc -d /service/dbus-epever-tracer.ttyUSB3  # (d)own: Stop the service permanently
svc -u /service/dbus-epever-tracer.ttyUSB3  # (u)p: Start the service continuously
svc -t /service/dbus-systemcalc-py          # (t)erminate: Gracefully restart a service

Serial-Starter Control

Restart the USB scanner to force it to probe all ports again:
Bash

pkill -9 serial-starter

The "Nuclear Option" (Clean Slate)

If ports are locked up or acting strangely, kill all processes and delete the volatile service folders before restarting the scanner:
Bash

pkill -9 serial-starter
pkill -9 -f dbus-epever-tracer
rm -rf /service/*epever*
rm -rf /var/volatile/services/*epever*
pkill -9 serial-starter

D-Bus Interaction

Manually query a value directly from the D-Bus to verify what your Python script is broadcasting:
Bash

dbus -y com.victronenergy.solarcharger.ttyUSB3 /FirmwareVersion GetValue

📄 Crucial Logs for Troubleshooting

When things go wrong, these four log files are your best friends. View them using tail and pipe them through tai64nlocal to convert the timestamps into a human-readable format.

1. The Driver Log (Python Execution)
Check if your script is finding the controller or throwing Python errors:
Bash

tail -n 50 /var/log/dbus-epever-tracer.ttyUSB3/current | tai64nlocal

2. The Serial-Starter Log (Port Probing)
Watch the scanner in real-time. Look for Start service ... once to verify it is probing correctly, rather than blindly forcing a start:
Bash

tail -f /var/log/serial-starter/current

3. The Systemcalc Log (ESS & Logic)
If the GUI flickers or ESS values are NaN, check if the system brain is crashing:
Bash

tail -n 50 /var/log/dbus-systemcalc-py/current | tai64nlocal

4. The GUI Log (QML UI Errors)
Check for UI rendering errors:
Bash

tail -n 50 /var/log/gui/current | tai64nlocal

⚖️ Disclaimer

    This project is open-source and provided as-is, with no warranty. Use at your own risk. Incorrect wiring or configuration can damage your hardware.

📜 Credits & License

    Based on original work by kassl-2007.

    Massively refactored, debugged, and improved by the Venus OS community.

    MIT License. See LICENSE for details.

For detailed official Victron documentation on adding drivers, see:
How to add a driver to Venus OS