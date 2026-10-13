#!/bin/zsh
set -u

PROJECT_DIR="/Users/libaijie/Downloads/Github_project/kalshi-trading-system"
PLIST="$HOME/Library/LaunchAgents/com.baijieli.kalshi-monitor.plist"
LABEL="com.baijieli.kalshi-monitor"
DOMAIN="gui/$(id -u)"

cd "$PROJECT_DIR" || exit 1
mkdir -p logs

echo "Checking LaunchAgent plist..."
plutil -lint "$PLIST" || exit 1
chmod 644 "$PLIST" || exit 1

echo "Stopping/removing any previous copy..."
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootout "$DOMAIN" "$PLIST" 2>/dev/null || true
launchctl remove "$LABEL" 2>/dev/null || true
sleep 1

echo "Loading Kalshi monitor into $DOMAIN..."
if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "Service is still registered; restarting it in place."
else
  if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
    echo "bootstrap failed; trying legacy launchctl load -w fallback..."
    launchctl load -w "$PLIST" || exit 1
  fi
fi
launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true

echo "Starting Kalshi monitor..."
launchctl kickstart -k "$DOMAIN/$LABEL" || exit 1

echo
echo "LaunchAgent status:"
launchctl print "$DOMAIN/$LABEL"

echo
echo "Done. Recent monitor log:"
sleep 3
echo "--- /tmp stdout ---"
tail -n 20 /tmp/kalshi-monitor-launchd.log 2>/dev/null || true
echo "--- /tmp stderr ---"
tail -n 20 /tmp/kalshi-monitor-launchd.err 2>/dev/null || true
echo "--- project stdout ---"
tail -n 20 logs/launchd-monitor.log 2>/dev/null || true
echo "--- project stderr ---"
tail -n 20 logs/launchd-monitor.err 2>/dev/null || true

echo
echo "You can close this Terminal window after checking there are no errors."
