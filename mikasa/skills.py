"""Load trusted project skills; repository/task content cannot choose skill paths."""
import hashlib
import json
import re

from .errors import MikasaError


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def load_skills(root, kind):
    directory = (root / "skills").resolve()
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest.get("version") != 1 or not isinstance(manifest.get("skills"), list):
            raise MikasaError("skill manifest 版本或结构不正确")
        selected = []
        seen = set()
        for entry in manifest["skills"]:
            name = entry["name"]
            if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]{1,63}", name) or name in seen:
                raise MikasaError("skill 名称不合法或重复")
            seen.add(name)
            if not isinstance(entry["tasks"], list) or not set(entry["tasks"]) <= {"plan", "implement", "review", "chat"}:
                raise MikasaError("skill 任务路由不合法")
            path = (directory / entry["path"]).resolve()
            if not path.is_relative_to(directory) or path.name != "SKILL.md":
                raise MikasaError("skill 路径越界")
            content = path.read_text()
            if len(content.encode()) > 30000 or not content.startswith("---\n") or f"\nname: {name}\n" not in content:
                raise MikasaError("skill 内容或 frontmatter 不合法")
            if kind in entry["tasks"]:
                selected.append({"name": name, "source": entry["source"], "sha256": digest(content), "content": content})
        if kind in {"plan", "implement", "review", "chat"} and not selected:
            raise MikasaError("任务没有加载任何 skill")
        return selected
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        raise MikasaError("无法加载 skill manifest 或文件") from exc


def skill_inventory(root):
    return {kind: [{k: v for k, v in s.items() if k != "content"} for s in load_skills(root, kind)]
            for kind in ("plan", "implement", "review", "chat")}
