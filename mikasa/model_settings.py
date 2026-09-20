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
API_MODES = {"codex_responses", "chat_completions", "anthropic_messages"}


def validate_source(selection):
    if not isinstance(selection, dict) or selection.get("type") not in {"environment", "codex", "claude"}:
        raise MikasaError("worker.model_source.type 必须为 environment、codex 或 claude")
    if set(selection) - {"type", "config_path", "auth_path"}:
        raise MikasaError("model_source 仅保存读取来源，不允许内嵌凭据")
    for field in ("config_path", "auth_path"):
        if field in selection and (not isinstance(selection[field], str) or not selection[field]):
            raise MikasaError("模型来源路径必须为非空字符串")
    if "auth_path" in selection and selection["type"] != "codex":
        raise MikasaError("仅 Codex 来源支持 auth_path")


def validate_routes(routes):
    if not isinstance(routes, list) or len(routes) > 100:
        raise MikasaError("model_routes 必须为最多 100 条路由的数组")
    seen_models, seen_prefixes = set(), set()
    for route in routes:
        if not isinstance(route, dict) or set(route) - {"models", "prefixes", "model_source"}:
            raise MikasaError("model_routes 路由字段不合法")
        validate_source(route.get("model_source"))
        if not route.get("models") and not route.get("prefixes"):
            raise MikasaError("模型路由需要 models 或 prefixes")
        for field, seen in (("models", seen_models), ("prefixes", seen_prefixes)):
            values = route.get(field, [])
            if not isinstance(values, list) or len(values) > 200:
                raise MikasaError("路由匹配项必须为最多 200 项的数组")
            for value in values:
                validate_model(value)
                if value in seen:
                    raise MikasaError("模型路由包含重复匹配项")
                seen.add(value)


def select_source(settings, model=None):
    routes = settings.get("model_routes", [])
    validate_routes(routes)
    if model is not None:
        validate_model(model)
        for route in routes:
            if model in route.get("models", []):
                return route["model_source"]
        candidates = [(len(prefix), route["model_source"]) for route in routes
                      for prefix in route.get("prefixes", []) if model.startswith(prefix)]
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
    return settings.get("model_source", {"type": "environment"})


def model_choices(settings):
    """Configured names only, never imply a live CCH inventory."""
    validate_routes(settings.get("model_routes", []))
    return sorted({model for route in settings.get("model_routes", []) for model in route.get("models", [])})


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
    if "MIKASA_MODEL_API_MODE" in env and env["MIKASA_MODEL_API_MODE"] not in API_MODES:
        raise MikasaError("模型 API 模式仅支持 codex_responses、chat_completions 或 anthropic_messages")
    return env


def model_environment(settings, model=None):
    selection = select_source(settings, model)
    validate_source(selection)
    source = selection.get("type")
    if source == "environment":
        env = {k: os.environ[k] for k in MODEL_FIELDS if k in settings.get("env_allowlist", []) and k in os.environ}
        if model is not None:
            env["MIKASA_MODEL"] = model
        return validate_environment(env)
    try:
        if source == "claude":
            path = Path(selection.get("config_path", "~/.claude/settings.json")).expanduser()
            config = json.loads(path.read_text())
            env = config.get("env", {})
            # Explicitly selected settings file only: no OAuth/keychain, helper or shell execution.
            key = env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY")
            selected = model or env.get("ANTHROPIC_MODEL") or config.get("model")
            if not isinstance(selected, str) or not selected or selected in {"opus", "sonnet", "haiku", "default"} or "[" in selected:
                raise MikasaError("Claude 来源需要完整模型 ID；不将 Claude Code 的别名或上下文后缀当成网关模型名")
            return validate_environment({"MIKASA_MODEL": selected, "MIKASA_MODEL_BASE_URL": env.get("ANTHROPIC_BASE_URL"),
                                         "MIKASA_MODEL_API_KEY": key, "MIKASA_MODEL_API_MODE": "anthropic_messages"}, required=True)
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
        return validate_environment({"MIKASA_MODEL": model or config["model"], "MIKASA_MODEL_BASE_URL": base_url,
                "MIKASA_MODEL_API_KEY": key, "MIKASA_MODEL_API_MODE": "codex_responses" if wire == "responses" else "chat_completions"}, required=True)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MikasaError("无法读取已选择的本地模型配置或认证；未复制认证文件") from exc


def model_diagnostics(settings, model=None):
    """Local evidence only. Never expose keys, auth paths or endpoint paths."""
    report = {"source": select_source(settings, model).get("type"),
              "connection": "not_checked", "provider_group": "unverified",
              "group_note": "CCH 分组由网关 Key 配置决定；本地模型名和连接成功不能证明属于 default 分组"}
    try:
        env = model_environment(settings, model)
        validate_environment(env, required=True)
    except MikasaError as exc:
        return {**report, "configuration": "invalid", "error": str(exc)}
    parsed = urlsplit(env["MIKASA_MODEL_BASE_URL"])
    host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return {**report, "configuration": "valid", "requested_model": env["MIKASA_MODEL"],
            "endpoint_origin": f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else ""),
            "api_mode": env.get("MIKASA_MODEL_API_MODE", "chat_completions"), "credential_present": True}
