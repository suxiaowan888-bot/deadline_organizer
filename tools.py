import json
from datetime import datetime

import storage
from dates import parse_date
from llm_client import call_model

TOOL_NAMES = ["add_task", "list_tasks", "ask_user"]

SYSTEM_PROMPT = """You are a deadline organizer. You help the user save tasks
with deadlines and list their upcoming deadlines.

Rules:
1. When the user gives a task, call add_task. Copy the date words exactly as
   the user wrote them into date_phrase. Do not calculate or change the date.
2. If the user's message has no date words at all, call ask_user to ask for
   the deadline. Never invent a date.
3. If add_task says the date is unclear, missing, or in the past, call
   ask_user with a short question. If it gives options, include them.
4. When the user asks about their deadlines, call list_tasks.
5. Only say a task was saved if add_task returned "saved": true.
6. Use one tool at a time. When finished, reply in one or two short sentences."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "add_task",
            "description": "Save a task with a deadline. Python checks the date words first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short task name, for example 'Submit the report'.",
                    },
                    "date_phrase": {
                        "type": "string",
                        "description": "The date words copied exactly from the user, "
                                       "for example 'Friday afternoon'.",
                    },
                },
                "required": ["title", "date_phrase"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_tasks",
            "description": "Show the user's upcoming deadlines, soonest first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "How many tasks to show. Default 5.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "Ask the user a question when the date is missing or unclear.",
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "One short, specific question for the user.",
                    },
                },
                "required": ["question"],
            },
        },
    },
]


# ---------- Parser ----------

def read_tool_call(call):
    """Parser: get the tool name and arguments out of the model's tool call."""
    function = call.get("function", {})
    name = function.get("name", "")
    arguments = function.get("arguments", {})
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            return name, {}, "The arguments are not valid JSON."
    if not isinstance(arguments, dict):
        return name, {}, "The arguments must be an object."
    return name, arguments, ""


# ---------- Validator ----------

def simplify(text):
    """Lowercase and remove punctuation so small differences don't matter."""
    text = text.lower()
    for mark in ".,!?;:\"'":
        text = text.replace(mark, " ")
    return " ".join(text.split())


def validate_tool_call(name, arguments, user_words):
    """Validator: return an error message, or "" if the call is allowed."""
    if name not in TOOL_NAMES:
        return "Unknown tool '" + name + "'. Allowed tools: " + ", ".join(TOOL_NAMES) + "."
    if name == "add_task":
        title = arguments.get("title")
        date_phrase = arguments.get("date_phrase")
        if not isinstance(title, str) or title.strip() == "":
            return "add_task needs a non-empty title."
        if not isinstance(date_phrase, str) or date_phrase.strip() == "":
            return "add_task needs date_phrase. If the user gave no date, call ask_user."
        if simplify(date_phrase) not in simplify(user_words):
            return ("date_phrase '" + date_phrase + "' is not in the user's words. "
                    "Copy the date words exactly. Never invent a date. "
                    "If there is no date, call ask_user.")
    if name == "list_tasks":
        limit = arguments.get("limit", 5)
        if isinstance(limit, str) and limit.isdigit():
            limit = int(limit)
        if not isinstance(limit, int) or limit < 1 or limit > 20:
            return "limit must be a whole number from 1 to 20."
    if name == "ask_user":
        question = arguments.get("question")
        if not isinstance(question, str) or question.strip() == "":
            return "ask_user needs a non-empty question."
    return ""


# ---------- Executor ----------

def due_of(task):
    """Used for sorting tasks by their due date."""
    return task["due"]


def run_add_task(title, date_phrase):
    """Check the date with Python, save the task, then confirm it on disk."""
    result = parse_date(date_phrase)
    if result["status"] != "ok":
        return {
            "saved": False,
            "date_status": result["status"],
            "note": result["note"],
            "options": result["candidates"],
            "next_step": "Ask the user for a clear date. Do not guess.",
        }
    for task in storage.load_tasks():
        if task["title"].lower() == title.lower() and task["due"] == result["due"]:
            return {"saved": False, "note": "This task is already saved.", "task": task}
    task = storage.add_task(title, result["due"])
    # Never trust "saved" without reading the file again
    verified = False
    for saved_task in storage.load_tasks():
        if saved_task["id"] == task["id"] and saved_task["due"] == task["due"]:
            verified = True
    return {
        "saved": verified,
        "verified_on_disk": verified,
        "task": task,
        "readable": result["readable"],
        "note": result["note"],
    }


def run_list_tasks(limit):
    """Return upcoming tasks, soonest first, with readable dates."""
    now_text = datetime.now().strftime("%Y-%m-%dT%H:%M")
    upcoming = []
    overdue_count = 0
    for task in storage.load_tasks():
        if task["done"]:
            continue
        if task["due"] >= now_text:
            upcoming.append(task)
        else:
            overdue_count = overdue_count + 1
    upcoming.sort(key=due_of)
    shown = []
    for task in upcoming[:limit]:
        due = datetime.strptime(task["due"], "%Y-%m-%dT%H:%M")
        shown.append({"id": task["id"], "title": task["title"],
                      "due": due.strftime("%A, %d %b %Y, %H:%M")})
    return {"count": len(shown), "total_upcoming": len(upcoming),
            "overdue_count": overdue_count, "tasks": shown}


def run_tool(name, arguments):
    """Executor: actually do the action the model asked for."""
    try:
        if name == "add_task":
            return run_add_task(arguments["title"].strip(), arguments["date_phrase"])
        if name == "list_tasks":
            return run_list_tasks(int(arguments.get("limit", 5)))
        if name == "ask_user":
            return {"asked": True, "question": arguments["question"]}
    except RuntimeError as error:
        return {"error": str(error)}
    return {"error": "The tool did not run."}


# ---------- Test (runs without the model) ----------

def show(label, name, arguments, user_words):
    print(label)
    print("  PROPOSAL:", name, arguments)
    error = validate_tool_call(name, arguments, user_words)
    if error != "":
        print("  REJECTED:", error)
    else:
        print("  RESULT:", run_tool(name, arguments))
    print()


if __name__ == "__main__":
    show("Test 1: clear date", "add_task",
         {"title": "Submit the report", "date_phrase": "Friday afternoon"},
         "Submit the report Friday afternoon.")
    show("Test 2: vague date", "add_task",
         {"title": "Prepare slides", "date_phrase": "sometime next week"},
         "Prepare slides sometime next week.")
    show("Test 3: invented date", "add_task",
         {"title": "Email my professor", "date_phrase": "Monday"},
         "Remind me to email my professor.")
    show("Test 4: unknown tool", "delete_everything", {},
         "Delete all my tasks.")
    show("Test 5: list deadlines", "list_tasks", {"limit": 5},
         "What are my next deadlines?")