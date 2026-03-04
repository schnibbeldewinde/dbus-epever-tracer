#!/bin/bash
. /opt/victronenergy/serial-starter/run-service.sh

app="python3 -u /opt/victronenergy/dbus-epever-tracer/driver/dbus-epever-tracer.py"
args="/dev/$tty"

start $args
