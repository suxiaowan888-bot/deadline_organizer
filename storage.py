import json
import os
from datetime import datetime

# tasks.json is kept in the same folder as this file
TASKS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.json")

def load_tasks():
    """Read all tasks from the JSON file and return them as a list."""
    if not os.path.exists(TASKS_FILE):
        return []
    with open(TASKS_FILE, "r", encoding="utf-8") as file:
        text = file.read()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError("tasks.json is damaged (not valid JSON). It was not changed.")
    if not isinstance(data, list):
        raise RuntimeError("tasks.json has the wrong format. It should contain a list.")
    return data

def save_tasks(tasks):
    """Write the whole task list to the JSON file."""
    temp_file = TASKS_FILE + ".tmp"
    with open(temp_file, "w", encoding="utf-8") as file:
        json.dump(tasks, file, indent=2, ensure_ascii=False)
    os.replace(temp_file, TASKS_FILE)

def add_task(title, due):
    """Add one task, save it, and return the new task."""
    tasks = load_tasks()
    new_id = 1
    for task in tasks:
        if task["id"] >= new_id:
            new_id = task["id"] + 1
    task = {
        "id": new_id,
        "title": title,
        "due": due,
        "done": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    tasks.append(task)
    save_tasks(tasks)
    return task

if __name__ == "__main__":
    saved = add_task("Test task", "2026-11-27T17:00")
    print("Saved:", saved)
    print("All tasks on disk:", load_tasks())