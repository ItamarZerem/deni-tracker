#!/bin/zsh
# ‏נפתח ב-Terminal.app מ-launchd, כמו הטייס של הסידור: רק Terminal מורשה לקרוא את ~/Desktop.
# ‏מותקן ב-~/.config/deni-writer/ (המקור בריפו: tool/launchd/writer.command).
printf '\e]0;📝 סוכן הכתבות של דני\a'
echo "📝 סוכן הכתבות של דני רץ ($(date +%H:%M)). החלון ייסגר לבד בסוף."
/bin/zsh "$HOME/Desktop/deni-tracker/tool/writer.sh"
TTY=$(tty)
(sleep 2; osascript -e "tell application \"Terminal\" to close (every window whose tty of selected tab is \"$TTY\")" >/dev/null 2>&1) &!
exit 0
