import json
import os
from datetime import datetime

import storage
from llm_client import call_model
from tools import SYSTEM_PROMPT, TOOLS, read_tool_call, validate_tool_call, run_tool

MAX_STEPS = 6
TRACE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trace.txt")


def log(trace, text):
    """Print a line and also keep it in the trace."""
    print(text)
    trace.append(text)


def count_tasks():
    """Count tasks on disk. Return -1 if the file is damaged."""
    try:
        return len(storage.load_tasks())
    except RuntimeError:
        return -1

SAVE_PHRASES = ["has been saved", "have been saved", "was saved", "were saved",
                "is saved", "saved with", "i saved", "i've saved", "i have saved",
                "has been added", "have been added", "was added", "i added",
                "i've added", "added to your"]


def claims_saved(text):
    """Return True if the reply claims a task was saved, not just uses the word."""
    lower = text.lower()
    for phrase in SAVE_PHRASES:
        if phrase in lower:
            return True
    return False

def check_evidence(reply_text, tasks_before, saved_ids, trace):
    """Compare what the model says with what is really in tasks.json."""
    tasks_after = count_tasks()
    log(trace, "  EVIDENCE: tasks.json has " + str(tasks_after) + " task(s) (before: "
        + str(tasks_before) + "). Saved this turn: " + str(saved_ids))
    if tasks_before >= 0 and tasks_after >= 0:
        if tasks_after - tasks_before != len(saved_ids):
            log(trace, "  WARNING: the number of tasks on disk does not match what was saved.")
    if claims_saved(reply_text) and len(saved_ids) == 0:
        log(trace, "  WARNING: the model says a task was saved, but no add_task succeeded this turn.")

def handle_message(messages, user_words, user_text, trace):
    """Run the agent loop for one user message and return the agent's reply."""
    user_words.append(user_text)
    messages.append({"role": "user", "content": user_text})
    tasks_before = count_tasks()
    saved_ids = []
    reply_text = ""
    finished = False
    step = 0

    while step < MAX_STEPS and not finished:
        step = step + 1
        label = "  [step " + str(step) + "] "
        reply = call_model(messages, TOOLS)
        messages.append(reply)
        tool_calls = reply.get("tool_calls")

        # No tool: the model is answering the user directly
        if not tool_calls:
            reply_text = (reply.get("content") or "").strip()
            log(trace, label + "MODEL REPLIED (no tool)")
            # Python check: the model may not claim a save that did not happen
            if claims_saved(reply_text) and len(saved_ids) == 0:
                log(trace, "    CHECK FAILED: the reply claims a save, but nothing was saved. Sent back to the model.")
                log(trace, "    REJECTED REPLY: " + reply_text)
                messages.append({"role": "user", "content":
                                 "SYSTEM CHECK FAILED: No task was saved in this turn. "
                                 "Do not say a task was saved. If the user gave no date, call ask_user."})
                continue
            finished = True
            continue

        for call in tool_calls:
            name, arguments, error = read_tool_call(call)                       # parser
            log(trace, label + "MODEL CHOSE: " + name + " " + json.dumps(arguments, ensure_ascii=False))
            if error == "":
                error = validate_tool_call(name, arguments, " ".join(user_words))  # validator
            if error != "":
                result = {"error": error}
                log(trace, "    REJECTED: " + error)
            else:
                result = run_tool(name, arguments)                                # executor
                log(trace, "    RESULT: " + json.dumps(result, ensure_ascii=False))
                if result.get("saved"):
                    saved_ids.append(result["task"]["id"])
                if name == "ask_user":
                    reply_text = arguments["question"]
                    finished = True
            # The result goes back to the model as an observation
            messages.append({"role": "tool", "tool_name": name,
                             "content": json.dumps(result, ensure_ascii=False)})

    if not finished:
        reply_text = "Sorry, I stopped after " + str(MAX_STEPS) + " steps without finishing."
        log(trace, "  STOPPED: step budget (MAX_STEPS) reached")

    check_evidence(reply_text, tasks_before, saved_ids, trace)
    return reply_text


def show_file():
    """Print tasks.json straight from disk, without the model."""
    if not os.path.exists(storage.TASKS_FILE):
        print("tasks.json does not exist yet.")
        return
    with open(storage.TASKS_FILE, "r", encoding="utf-8") as file:
        print(file.read())


def save_trace(trace):
    """Add this session's trace to trace.txt."""
    with open(TRACE_FILE, "a", encoding="utf-8") as file:
        file.write("===== Session " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " =====\n")
        for line in trace:
            file.write(line + "\n")
        file.write("\n")
    print("Trace saved to trace.txt")


def main():
    trace = []
    today = datetime.now().strftime("%A, %d %b %Y")
    messages = [{"role": "system", "content": SYSTEM_PROMPT + "\nToday is " + today + "."}]
    user_words = []
    print("Deadline Organizer. Type 'file' to see tasks.json, or 'quit' to stop.")

    while True:
        try:
            user_text = input("\nYOU: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_text == "":
            continue
        if user_text.lower() in ["quit", "exit"]:
            break
        if user_text.lower() == "file":
            show_file()
            continue
        trace.append("")
        trace.append("USER: " + user_text)
        try:
            reply_text = handle_message(messages, user_words, user_text, trace)
        except RuntimeError as error:
            log(trace, "SYSTEM ERROR: " + str(error))
            continue
        log(trace, "AGENT: " + reply_text)

    save_trace(trace)


if __name__ == "__main__":
    main()