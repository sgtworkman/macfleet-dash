#!/bin/sh
# macfleet-dash endpoint installer — macOS LaunchAgent.
#
# Usage:  ./install.sh [BIND_IP[:PORT]]     (default 127.0.0.1:8791)
#
# Installs ~/Library/LaunchAgents/com.macfleet.metrics.plist so the read-only
# probe endpoint starts at login and stays alive. Bind a loopback or tailnet
# address only — the endpoint has no authentication.
set -eu

LABEL="com.macfleet.metrics"
BIND="${1:-127.0.0.1:8791}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
LOG_DIR="$HOME/Library/Logs/macfleet-dash"

if [ "$(uname)" != "Darwin" ]; then
  echo "error: install.sh is for macOS LaunchAgents." >&2
  echo "On Linux, run the endpoint under systemd, e.g.:" >&2
  echo "  ExecStart=/usr/bin/python3 $APP_DIR/endpoint/metrics_server.py $BIND" >&2
  echo "  (bind a loopback or tailnet IP; Restart=always; User=<you>)" >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3 || true)"
if [ -z "$PYTHON_BIN" ]; then
  echo "error: python3 not found in PATH" >&2
  exit 1
fi

mkdir -p "$LOG_DIR" "$(dirname "$PLIST")"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${APP_DIR}/endpoint/metrics_server.py</string>
    <string>${BIND}</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/metrics-server.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/metrics-server.log</string>
</dict>
</plist>
EOF

# Replace any running instance.
launchctl bootout "gui/$(id -u)/${LABEL}" 2>/dev/null || \
  launchctl unload "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || \
  launchctl load "$PLIST"

echo "installed ${LABEL} — bind ${BIND}"
echo "plist: ${PLIST}"
echo "logs:  ${LOG_DIR}/metrics-server.log"
sleep 1

PORT="${BIND##*:}"
if command -v curl >/dev/null 2>&1; then
  HOST="${BIND%:*}"
  if curl -fsS -m 8 "http://${HOST}:${PORT}/healthz" >/dev/null 2>&1; then
    echo "verified: http://${HOST}:${PORT}/metrics.txt is up"
  else
    echo "note: endpoint did not answer yet — check the log or re-run install.sh" >&2
  fi
fi
