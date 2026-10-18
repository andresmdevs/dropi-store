#!/bin/zsh
# Instala los agentes de Monkey Store como servicio de launchd (corren solos, 24/7).
# Uso: ./agentes/instalar.sh           (instala o reinicia)
#      ./agentes/instalar.sh quitar    (los detiene y desinstala)
set -e
LABEL=com.andresmo.dropi-agentes
DIR=${0:A:h}
PLIST=~/Library/LaunchAgents/$LABEL.plist
mkdir -p $DIR/data/logs
launchctl bootout gui/$(id -u)/$LABEL 2>/dev/null || true
if [[ "$1" == "quitar" ]]; then rm -f $PLIST; echo "Agentes detenidos y desinstalados"; exit 0; fi
cat > $PLIST <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <!-- caffeinate -i: el Mac no se duerme por inactividad mientras los agentes trabajan -->
  <key>ProgramArguments</key><array><string>/usr/bin/caffeinate</string><string>-i</string><string>/opt/homebrew/bin/python3</string><string>$DIR/orquestador.py</string></array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>60</integer>
  <key>StandardOutPath</key><string>$DIR/data/logs/launchd.log</string>
  <key>StandardErrorPath</key><string>$DIR/data/logs/launchd.log</string>
</dict></plist>
PL
launchctl bootstrap gui/$(id -u) $PLIST
echo "Agentes corriendo. Estado: http://localhost:8790   Log: $DIR/data/logs/launchd.log"
