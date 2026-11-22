import re
from datetime import datetime, date, time, timedelta

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_WORDS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2, "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}
MONTH_WORDS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
VAGUE_WORDS = ["soon", "sometime", "some time", "asap", "whenever", "later", "eventually",
               "next week", "this week", "next month", "this month", "weekend"]
PART_OF_DAY = {
    "morning": time(9, 0), "noon": time(12, 0), "afternoon": time(17, 0),
    "evening": time(19, 0), "tonight": time(20, 0),
    "end of day": time(23, 59), "end of the day": time(23, 59),
}


def safe_date(year, month, day):
    """Return a date, or None if that day does not exist (like Feb 30)."""
    try:
        return date(year, month, day)
    except ValueError:
        return None


def make_result(status, due=None, note="", candidates=None):
    """Build the answer that the agent will receive."""
    result = {"status": status, "due": None, "readable": None, "note": note, "candidates": []}
    if due is not None:
        result["due"] = due.strftime("%Y-%m-%dT%H:%M")
        result["readable"] = due.strftime("%A, %d %b %Y, %H:%M")
    if candidates is not None:
        for one_date in candidates:
            result["candidates"].append(one_date.strftime("%A, %d %b %Y"))
    return result


def find_time(text):
    """Return (time, note). Return (None, reason) if the time is impossible."""
    match = re.search(r"(?<!\d)(\d{1,2})(:(\d{2}))?\s?(am|pm)\b", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(3) or 0)
        if hour < 1 or hour > 12 or minute > 59:
            return None, "That is not a real time."
        if match.group(4) == "pm" and hour != 12:
            hour = hour + 12
        if match.group(4) == "am" and hour == 12:
            hour = 0
        return time(hour, minute), ""
    match = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        if hour > 23 or minute > 59:
            return None, "That is not a real time."
        return time(hour, minute), ""
    for word in PART_OF_DAY:
        if re.search(r"\b" + word + r"\b", text):
            chosen = PART_OF_DAY[word]
            return chosen, "'" + word + "' was read as " + chosen.strftime("%H:%M") + "."
    return time(23, 59), "No time was given, so 23:59 (end of day) was used."


def parse_date(phrase, now=None):
    """Turn words like 'Friday afternoon' into a date, or explain why it can't."""
    if now is None:
        now = datetime.now()
    today = now.date()

    text = phrase.lower().replace(",", " ")
    text = text.replace("a.m.", "am").replace("p.m.", "pm")
    text = text.replace("no later than", "by")
    text = " ".join(text.split())

    # Step 1: vague words. Never guess.
    for word in VAGUE_WORDS:
        if re.search(r"\b" + word + r"\b", text):
            return make_result("unclear", note="'" + word + "' is too vague to pick one date.")

    found = []

    # Step 2: relative words like tomorrow or in 3 days
    if re.search(r"\bday after tomorrow\b", text):
        found.append(today + timedelta(days=2))
        text = text.replace("day after tomorrow", " ")
    if re.search(r"\b(tomorrow|tmr)\b", text):
        found.append(today + timedelta(days=1))
    if re.search(r"\b(today|tonight)\b", text):
        found.append(today)
    if re.search(r"\byesterday\b", text):
        found.append(today - timedelta(days=1))
    match = re.search(r"\bin (\d+) (day|days|week|weeks)\b", text)
    if match:
        amount = int(match.group(1))
        if match.group(2).startswith("week"):
            amount = amount * 7
        found.append(today + timedelta(days=amount))

    # Step 3: exact dates like 2026-11-27, Nov 27, or 27 November
    match = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", text)
    if match:
        exact = safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if exact is None:
            return make_result("unclear", note="That calendar date does not exist.")
        found.append(exact)
    for word in MONTH_WORDS:
        match = re.search(r"\b" + word + r" (\d{1,2})(st|nd|rd|th)?\b", text)
        if not match:
            match = re.search(r"\b(\d{1,2})(st|nd|rd|th)? (of )?" + word + r"\b", text)
        if match:
            month = MONTH_WORDS[word]
            day = int(match.group(1))
            exact = safe_date(today.year, month, day)
            if exact is not None and exact < today:
                exact = safe_date(today.year + 1, month, day)
            if exact is None:
                return make_result("unclear", note="That calendar date does not exist.")
            found.append(exact)

    # Step 4: weekday names like Friday or next Friday
    for word in WEEKDAY_WORDS:
        match = re.search(r"\b(this |next |coming )?" + word + r"\b", text)
        if not match:
            continue
        target = WEEKDAY_WORDS[word]
        name = DAY_NAMES[target]
        if len(found) > 0:
            if found[0].weekday() != target:
                return make_result("unclear", note="The phrase says " + name + ", but "
                                   + found[0].strftime("%d %b") + " is a "
                                   + found[0].strftime("%A") + ".")
            continue
        days_ahead = (target - today.weekday()) % 7
        modifier = (match.group(1) or "").strip()
        if modifier == "next":
            if days_ahead == 0:
                days_ahead = 7
            first = today + timedelta(days=days_ahead)
            return make_result("unclear", note="'next " + name + "' could mean either date.",
                               candidates=[first, first + timedelta(days=7)])
        if days_ahead == 0 and modifier != "this":
            return make_result("unclear", note="Today is " + name + ", so it could mean today or next week.",
                               candidates=[today, today + timedelta(days=7)])
        found.append(today + timedelta(days=days_ahead))

    # Step 5: decide
    unique = []
    for one_date in found:
        if one_date not in unique:
            unique.append(one_date)
    if len(unique) == 0:
        return make_result("missing", note="No date was found.")
    if len(unique) > 1:
        return make_result("unclear", note="More than one date was mentioned.", candidates=unique)

    due_time, time_note = find_time(text)
    if due_time is None:
        return make_result("unclear", note=time_note)
    due = datetime.combine(unique[0], due_time)
    if due < now:
        return make_result("past", due=due, note="This date and time is already in the past.")
    return make_result("ok", due=due, note=time_note)


if __name__ == "__main__":
    test_now = datetime(2026, 11, 22, 10, 0)   # fixed "now": Sunday, 22 Nov 2026, 10:00
    examples = ["Friday afternoon", "tomorrow at 3pm", "Nov 30 9am", "in 3 days",
                "next Friday", "sometime next week", "Submit the report", "Sunday",
                "Friday Dec 5", "Feb 30", "today 8am"]
    for example in examples:
        result = parse_date(example, test_now)
        line = example.ljust(20) + result["status"].ljust(9)
        if result["readable"]:
            line = line + result["readable"] + "  "
        line = line + result["note"]
        if len(result["candidates"]) > 0:
            line = line + "  Options: " + " / ".join(result["candidates"])
        print(line)