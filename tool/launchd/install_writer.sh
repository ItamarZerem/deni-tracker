#!/bin/zsh
# ‏מתקין את סוכן הכתבות על המק. ‏אפשר להריץ שוב אחרי שינוי ב-writer_gate.py או ב-writer.command.
# ‏לפני הריצה הראשונה: להעתיק את הטוקן של הבוט מ-BotFather, והסקריפט קורא אותו מהלוח ולא מדפיס אותו.
set -e
SRC=${0:A:h}
BASE=$HOME/.config/deni-writer
LOGS=$HOME/Library/Logs/deni-writer
AGENTS=$HOME/Library/LaunchAgents
mkdir -p "$BASE" "$LOGS"
cp "$SRC/writer_gate.py" "$BASE/gate.py"
cp "$SRC/writer.command" "$BASE/writer.command"
chmod +x "$BASE/writer.command"

if [[ ! -s "$BASE/telegram_token" ]]; then
  TOKEN=$(pbpaste | tr -d '[:space:]')
  if [[ ! "$TOKEN" =~ '^[0-9]+:[A-Za-z0-9_-]+$' ]]; then
    echo "❌ בלוח אין טוקן של בוט. צריך להעתיק אותו מ-BotFather ולהריץ שוב."
    exit 1
  fi
  (umask 077; print -rn -- "$TOKEN" > "$BASE/telegram_token")
  echo "✅ הטוקן נשמר"
fi

cat > "$AGENTS/com.itamar.deni-writer.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.itamar.deni-writer</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/open</string><string>-g</string><string>-a</string><string>Terminal</string>
    <string>$BASE/writer.command</string>
  </array>
  <key>StandardOutPath</key><string>$LOGS/launchd.log</string>
  <key>StandardErrorPath</key><string>$LOGS/launchd.log</string>
</dict></plist>
PLIST

cat > "$AGENTS/com.itamar.deni-writer-gate.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.itamar.deni-writer-gate</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$BASE/gate.py</string><string>tick</string>
  </array>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOGS/gate.log</string>
  <key>StandardErrorPath</key><string>$LOGS/gate.log</string>
</dict></plist>
PLIST

for LABEL in com.itamar.deni-writer com.itamar.deni-writer-gate; do
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$LABEL.plist"
done

# ‏רישום בעמוד הסוכנים של קוקפיט
/usr/bin/python3 - <<'PY'
import json, os
path = os.path.expanduser("~/Library/Application Support/Cockpit/data/projects/deni.json")
p = json.load(open(path))
if not any(a.get("id") == "writer" for a in p.get("agents", [])):
    p.setdefault("agents", []).append({"id": "writer", "name": "כתבות", "launchdLabel": "com.itamar.deni-writer"})
    json.dump(p, open(path, "w"), ensure_ascii=False, indent=2)
PY
echo "✅ הסוכן מותקן"
