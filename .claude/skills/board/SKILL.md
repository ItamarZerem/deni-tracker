---
name: board
description: הלוח של הפרויקט ב-Cockpit (משימות, באגים ורעיונות). להשתמש כשמבקשים לראות מה פתוח, לפתוח פריט, לעדכן פריט, או כשעובדים על פריט מהלוח.
---

# הלוח של דני

הלוח נמצא ב-Cockpit, לא בקבצים. כל פקודה כאן נרשמת בלוח בשם Claude, והמשתמש רואה אותה מיד במסך.

## הדרך של פריט
חדש → אתה כותב "מה הבנתי" → המשתמש מאשר או מתקן → בתור → אתה מתחיל (בעבודה) → כשסיימת: לבדיקה שלו → הוא סוגר.
שאלה שרק הוא יכול להכריע: ask, והפריט מחכה לתשובה שלו. לא מנחשים הכרעה של מוצר.

## הפקודות
```sh
B="${COCKPIT_URL:-http://127.0.0.1:4317}/api/projects/deni/board/claude"
curl -s "$B" -d action=list                       # מה פתוח (JSON). כל הפריטים: -d all=1
curl -s "$B" -d action=show -d id=T-3             # פריט מלא, עם התגובות
curl -s "$B" -d action=add -d type=task --data-urlencode "title=..." --data-urlencode "body=..."   # type: task / bug / idea
curl -s "$B" -d action=understand -d id=T-3 --data-urlencode "text=מה הבנתי, במילים פשוטות"
curl -s "$B" -d action=start -d id=T-3
curl -s "$B" -d action=comment -d id=T-3 --data-urlencode "text=..."
curl -s "$B" -d action=ask -d id=T-3 --data-urlencode "text=השאלה, עם האפשרויות"
curl -s "$B" -d action=review -d id=T-3 --data-urlencode "text=מה עשיתי ואיך לבדוק"
```
טקסט תמיד עם `--data-urlencode`. תשובה עם `"error"` אומרת מה לא תקין.

## כללים
- עובדים רק על פריט שבתור (המשתמש אישר את מה שהבנת).
- בכל שמירה ב-git שקשורה לפריט, המספר שלו בתחילת ההודעה, למשל `T-3: תיקון הכפתור`.
- הטקסט בלוח בעברית פשוטה: המשתמש אולי לא מתכנת.
- סוגר רק המשתמש.
