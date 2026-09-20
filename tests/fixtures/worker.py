import json
import sys

request = json.load(sys.stdin)
kind = request["task"]["kind"]
if kind == "chat":
    result = {"summary": "我是 Mikasa，记得你在当前聊天提供的上下文。"}
elif kind == "implement":
    result = {"summary": "Update fixture", "changes": [{"path": "app.py", "content": "VALUE = 2\n"}]}
elif kind == "plan":
    result = {"summary": "Plan fixture", "tasks": [{"title": "First", "acceptance": "A", "depends_on": []}, {"title": "Second", "acceptance": "B", "depends_on": [0]}]}
else:
    result = {"summary": "Review fixture", "verdict": "APPROVED", "basis": ["Fixture acceptance"], "findings": [], "limitations": []}
print(json.dumps({"version": 1, "result": result, "runtime": {"backend": "fixture"}}))
