import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import MikasaError
from .model_settings import validate_routes, validate_source

REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")


@dataclass(frozen=True)
class Config:
    root: Path
    data: dict

    @classmethod
    def load(cls, path):
        path = Path(path).resolve()
        try:
            data = json.loads(path.read_text())
            root = (path.parent / data.get("project_root", "../..")).resolve()
            if data.get("version") != 1:
                raise MikasaError("配置 version 必须为 1")
            allowed = {"version", "project_root", "runtime", "owner", "bot", "members", "repositories", "worker", "server", "github", "feishu", "schedules", "engineering"}
            if set(data) - allowed:
                raise MikasaError("配置包含未知字段")
            if data.get("owner") != "Ceng-0324" or data.get("bot") != "Mikasa-0910":
                raise MikasaError("配置身份必须符合工程契约")
            for name in ("identity.md", "engineering-contract.md", "engineering-workflow.md"):
                if not (root / name).is_file():
                    raise MikasaError(f"缺少规则文件：{name}")
            repos = data.get("repositories", {})
            if not isinstance(repos, dict):
                raise MikasaError("repositories 必须为对象")
            for name, repo in repos.items():
                if not REPO.fullmatch(name) or any(p in {".", ".."} for p in name.split("/")):
                    raise MikasaError("非法仓库名称")
                if not isinstance(repo, dict) or set(repo) - {"source", "base", "checks", "check_image", "agent_image", "allow_local_checks"}:
                    raise MikasaError("仓库配置字段不合法")
                if not isinstance(repo.get("base"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/_.-]*", repo["base"]):
                    raise MikasaError("需要明确仓库 base 分支")
                if ".." in repo["base"] or repo["base"].endswith(".lock"):
                    raise MikasaError("非法 base 分支")
                source = repo.get("source", f"https://github.com/{name}.git")
                if source != f"https://github.com/{name}.git" and not Path(source).is_absolute():
                    raise MikasaError("source 只支持指定 GitHub HTTPS 地址或绝对本地路径")
                if not isinstance(repo.get("checks", []), list):
                    raise MikasaError("checks 必须为数组")
                for command in repo.get("checks", []):
                    if not isinstance(command, list) or not command or not all(isinstance(v, str) and v for v in command):
                        raise MikasaError("checks 必须为非空 argv 数组的列表")
                if type(repo.get("allow_local_checks", False)) is not bool:
                    raise MikasaError("allow_local_checks 必须为布尔值")
                if "check_image" in repo and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}", repo["check_image"]):
                    raise MikasaError("非法容器镜像名称")
                if 'agent_image' in repo and (not isinstance(repo['agent_image'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]{0,255}', repo['agent_image'])):
                    raise MikasaError('非法原生工程容器镜像名称')
            worker = data.get("worker", {})
            command = worker.get("command", [])
            if not isinstance(command, list) or not all(isinstance(v, str) and v for v in command):
                raise MikasaError("worker.command 必须为 argv 数组")
            env_names = worker.get("env_allowlist", [])
            if not isinstance(env_names, list) or not all(isinstance(v, str) and re.fullmatch(r"[A-Z_][A-Z0-9_]*", v) for v in env_names):
                raise MikasaError("worker.env_allowlist 必须为环境变量名称数组")
            model_source = worker.get("model_source", {"type": "environment"})
            validate_source(model_source)
            validate_routes(worker.get("model_routes", []))
            for field in ("hermes_source", "home", "native_python"):
                if field in worker and (not isinstance(worker[field], str) or not worker[field]):
                    raise MikasaError(f"worker.{field} 必须为路径")
            if "native_gateway" in worker:
                raise MikasaError("聊天已统一使用原生 Gateway；删除旧 native_gateway 开关")
            members = data.get("members", [])
            engineering = data.get('engineering', {})
            if not isinstance(engineering, dict) or set(engineering) - {'cwd', 'env_allowlist'}:
                raise MikasaError('engineering 只接受默认 cwd 和显式环境变量名称')
            if 'cwd' in engineering and (not isinstance(engineering['cwd'], str) or not Path(engineering['cwd']).is_absolute()):
                raise MikasaError('engineering.cwd 必须为绝对目录')
            if not isinstance(engineering.get('env_allowlist', []), list) or any(
                    not isinstance(n, str) or not re.fullmatch(r'[A-Z_][A-Z0-9_]*', n)
                    for n in engineering.get('env_allowlist', [])):
                raise MikasaError('engineering.env_allowlist 必须为环境变量名称数组')
            if not isinstance(members, list) or not all(isinstance(m, str) and m for m in members):
                raise MikasaError("members 必须为账号数组")
            interval = data.get("schedules", {}).get("audit_interval_seconds", 0)
            if type(interval) is not int or (interval != 0 and not 60 <= interval <= 604800):
                raise MikasaError("审计间隔必须为 0（关闭）或 60–604800 秒")
            feishu = data.get("feishu", {})
            if not isinstance(feishu, dict) or set(feishu) - {"domain", "owner_open_id", "owner_user_id", "app_id_env", "app_secret_env"}:
                raise MikasaError("feishu 只接受 domain、负责人 ID 和凭据环境变量名称")
            if feishu.get("domain", "feishu") not in {"feishu", "lark"}:
                raise MikasaError("feishu.domain 必须为 feishu 或 lark")
            if "owner_open_id" in feishu and (not isinstance(feishu["owner_open_id"], str) or not re.fullmatch(r"ou_[A-Za-z0-9]+", feishu["owner_open_id"])):
                raise MikasaError("feishu.owner_open_id 必须为负责人在本应用中的 ou_ 用户标识")
            if "owner_user_id" in feishu and (not isinstance(feishu["owner_user_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", feishu["owner_user_id"])):
                raise MikasaError("feishu.owner_user_id 必须为同一负责人的租户用户 ID")
            for section, field, default in (("github", "token_env", "MIKASA_GITHUB_TOKEN"),
                                            ("feishu", "app_id_env", "MIKASA_FEISHU_APP_ID"),
                                            ("feishu", "app_secret_env", "MIKASA_FEISHU_APP_SECRET")):
                variable = data.get(section, {}).get(field, default)
                if not isinstance(variable, str) or not re.fullmatch(r"[A-Z_][A-Z0-9_]*", variable):
                    raise MikasaError(f"{section}.{field} 必须为环境变量名称")
            return cls(root, data)
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise MikasaError("配置无法读取或结构不正确") from exc

    @property
    def runtime(self):
        return (self.root / self.data.get("runtime", "runtime/state")).resolve()

    @property
    def owner(self):
        return self.data["owner"]

    @property
    def bot(self):
        return self.data["bot"]


    def authorize(self, actor, owner=False):
        from .errors import Forbidden
        if actor != self.owner and (owner or actor not in self.data.get("members", [])):
            raise Forbidden("账号无此操作权限")

    def secret(self, section, field, default):
        name = self.data.get(section, {}).get(field, default)
        value = os.environ.get(name, "")
        if not value:
            raise MikasaError(f"缺少环境变量：{name}")
        return value

    def rules(self):
        return "\n\n".join((self.root / name).read_text() for name in (
            "identity.md", "engineering-contract.md", "engineering-workflow.md"))
