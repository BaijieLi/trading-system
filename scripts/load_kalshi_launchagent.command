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

echo "Unloading any previous copy..."
launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true

echo "Loading Kalshi monitor into $DOMAIN..."
launchctl bootstrap "$DOMAIN" "$PLIST" || exit 1

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
