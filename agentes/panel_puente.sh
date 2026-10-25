#!/bin/zsh
set -e
LABEL=com.andresmo.dropi-panel-puente
DIR=${0:A:h}
PLIST=~/Library/LaunchAgents/$LABEL.plist
mkdir -p "$DIR/data/logs"
launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
if [[ "$1" == "quitar" ]]; then
  rm -f "$PLIST"
  echo "Puente remoto detenido y desinstalado"
  exit 0
fi
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/opt/homebrew/bin/python3</string><string>$DIR/panel_puente.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$DIR/data/logs/panel-puente.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/logs/panel-puente.log</string>
</dict></plist>
PL
launchctl bootstrap gui/$(id -u) "$PLIST"
echo "Puente remoto corriendo; necesita INTERACCIONES_QUEUE_URL y token en .env.local"
