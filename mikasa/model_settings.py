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


MODEL_FIELDS = ("MIKASA_MODEL", "MIKASA_MODEL_BASE_URL", "MIKASA_MODEL_API_KEY", "MIKASA_MODEL_API_MODE")


def validate_environment(env, *, required=False):
    """Validate only selected settings; optional workers need not use a model."""
    if required and any(not env.get(k) for k in MODEL_FIELDS[:3]):
        raise MikasaError("缺少模型 ID、端点或 API key；检查模型来源及 env_allowlist")
    if "MIKASA_MODEL" in env:
        validate_model(env["MIKASA_MODEL"])
    if "MIKASA_MODEL_BASE_URL" in env:
        try:
            value = env["MIKASA_MODEL_BASE_URL"]
            if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value):
                raise ValueError()
            parsed = urlsplit(value)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or parsed.query or parsed.fragment or parsed.port == 0):
                raise ValueError()
        except (ValueError, TypeError):
            raise MikasaError("模型端点必须为无嵌入凭据、查询参数或片段的有效 HTTP(S) URL") from None
    if "MIKASA_MODEL_API_KEY" in env:
        key = env["MIKASA_MODEL_API_KEY"]
        if not isinstance(key, str) or not key or any(c.isspace() or ord(c) < 32 for c in key):
            raise MikasaError("模型 API key 必须为非空且无空白的字符串")
    if "MIKASA_MODEL_API_MODE" in env and env["MIKASA_MODEL_API_MODE"] not in {"codex_responses", "chat_completions"}:
        raise MikasaError("模型 API 模式仅支持 codex_responses 或 chat_completions")
    return env


def model_environment(settings):
    selection = settings.get("model_source", {"type": "environment"})
    source = selection.get("type")
    if source == "environment":
        return validate_environment({k: os.environ[k] for k in MODEL_FIELDS
                                     if k in settings.get("env_allowlist", []) and k in os.environ})
    if source != "codex":
        raise MikasaError("model_source.type 仅支持 environment 或 codex")
    try:
        config_path = Path(selection.get("config_path", "~/.codex/config.toml")).expanduser()
        config = tomllib.loads(config_path.read_text())
        provider = config["model_providers"][config["model_provider"]]
        base_url = provider["base_url"]
        validate_environment({"MIKASA_MODEL_BASE_URL": base_url})
        key = os.environ.get(provider.get("env_key", ""), "") or provider.get("experimental_bearer_token", "")
        if not key:
            auth_path = Path(selection.get("auth_path", str(config_path.parent / "auth.json"))).expanduser()
            key = json.loads(auth_path.read_text()).get("OPENAI_API_KEY", "")
        if not key:
            raise MikasaError("选定 Codex 配置未提供 API key；不使用或迁移 OAuth 会话")
        wire = provider.get("wire_api", "responses")
        if wire not in {"responses", "chat"}:
            raise MikasaError("不支持选定 Codex provider 的 wire_api")
        return validate_environment({"MIKASA_MODEL": config["model"], "MIKASA_MODEL_BASE_URL": base_url,
                "MIKASA_MODEL_API_KEY": key, "MIKASA_MODEL_API_MODE": "codex_responses" if wire == "responses" else "chat_completions"}, required=True)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MikasaError("无法读取已选择的本地模型配置或认证；未复制认证文件") from exc


def model_diagnostics(settings):
    """Local evidence only. Never expose keys, auth paths or endpoint paths."""
    report = {"source": settings.get("model_source", {}).get("type", "environment"),
              "connection": "not_checked", "provider_group": "unverified",
              "group_note": "CCH 分组由网关 Key 配置决定；本地模型名和连接成功不能证明属于 default 分组"}
    try:
        env = model_environment(settings)
        validate_environment(env, required=True)
    except MikasaError as exc:
        return {**report, "configuration": "invalid", "error": str(exc)}
    parsed = urlsplit(env["MIKASA_MODEL_BASE_URL"])
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return {**report, "configuration": "valid", "requested_model": env["MIKASA_MODEL"],
            "endpoint_origin": f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else ""),
            "api_mode": env.get("MIKASA_MODEL_API_MODE", "chat_completions"), "credential_present": True}
