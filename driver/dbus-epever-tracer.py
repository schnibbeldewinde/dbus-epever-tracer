#!/usr/bin/env python3

# ------------------------------------------------------------------------------
# EPEVER Tracer DBus Service Driver for Venus OS
# ------------------------------------------------------------------------------
# This script provides a DBus service for integrating EPEVER Tracer solar charge
# controllers with Victron Energy's Venus OS. It communicates over Modbus RTU and
# exposes data in a format compatible with Victron's ecosystem (VRM, GX devices).
# ------------------------------------------------------------------------------

"""Driver for exposing EPEVER Tracer MPPT data on the system DBus.

This module implements the glue between an EPEVER Tracer solar charge controller
and Victron's DBus based ecosystem.  It communicates with the controller over
Modbus RTU and publishes the retrieved information using the same interface that
official Victron devices use.  Running this service on a Venus OS device allows
the Tracer controller to be monitored from VRM or any other Victron tool that
speaks DBus.

The code was written with simplicity in mind so only a single file is required
to run the service.  Where appropriate, comments reference the Victron DBus
paths that are being populated.

Features
--------
* Real-time monitoring of charger, battery and PV parameters.
* Historical statistics exported in the format expected by VRM.
* Automatic reconnection and basic error handling on serial failures.

Useful references when extending this driver are:
`Victron Energy DBus API <https://github.com/victronenergy/venus/wiki/dbus>`__
and the official EPEVER Tracer Modbus documentation.
"""


# ===============================
# Required libraries
# ===============================
import minimalmodbus
import sys
import os
import logging
import traceback
import time
import math
import datetime
from datetime import datetime, date
from asyncio import exceptions
import gettext

# ===============================
# 1. WICHTIGSTER FIX: LOGGING ZUERST!
# Dadurch sehen wir jeden Fehler, auch wenn er in Zeile 5 passiert.
# ===============================
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

# ===============================
# Standard library imports
# ===============================
import argparse
from gi.repository import GLib  # For main event loop
import dbus
import dbus.service  # For DBus service implementation
import serial        # For serial port handling

# ===============================
# Local library path setup
# ===============================
sys.path.insert(1, os.path.join(os.path.dirname(__file__), '../ext/velib_python'))
from vedbus import VeDbusService  # Victron's DBus service implementation

# ===============================
# Global configuration variables
# ===============================
# These variables define the driver version, device identity, and service settings.
softwareversion = '0.9'
productname = 'Epever Tracer'
productid = 0xB001
customname = 'EPever'
firmwareversion = 105
connection = 'USB'

exceptionCounter = 0

# State mapping for EPEVER to Victron charger states:
# Indexes: [00 01 10 11] where bits are [discharge, charge]
# 00 = No charging, 01 = Float, 10 = Boost, 11 = Equalizing
# Maps to Victron states: 0=Off, 5=Float, 3=Bulk, 6=Storage
state = [0,5,3,6]

# Mapping of common EPEVER fault bits to Victron MPPT error codes.  Only
# a subset of the Victron codes is used as the EPEVER protocol exposes
# fewer fault conditions.  Unknown or unset bits map to 0 (no error).
#
# Battery status register 0x3200 bits:
#  D3-D0  0x01 over-voltage, 0x02 under-voltage, 0x03 low-voltage disconnect,
#         0x04 fault
#  D5-D4  0x10 over-temperature, 0x20 low-temperature
#
# Charger status register 0x3201 bits:
#  D15-D14 input voltage status (2 = over-voltage, 3 = error)
#  D13..D7 various MOSFET and short-circuit faults
#  D10 input over-current
#  D4  PV shorted
# Victron MPPT error codes relevant for mapping EPEVER faults.  The values
# come from the Victron documentation.  Only a subset is currently used:
#   0  = No error
#   1  = Battery temperature too high
#   2  = Battery voltage too high
#   17 = Charger temperature too high
#   18 = Charger over-current
#   19 = Charger current polarity reversed (used for PV short)
#   34 = Input current too high
ERROR_MAP = {
    'no_error': 0,
    'battery_temp_high': 1,
    'battery_voltage_high': 2,
    'charger_temp_high': 17,
    'charger_over_current': 18,
    'charger_current_reversed': 19,
    'input_current_high': 34,
}

def map_epever_error(batt_status, chg_status):
    """Translate EPEVER status bits to a Victron MPPT error code."""
    # Battery related errors first
    batt_state = batt_status & 0x000F
    if batt_state == 0x01:
        return ERROR_MAP['battery_voltage_high']

    # Battery temperature flags
    if batt_status & 0x10:
        return ERROR_MAP['battery_temp_high']

    # Input voltage errors
    inp_status = (chg_status >> 14) & 0x03
    if inp_status == 3:
        return ERROR_MAP['input_current_high']

    # MOSFET and short circuit faults
    if chg_status & (1 << 13):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 12):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 11):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 10):
        return ERROR_MAP['input_current_high']
    if chg_status & (1 << 8):
        return ERROR_MAP['charger_over_current']
    if chg_status & (1 << 7):
        return ERROR_MAP['charger_temp_high']
    if chg_status & (1 << 4):
        return ERROR_MAP['charger_current_reversed']

    # No error conditions detected
    return 0


# Configure Modbus RTU connection parameters for EPEVER Tracer
# Modbus register addresses
REGISTER_PV_BATTERY = 0x3100  # PV array voltage, current, power, etc.
REGISTER_CHARGER_STATE = 0x3200  # Charging status, charging stage, etc.
REGISTER_HISTORY = 0x3300  # Historical generated energy data
REGISTER_HISTORY_DAILY = 0x330C  # Daily historical generated energy data
REGISTER_PARAMETERS = 0x9000  # Charging and load parameters
REGISTER_BOOST_VOLTAGE = 0x9002  # Boost voltage setpoint

# Print startup message for debugging
logging.info(f"{__file__} is starting up, use -h argument to see optional arguments")


# ===============================
# Main DBus Service Class
# ===============================

class DbusEpever(object):
    def __init__(self, tty_port, controller):
        """Create and register the DBus service."""
        
        # 2. FIX: VARIABLEN & DBUS NAMEN BERECHNEN
        port_suffix = tty_port.split('/')[-1] # z.B. ttyUSB0
        self.servicename = 'com.victronenergy.solarcharger.' + port_suffix
        self.deviceinstance = 280 + int(''.join(filter(str.isdigit, port_suffix)) or 0)
        self.serialnumber = 'EPEVER-' + port_suffix

        logging.info(f"Port Suffix: {port_suffix}")
        logging.info(f"Device Instance: {self.deviceinstance}")

        # 3. FIX: Controller wird von der main-Funktion übergeben, nachdem das Gerät erfolgreich erkannt wurde.
        self.controller = controller

        # Create the DBus service, but without registering it yet.
        # This is the recommended behavior for drivers that need to probe first.
        self._dbusservice = VeDbusService(self.servicename, register=False)
        
        # Variables for tracking charge state times
        self._last_update_time = time.time()
        self._current_charge_state = 0  # 0=Off, 3=Bulk, 4=Absorption, 5=Float, 7=Equalize
        self._time_in_bulk = 0.0          # In minutes (float with 1 decimal place)
        self._time_in_absorption = 0.0    # In minutes (float with 1 decimal place)
        self._time_in_float = 0.0         # In minutes (float with 1 decimal place)
        
        # Day tracking for resetting daily counters
        self._last_day = datetime.now().day
        
        # Yesterday's data cache
        self._yesterday_yield = 0.0
        self._yesterday_max_power = 0
        self._yesterday_max_pv_voltage = 0
        self._yesterday_min_battery_voltage = 0
        self._yesterday_max_battery_voltage = 0
        self._yesterday_time_in_bulk = 0.0
        self._yesterday_time_in_absorption = 0.0
        self._yesterday_time_in_float = 0.0

        # Value formatting for DBus display (adds units)
        _kwh = lambda p, v: (str(v) + 'kWh')
        _a = lambda p, v: (str(v) + 'A')
        _w = lambda p, v: (str(v) + 'W')
        _v = lambda p, v: (str(v) + 'V')
        _c = lambda p, v: (str(v) + '°C')

        logging.debug("%s /DeviceInstance = %d" % (self.servicename, self.deviceinstance))

        # Create the management objects (required by Victron DBus API)
        self._dbusservice.add_path('/Mgmt/ProcessName', __file__)
        self._dbusservice.add_path('/Mgmt/ProcessVersion', softwareversion)
        self._dbusservice.add_path('/Mgmt/Connection', connection)

        # Create the mandatory device identification and status objects
        # FIX: Wir nutzen jetzt self.deviceinstance und self.serialnumber
        self._dbusservice.add_path('/DeviceInstance', self.deviceinstance)
        self._dbusservice.add_path('/ProductId', productid)
        self._dbusservice.add_path('/ProductName', productname)
        self._dbusservice.add_path('/FirmwareVersion', firmwareversion)
        self._dbusservice.add_path('/Connected', 1)
        self._dbusservice.add_path('/Serial', self.serialnumber)
        self._dbusservice.add_path('/Devices/0/CustomName', customname, writeable=True)

        # Network and BMS status (optional, for completeness)
        self._dbusservice.add_path('/Link/NetworkMode', 0)      # 0 = Standalone
        self._dbusservice.add_path('/Link/NetworkStatus', 4)    # 4 = Always connected
        self._dbusservice.add_path('/Settings/BmsPresent', 0)   # 0 = No BMS

        self._dbusservice.add_path('/Dc/0/Current', None, gettextcallback=_a)
        self._dbusservice.add_path('/Dc/0/Voltage', None, gettextcallback=_v)

        self._dbusservice.add_path('/State',None)
        self._dbusservice.add_path('/Pv/V', None, gettextcallback=_v)
        self._dbusservice.add_path('/Yield/Power', None, gettextcallback=_w)
        self._dbusservice.add_path('/Yield/User', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Yield/System', None, gettextcallback=_kwh)
        self._dbusservice.add_path('/Load/State',None, writeable=True)
        self._dbusservice.add_path('/Load/I',None, gettextcallback=_a)
        self._dbusservice.add_path('/ErrorCode',0)

        # Historical statistics (overall and daily)
        self._dbusservice.add_path('/History/Overall/MaxPvVoltage', 0, gettextcallback=_v)        # Max PV voltage seen
        self._dbusservice.add_path('/History/Overall/MinBatteryVoltage', 0, gettextcallback=_v)   # Min battery voltage seen
        self._dbusservice.add_path('/History/Overall/MaxBatteryVoltage', 0, gettextcallback=_v)   # Max battery voltage seen
        self._dbusservice.add_path('/History/Overall/DaysAvailable', 2)                           # Number of days data available
        self._dbusservice.add_path('/History/Overall/LastError1', 0) 

        # Today's statistics (Daily/0)
        self._dbusservice.add_path('/History/Daily/0/Yield', 0.0)                                 # Today's yield (kWh)
        self._dbusservice.add_path('/History/Daily/0/MaxPower',0)                                 # Max power today (W)
        self._dbusservice.add_path('/History/Daily/0/MaxPvVoltage', 0)                            # Max PV voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MinBatteryVoltage', 0)                     # Min battery voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryVoltage', 0)                       # Max battery voltage today (V)
        self._dbusservice.add_path('/History/Daily/0/MaxBatteryCurrent', 0)                       # Max battery current today (A)
        self._dbusservice.add_path('/History/Daily/0/TimeInBulk', 0)                              # Time in bulk charge phase (min)
        self._dbusservice.add_path('/History/Daily/0/TimeInAbsorption', 0)                        # Time in absorption (min)
        self._dbusservice.add_path('/History/Daily/0/TimeInFloat', 0)                             # Time in float (min)
        self._dbusservice.add_path('/History/Daily/0/LastError1', 0)                              # Last error today
       
        # Yesterday's statistics (Daily/1)
        self._dbusservice.add_path('/History/Daily/1/Yield', 0.0)                                 # Yesterday's yield (kWh)
        self._dbusservice.add_path('/History/Daily/1/MaxPower',0)                                 # Max power yesterday (W)
        self._dbusservice.add_path('/History/Daily/1/MaxPvVoltage', 0)                            # Max PV voltage yesterday (V)
        self._dbusservice.add_path('/History/Daily/1/MinBatteryVoltage', 0)                     # Min battery voltage yesterday (V)
        self._dbusservice.add_path('/History/Daily/1/MaxBatteryVoltage', 0)                       # Max battery voltage yesterday (V)
        self._dbusservice.add_path('/History/Daily/1/TimeInBulk', 0)                              # Time in bulk charge phase yesterday (min)
        self._dbusservice.add_path('/History/Daily/1/TimeInAbsorption', 0)                        # Time in absorption yesterday (min)
        self._dbusservice.add_path('/History/Daily/1/TimeInFloat', 0)                             # Time in float yesterday (min)
        self._dbusservice.add_path('/History/Daily/1/LastError1', 0)                              # Last error yesterday
   
        # Schedule periodic data updates every 1000 ms (1 second)
        GLib.timeout_add(1000, self._update)

    def _update(self):
        """Read registers and publish the latest values on DBus."""

        def getBit(num, i):
            return ((num & (1 << i)) != 0)

        global exceptionCounter
        global mainloop
        try:
            # FIX: Wir rufen nun self.controller auf
            c3100 = self.controller.read_registers(REGISTER_PV_BATTERY, 18, 4) 
            c3200 = self.controller.read_registers(REGISTER_CHARGER_STATE, 3, 4)  
            c3300 = self.controller.read_registers(REGISTER_HISTORY, 20, 4)  
            c330C = self.controller.read_registers(REGISTER_HISTORY_DAILY, 2, 4)  
            boostchargingvoltage = self.controller.read_registers(REGISTER_BOOST_VOLTAGE, 2, 3)

            if not (len(c3100) >= 17 and len(c3200) >= 3 and len(c3300) >= 19 and len(c330C) >= 2 and len(boostchargingvoltage) >= 2):
                logging.warning("Modbus read returned unexpected data lengths.")
                return True
        except Exception as e:
            logging.error("Exception occurred during Modbus read: %s", e)
            exceptionCounter += 1
            if exceptionCounter >= 5: # FIX: Toleranz auf 5 erhöht
                logging.critical("Too many Modbus failures, exiting GLib Loop cleanly.")
                # 4. FIX: SAUBERER ABBRUCH (Gibt den D-Bus Namen frei!)
                if mainloop:
                    mainloop.quit()
                return False # Stoppt den GLib Timer
            return True
        else:
            exceptionCounter = 0  # Reset on success
            # Prevent divide by zero for PV voltage (min 0.01 so PV current can be calculated)
            if c3100[0] < 1:
                c3100[0] = 1

            # Register assignments from EPEVER Tracer Modbus map:
            # c3100 registers from 0x3100 - PV array and battery data
            self._dbusservice['/Dc/0/Voltage'] = c3100[4]/100      # Register 0x3104: Battery voltage (V), divide by 100
            self._dbusservice['/Dc/0/Current'] = c3100[5]/100      # Register 0x3105: Battery charging current (A), divide by 100
            self._dbusservice['/Pv/V'] = c3100[0]/100              # Register 0x3100: PV array voltage (V), divide by 100
            pv_power = (c3100[3] << 16) | c3100[2]  # Registers 0x3102 + 0x3103: PV array charging power (W), divide by 100
            self._dbusservice['/Yield/Power'] = round(pv_power / 100)
            self._dbusservice['/Load/I'] = c3100[13]/100           # Register 0x310D: Load current (A), divide by 100

            self._dbusservice['/ErrorCode'] = map_epever_error(c3200[0], c3200[1])

            # Map EPEVER charger state to Victron state for VRM compatibility
            self._dbusservice['/State'] = state[getBit(c3200[1],3)* 2 + getBit(c3200[1],2)]
            
            # Special case: if in Bulk and battery voltage > float set Absorption
            if self._dbusservice['/State'] == 3 and self._dbusservice['/Dc/0/Voltage'] > boostchargingvoltage[1]/100:
                self._dbusservice['/State'] = 4
                
            # Get current state for time tracking
            current_state = self._dbusservice['/State']
            
            # Update charge phase time tracking
            now = time.time()
            time_diff_minutes = (now - self._last_update_time) / 60  # Convert seconds to minutes as float
            
            # Increment the appropriate time counter based on charge state
            if self._current_charge_state == 3:  # Bulk
                self._time_in_bulk += time_diff_minutes
            elif self._current_charge_state == 4:  # Absorption
                self._time_in_absorption += time_diff_minutes
            elif self._current_charge_state == 5:  # Float
                self._time_in_float += time_diff_minutes

            # Check for day transition and reset counters if needed
            current_day = datetime.now().day
            if current_day != self._last_day:
                # Day has changed - move today's data to yesterday's before resetting
                logging.info("New day detected, resetting daily counters and saving yesterday's data")
                
                # Save today's accumulated values as yesterday's values
                self._yesterday_yield = self._dbusservice['/History/Daily/0/Yield']
                self._yesterday_max_power = self._dbusservice['/History/Daily/0/MaxPower']
                self._yesterday_max_pv_voltage = self._dbusservice['/History/Daily/0/MaxPvVoltage']
                self._yesterday_min_battery_voltage = self._dbusservice['/History/Daily/0/MinBatteryVoltage']
                self._yesterday_max_battery_voltage = self._dbusservice['/History/Daily/0/MaxBatteryVoltage']
                self._yesterday_time_in_bulk = self._time_in_bulk
                self._yesterday_time_in_absorption = self._time_in_absorption
                self._yesterday_time_in_float = self._time_in_float
                
                # Update yesterday's paths
                self._dbusservice['/History/Daily/1/Yield'] = self._yesterday_yield
                self._dbusservice['/History/Daily/1/MaxPower'] = self._yesterday_max_power
                self._dbusservice['/History/Daily/1/MaxPvVoltage'] = self._yesterday_max_pv_voltage
                self._dbusservice['/History/Daily/1/MinBatteryVoltage'] = self._yesterday_min_battery_voltage
                self._dbusservice['/History/Daily/1/MaxBatteryVoltage'] = self._yesterday_max_battery_voltage
                self._dbusservice['/History/Daily/1/TimeInBulk'] = round(self._yesterday_time_in_bulk, 0)
                self._dbusservice['/History/Daily/1/TimeInAbsorption'] = round(self._yesterday_time_in_absorption, 0)
                self._dbusservice['/History/Daily/1/TimeInFloat'] = round(self._yesterday_time_in_float, 0)
                
                # Reset today's counters
                self._time_in_bulk = 0.0
                self._time_in_absorption = 0.0
                self._time_in_float = 0.0
                self._dbusservice['/History/Daily/0/MaxPower'] = 0
                self._dbusservice['/History/Daily/0/MaxPvVoltage'] = 0
                self._dbusservice['/History/Daily/0/MinBatteryVoltage'] = 0
                self._dbusservice['/History/Daily/0/MaxBatteryVoltage'] = 0
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = 0
                
                # Update day tracking
                self._last_day = current_day
            
            # Update the DBus paths with accumulated times for today (rounded to 1 decimal place)
            self._dbusservice['/History/Daily/0/TimeInBulk'] = round(self._time_in_bulk, 0)
            self._dbusservice['/History/Daily/0/TimeInAbsorption'] = round(self._time_in_absorption, 0)
            self._dbusservice['/History/Daily/0/TimeInFloat'] = round(self._time_in_float, 0)
            
            # Store current state for next iteration
            self._current_charge_state = current_state
            self._last_update_time = now

            # Register 0x3202: Load on/off status
            self._dbusservice['/Load/State'] = c3200[2]
            
            # Registers 0x3312-0x3313: Total generated energy (kWh), divide by 100
            # Combine two 16-bit registers into one 32-bit value
            self._dbusservice['/Yield/User'] = (c3300[12] | c3300[13] << 16)/100 #vorher c3300[13] << 8
            self._dbusservice['/Yield/System'] = (c3300[12] | c3300[13] << 16)/100 #vorher c3300[13] << 8
            
            # Registers 0x330C-0x330D: Daily generated energy (kWh), divide by 100
            # Used as today's yield value
            self._dbusservice['/History/Daily/0/Yield'] = (c330C[0] | c330C[1] << 8)/100
            
            # Update yesterday's yield from EPEVER registers
            yesterday_yield = (c330C[0] | c330C[1] << 8)/100
            if yesterday_yield > 0:
                self._dbusservice['/History/Daily/1/Yield'] = yesterday_yield

            # Update historical max/min statistics (overall and daily)
            # Track maximum PV voltage ever seen (overall system lifetime)
            if self._dbusservice['/Pv/V'] > self._dbusservice['/History/Overall/MaxPvVoltage']:
                self._dbusservice['/History/Overall/MaxPvVoltage'] = self._dbusservice['/Pv/V']

            # Track minimum battery voltage ever seen (overall system lifetime)
            if self._dbusservice['/Dc/0/Voltage'] < self._dbusservice['/History/Overall/MinBatteryVoltage']:
                self._dbusservice['/History/Overall/MinBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']

            # Track maximum battery voltage ever seen (overall system lifetime)
            if self._dbusservice['/Dc/0/Voltage'] > self._dbusservice['/History/Overall/MaxBatteryVoltage']:
                self._dbusservice['/History/Overall/MaxBatteryVoltage'] = self._dbusservice['/Dc/0/Voltage']

            # Track maximum power today (W)
            if self._dbusservice['/Yield/Power'] > self._dbusservice['/History/Daily/0/MaxPower']:
                self._dbusservice['/History/Daily/0/MaxPower'] = self._dbusservice['/Yield/Power']
            
            # Daily statistics - read directly from EPEVER hardware registers
            self._dbusservice['/History/Daily/0/MaxPvVoltage'] = c3300[0] / 100
            self._dbusservice['/History/Daily/0/MaxBatteryVoltage'] = c3300[2] / 100
            self._dbusservice['/History/Daily/0/MinBatteryVoltage'] = c3300[3] / 100
            
            # Track maximum battery current today (A)
            if self._dbusservice['/Dc/0/Current'] > self._dbusservice['/History/Daily/0/MaxBatteryCurrent']:
                self._dbusservice['/History/Daily/0/MaxBatteryCurrent'] = self._dbusservice['/Dc/0/Current']

        return True


# ===============================
# Main entry point
# ===============================
def main():
    """Entry point when executed as a stand‑alone script."""

    if len(sys.argv) < 2:
        logging.error("Kein Port angegeben! Usage: python3 dbus-epever-tracer.py /dev/ttyUSB0")
        sys.exit(1)
        
    tty_port = sys.argv[1]
    
    # 5. FIX: "Probe"-Funktion, um das Gerät zu erkennen, bevor der D-Bus-Dienst gestartet wird.
    # Dies ist das Standardverhalten, das der serial-starter erwartet.
    logging.info(f"Probing for EPEVER Tracer on {tty_port}")
    try:
        controller = minimalmodbus.Instrument(tty_port, 1)
        controller.serial.baudrate = 115200
        controller.serial.bytesize = 8
        controller.serial.parity = serial.PARITY_NONE
        controller.serial.stopbits = 1
        # A short timeout is crucial for the probe to fail fast if no device is present.
        # serial-starter expects drivers to exit quickly if they don't find their hardware.
        controller.serial.timeout = 0.2
        controller.mode = minimalmodbus.MODE_RTU
        controller.clear_buffers_before_each_transaction = True

        # Ein Register lesen, das immer existieren sollte, um das Gerät zu bestätigen.
        # 0x9000 = Rated charging current.
        rated_current = controller.read_register(REGISTER_PARAMETERS, 0, 3)
        logging.info(f"EPEVER device found on {tty_port}. Rated current: {rated_current/100}A")
    except Exception as e:
        logging.info(f"No EPEVER device found on {tty_port}. Reason: {e}")
        # sys.exit() raises a SystemExit exception which can be caught.
        # os._exit() is a hard exit and is used in velib_python itself,
        # so it's the safer option to ensure the script terminates immediately.
        os._exit(1)
        #sys.exit(1)

    global mainloop

    from dbus.mainloop.glib import DBusGMainLoop
    # Set up the main loop so we can send/receive async calls to/from DBus
    DBusGMainLoop(set_as_default=True)

    # Erstelle die EPEVER DBus-Service-Instanz und übergib den bereits verbundenen Controller
    epever = DbusEpever(tty_port, controller)

    # All paths have been added in the DbusEpever constructor.
    # Now, register the service on D-Bus. This will fail if another service
    # with the same name is already running (which is what we want).
    epever._dbusservice.register()

    logging.info('Connected to dbus, and switching over to GLib.MainLoop() (event based)')
    # Start the GLib event loop (runs forever)
    mainloop = GLib.MainLoop()
    try:
        mainloop.run()
    except KeyboardInterrupt:
        pass
    finally:
        logging.info("Treiber wird beendet, D-Bus räumt auf.")

# Run the main function if this script is executed directly
if __name__ == "__main__":
    main()