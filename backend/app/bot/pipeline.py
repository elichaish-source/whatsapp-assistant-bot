"""הצינור של הבוט: פענוח, ביצוע ורישום — בלי לדעת מי שאל.

⚠️⚠️ **מוח אחד, שני ערוצים.** זה הגבול שנקבע באפיון של מסך הוואטסאפ:
סכימת כוונות אחת, קבוצת פעולות אחת, ואותו קוד בדיוק — **אין פעולה
שקיימת רק במסך**. מה שהמסך מוסיף הוא רינדור (כפתורים, רשימה ארוכה,
קישור), ולא יכולת.

⚠️ **הצינור אינו שולח כלום.** הוא מחזיר את הקטעים לשליחה, ומי שמחליט
מה לעשות בהם הוא הערוץ: ``routers/bot.py`` שולח אותם בוואטסאפ,
ו-``routers/whatsapp.py`` מציג אותם במסך בלבד. זה מה שמממש את ההכרעה
"הודעה שנכתבה במסך נענית במסך בלבד ואינה יוצאת בוואטסאפ" — אחרת
וואטסאפ מתמלא בהדים של עבודה שנעשתה במסך.
"""

import json
import logging

from sqlalchemy.orm import Session

from .. import memory
from ..models import BotMessage
from . import actions
from .intent import IntentError, extract

log = logging.getLogger(__name__)

UNREADABLE = "לא הצלחתי לפענח את ההודעה. אפשר לנסות שוב בעוד רגע."


def run(db: Session, row: BotMessage) -> list[str]:
    """מריץ את ההודעה שבשורה, ממלא אותה, ומחזיר את מה שיש להשיב.

    השורה כבר נשמרה לפני הקריאה: היא מה שמונע טיפול כפול, והיא גם
    המזהה ש-``before_id`` מצביע עליו כשמחפשים את ההודעה שלפניה.
    """
    channel = row.channel or actions.WHATSAPP
    # כלל הברזל: בלי זיכרון הבוט עובד בדיוק כמו קודם
    memory_block = memory.build_block(db)
    try:
        result = extract(
            row.body or "",
            actions.build_context(db),
            actions.now_local(),
            actions.build_history(db, row.id, channel),
            memory_block,
        )
    except IntentError as exc:
        log.warning("פענוח ההודעה נכשל: %s", exc)
        row.error = str(exc)
        row.reply = UNREADABLE
        db.commit()
        return [row.reply]

    row.intent = result.intent.action
    # הבלוק שהוזרק נשמר כמו שהוא, כדי שתמיד נדע על סמך מה הבוט החליט
    row.memory_used = memory_block or None
    row.input_tokens = result.input_tokens
    row.output_tokens = result.output_tokens
    row.cached_tokens = result.cached_tokens
    db.commit()

    outcome = actions.execute(db, result.intent, row.id, channel)
    row.reply = outcome.reply
    row.task_id = outcome.task_id
    row.fact_id = outcome.fact_id
    row.recurrence_id = outcome.recurrence_id
    row.query_sql = outcome.query_sql
    row.undo_json = json.dumps(outcome.undo, ensure_ascii=False) if outcome.undo else None
    row.pending_json = (
        json.dumps(outcome.pending, ensure_ascii=False) if outcome.pending else None
    )
    if outcome.listed_task_ids:
        row.listed_task_ids = ",".join(str(item) for item in outcome.listed_task_ids)
    elif outcome.clear_list:
        # ‏"" ולא None: השורה הזאת היא עכשיו המספור האחרון, והוא ריק.
        # ככה "סיימתי 2" לא יחזור אחורה לרשימה של לפני השאילתה
        row.listed_task_ids = ""
    else:
        row.listed_task_ids = None
    # ‏None ולא "": רשימת המיילים האחרונה נשארת תקפה גם אחרי הודעות
    # שאינן על מיילים, בדיוק כמו שרשימת המשימות נשארת תקפה
    row.listed_email_ids = (
        ",".join(outcome.listed_email_ids) if outcome.listed_email_ids else None
    )
    if outcome.query_error:
        row.error = outcome.query_error
    db.commit()
    # מייל ארוך יוצא בכמה הודעות. בכל שאר המקרים parts ריק, וזו
    # בדיוק אותה תשובה אחת שהייתה כאן קודם
    return list(outcome.parts or [outcome.reply])
