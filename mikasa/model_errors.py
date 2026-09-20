"""Closed transport error vocabulary shared by the host and Hermes bridge."""
from .errors import MikasaError


MESSAGES = {
    "missing_dependency": "Hermes 缺少所选协议的依赖；请按 requirements-tested.txt 安装独立执行环境",
    "auth": "模型服务拒绝认证；检查选定 API key 是否有效",
    "access_denied": "模型服务返回 403；可能涉及网关访问控制或 WAF，不能仅据此判断 Key 权限不足",
    "upstream_blocked": "Hermes 识别到网关或 WAF 拦截；请由服务管理员核对访问策略",
    "billing": "模型服务报告额度或计费限制；请核对网关账户状态",
    "rate_limit": "模型服务限流；请稍后重试或核对 CCH 上游容量",
    "unavailable": "模型服务暂不可用；请核对 CCH 与上游状态",
    "timeout": "模型服务请求超时；请核对网络和 CCH 状态",
    "tls": "模型服务 TLS 校验失败；请核对证书链",
    "model_unavailable": "模型或端点不可用；请核对模型 ID、API 协议和 CCH 路由",
    "request_rejected": "模型服务拒绝请求；请核对协议、上下文限制和模型权限",
    "invalid_response": "Hermes 未返回约定 JSON；请核对所选模型的结构化输出能力",
    "execution_failed": "模型执行器失败；检查隔离环境、模型配置与提供商状态",
}


class ModelFailure(MikasaError):
    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in MESSAGES else "execution_failed"
        super().__init__(MESSAGES[self.code])


def classify_failure(fields):
    # No message/body/request copying. The upstream reason comes from Hermes'
    # official classifier; it is evidence about the error, not a routing decision.
    reason = fields.get("reason")
    status = fields.get("status_code")
    if reason == "upstream_blocked":
        return "upstream_blocked"
    if status == 403:
        return "access_denied"
    if status == 401:
        return "auth"
    reasons = {"auth": "auth", "auth_permanent": "auth", "billing": "billing",
               "rate_limit": "rate_limit", "upstream_rate_limit": "rate_limit",
               "overloaded": "unavailable", "server_error": "unavailable",
               "timeout": "timeout", "ssl_cert_verification": "tls",
               "model_not_found": "model_unavailable", "model_entitlement": "request_rejected",
               "context_overflow": "request_rejected", "payload_too_large": "request_rejected",
               "format_error": "request_rejected"}
    if isinstance(reason, str) and reason in reasons:
        return reasons[reason]
    if type(status) is int:
        if status >= 500:
            return "unavailable"
        return {400: "request_rejected", 402: "billing", 404: "model_unavailable",
                408: "timeout", 413: "request_rejected", 429: "rate_limit"}.get(status, "execution_failed")
    return "execution_failed"
