#!/bin/zsh
# ‏ריצה אחת של סוכן הכתבות. ‏launchd פותח אותה דרך writer.command, כי רק Terminal מורשה לקרוא את ~/Desktop.
# ‏קוקפיט מזהה ריצה לפי הנתיב של הקובץ הזה, וקורא את היומן בפורמט שלמטה (engine/src/agents/index.ts).
# ‏⛔ היומן מוצג בעמוד הסוכנים, ולכן הוא ניטרלי: הכתבה לא נכתבת אליו.
ROOT=${0:A:h:h}
GATE=$HOME/.config/deni-writer/gate.py
LOG_DIR=$HOME/Library/Logs/deni-writer
mkdir -p "$LOG_DIR"

JOB=$(/usr/bin/python3 "$GATE" pick 2>/dev/null)
if [[ -z "$JOB" ]]; then
  echo "$(date '+%d.%m %H:%M') דילוג: אין כרגע כתבה לכתוב" >> "$LOG_DIR/skipped.log"
  exit 0
fi
MODE=${JOB%% *}
GAME=${JOB##* }
KEY="$GAME-$MODE"

LOG="$LOG_DIR/$(date +%Y-%m-%d_%H%M)_$MODE.log"
exec >>"$LOG" 2>&1
echo "=== $(date) · $MODE ==="
/usr/bin/python3 "$GATE" begin "$KEY"
caffeinate -i /usr/bin/python3 -u "$ROOT/tool/writer.py" "$MODE" "$GAME"
EXIT=$?
if [[ $EXIT == 0 ]]; then
  /usr/bin/python3 "$GATE" done "$KEY"
  echo "הטיוטה נשלחה לטלגרם, והיא מחכה לאישור."
else
  echo "הכתיבה נכשלה. ינוסה שוב, או שאפשר להפעיל ידנית."
fi
echo "=== סיום $(date) · יציאה $EXIT ==="
exit $EXIT
