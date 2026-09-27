import requests

# 1. Get Token
r1 = requests.post("http://127.0.0.1:8000/token")
token = r1.json()["access_token"]

# 2. Call Chat
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
data = {
    "query": "Which vehicles should we investigate this week?",
    "from_date": "2026-08-28",
    "to_date": "2026-09-26"
}
print("Asking Agent: ", data["query"])
r2 = requests.post("http://127.0.0.1:8000/chat", headers=headers, json=data)

if r2.status_code == 200:
    res = r2.json()
    print("\n--- AGENT RESPONSE ---")
    print(res["answer"])
    print("\n--- TOOLS EXECUTED ---")
    for tool in res.get("tool_calls", []):
        print(f"- {tool['name']}: {tool['args']}")
else:
    print("Error:", r2.status_code, r2.text)
