#!/bin/bash

# =========================================================================================
# dbus-epever-tracer Installer for Venus OS
# =========================================================================================

DRIVER_DIR="/data/dbus-epever-tracer"
TEMPLATES_DIR="/opt/victronenergy/service-templates/dbus-epever-tracer"
CONF_FILE="/data/conf/serial-starter.d/epever.conf"

echo "🚀 Starting installation of dbus-epever-tracer..."

# 1. Sicherstellen, dass das Skript als root läuft
if [[ $EUID -ne 0 ]]; then
   echo "❌ This script must be run as root" 
   exit 1
fi

# 2. Verzeichnisse vorbereiten
echo "📁 Preparing directories..."
mkdir -p /data/conf/serial-starter.d

# 3. Service-Template in /opt/ kopieren (KEIN Symlink!)
# Das ist wichtig, damit der serial-starter für jeden USB-Port eine eigene Instanz kopieren kann.
echo "🛠 Setting up service templates..."
if [ -d "$TEMPLATES_DIR" ]; then
    rm -rf "$TEMPLATES_DIR"
fi
# Wir kopieren den /service Ordner aus deinem Treiber-Verzeichnis als Vorlage
cp -r "$DRIVER_DIR/service" "$TEMPLATES_DIR"

# 4. Serial-Starter Konfiguration erstellen
# Wir nutzen die kombinierte Liste, damit GPS und SerialBattery weiterhin funktionieren.
echo "📝 Configuring serial-starter..."
cat > "$CONF_FILE" <<'EOF'
service epever dbus-epever-tracer
alias default gps:vedirect:sbattery:epever
alias rs485 cgwacs:fzsonick:imt:modbus:sbattery:epever
EOF

# 5. rc.local Integration (für Persistenz nach Firmware-Updates)
# Wir verlinken den Treiber-Ordner nach /opt/, damit der Pfad im 'run' Skript stimmt.
echo "🔗 Ensuring persistence via rc.local..."
if ! grep -q "$DRIVER_DIR" /data/rc.local; then
    cat >> /data/rc.local <<EOF

# dbus-epever-tracer setup
ln -s $DRIVER_DIR /opt/victronenergy/dbus-epever-tracer
EOF
fi

# Einmalig manuell ausführen, falls der Link noch nicht existiert
if [ ! -L "/opt/victronenergy/dbus-epever-tracer" ]; then
    ln -s "$DRIVER_DIR" /opt/victronenergy/dbus-epever-tracer
fi

# 6. Berechtigungen setzen
echo "🔐 Setting permissions..."
chmod +x "$DRIVER_DIR/driver/dbus-epever-tracer.py"
chmod +x "$DRIVER_DIR/start-dbus-epever-tracer.sh"
chmod +x "$DRIVER_DIR/service/run"

# 7. Altlasten aufräumen und Neustart vorbereiten
echo "🧹 Cleaning up old service instances..."
pkill -9 serial-starter
pkill -9 -f dbus-epever-tracer
rm -rf /service/dbus-epever-tracer.*
rm -rf /var/volatile/services/dbus-epever-tracer.*

echo "-----------------------------------------------------------------------"
echo "✅ Installation finished!"
echo "-----------------------------------------------------------------------"
echo "REBOOT REQUIRED: Please run 'reboot' now."
echo "The driver will then automatically scan all USB ports for EPEVER devices."
echo "-----------------------------------------------------------------------"