import requests

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3:8b"

def call_model(messages, tools=None):
    """Send the conversation to Ollama and return the model's reply."""
    body = {"model": MODEL, "messages": messages, "stream": False, "think": False}
    if tools:
        body["tools"] = tools
    try:
        response = requests.post(OLLAMA_URL, json=body, timeout=120)
    except requests.RequestException as error:
        raise RuntimeError("Could not reach Ollama. Is the app open? " + str(error))
    if response.status_code != 200:
        raise RuntimeError("Ollama returned an error: " + response.text)
    return response.json()["message"]

if __name__ == "__main__":
    reply = call_model([{"role": "user", "content": "Say hello in one short sentence."}])
    print(reply["content"])