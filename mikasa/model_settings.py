"""Resolve explicitly selected local model settings without copying credentials."""
import json
import os
import re
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

from .errors import MikasaError


def validate_model(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,199}", value):
        raise MikasaError("请提供完整模型 ID，例如：切换为 gpt-5.6-luna")
    return value


def default_model(config):
    settings = config.data.get("worker", {})
    selected = model_environment(settings).get("MIKASA_MODEL")
    if not selected and "MIKASA_MODEL" in settings.get("env_allowlist", []):
        selected = os.environ.get("MIKASA_MODEL")
    if not selected:
        raise MikasaError("尚未配置默认模型")
    return validate_model(selected)


def model_environment(settings):
    selection = settings.get("model_source", {"type": "environment"})
    source = selection.get("type")
    if source == "environment":
        return {}
    if source != "codex":
        raise MikasaError("model_source.type 仅支持 environment 或 codex")
    try:
        config_path = Path(selection.get("config_path", "~/.codex/config.toml")).expanduser()
        config = tomllib.loads(config_path.read_text())
        provider = config["model_providers"][config["model_provider"]]
        base_url = provider["base_url"]
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise MikasaError("模型端点必须为无嵌入凭据的 HTTP(S) URL")
        key = os.environ.get(provider.get("env_key", ""), "") or provider.get("experimental_bearer_token", "")
        if not key:
            auth_path = Path(selection.get("auth_path", str(config_path.parent / "auth.json"))).expanduser()
            key = json.loads(auth_path.read_text()).get("OPENAI_API_KEY", "")
        if not key:
            raise MikasaError("选定 Codex 配置未提供 API key；不使用或迁移 OAuth 会话")
        wire = provider.get("wire_api", "responses")
        if wire not in {"responses", "chat"}:
            raise MikasaError("不支持选定 Codex provider 的 wire_api")
        return {"MIKASA_MODEL": config["model"], "MIKASA_MODEL_BASE_URL": base_url,
                "MIKASA_MODEL_API_KEY": key, "MIKASA_MODEL_API_MODE": "codex_responses" if wire == "responses" else "chat_completions"}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise MikasaError("无法读取已选择的本地模型配置或认证；未复制认证文件") from exc
