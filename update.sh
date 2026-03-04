#!/bin/bash

# =========================================================================================
# dbus-epever-tracer Updater for Venus OS
# =========================================================================================

DRIVER_DIR="/data/dbus-epever-tracer"
TEMPLATES_DIR="/opt/victronenergy/service-templates/dbus-epever-tracer"

echo "-----------------------------------------------------------------------"
echo "🔄 dbus-epever-tracer Updater"
echo "-----------------------------------------------------------------------"
read -p "Update Epever Tracer on Venus OS? [Y to proceed] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "❌ Update cancelled by user."
    exit 1
fi

echo "[1/5] Downloading latest master from GitHub..."
cd /data
wget -q --show-progress https://github.com/peterxxl/dbus-epever-tracer/archive/master.zip -O master.zip
unzip -q -o master.zip
rm master.zip

echo "[2/5] Updating files..."
# Kopiert die neuen Dateien über die alten (behält /data Struktur bei)
cp -R dbus-epever-tracer-master/* "$DRIVER_DIR/"
rm -rf dbus-epever-tracer-master

echo "[3/5] Refreshing service templates (Strict: No Symlinks)..."
# WICHTIG: Den Template-Ordner in /opt/ physisch erneuern, NICHT verlinken!
rm -rf "$TEMPLATES_DIR"
cp -r "$DRIVER_DIR/service" "$TEMPLATES_DIR"

echo "[4/5] Setting execute permissions..."
chmod +x "$DRIVER_DIR/driver/dbus-epever-tracer.py"
chmod +x "$DRIVER_DIR/start-dbus-epever-tracer.sh"
chmod +x "$DRIVER_DIR/service/run"

echo "[5/5] Cleaning up active service instances..."
# Stoppt laufende Treiber, damit sie mit dem neuen Code neu starten
pkill -9 -f dbus-epever-tracer
# Wir löschen die flüchtigen Service-Ordner, damit der serial-starter sie frisch aus dem Template erstellt
rm -rf /service/dbus-epever-tracer.*
rm -rf /var/volatile/services/dbus-epever-tracer.*

echo "-----------------------------------------------------------------------"
echo "✅ Update complete!"
echo "-----------------------------------------------------------------------"
echo "The serial-starter will now re-scan your ports automatically."
echo "If the device does not appear, please perform a 'reboot'."
echo "-----------------------------------------------------------------------"