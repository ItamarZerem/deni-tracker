#!/bin/bash
# ‏רענון יומי של זמני הבדיקה מלוח המשחקים (טרייד, דחייה, משחקי גביע, פלייאוף).
# ‏רץ מ-launchd במק (com.itamar.deni-tracker). ‏דוחף רק אם משהו השתנה.
cd "$(dirname "$0")" || exit 1
exec >>refresh.log 2>&1
echo "== $(date '+%F %T')"
git pull -q --rebase || exit 1
/usr/bin/python3 tracker.py gen || exit 1
if ! git diff --quiet -- .github/workflows/deni.yml; then
  git commit -q -m "רענון לוח משחקים $(date +%F)" -- .github/workflows/deni.yml && git push -q && echo "נדחף"
fi
