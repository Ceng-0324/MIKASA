"""Use Hermes QR pairing unchanged; atomically retain only a complete owner binding."""
import asyncio
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, os.environ["MIKASA_HERMES_SOURCE"])


def main():
    import json
    from gateway.platforms.weixin import check_weixin_requirements, qr_login
    from mikasa.connections import validate_weixin_binding
    from mikasa.native import private_write

    # Native QR presentation is intentional; SDK errors must not expose responses.
    logging.disable(logging.CRITICAL)
    if not check_weixin_requirements():
        raise RuntimeError("missing native dependencies")
    value = asyncio.run(qr_login(os.environ["HERMES_HOME"]))
    if not value:
        print("微信扫码未完成，原绑定保留。", flush=True)
        return 1
    value["actor"] = sys.argv[2]
    validate_weixin_binding(value, sys.argv[2])
    private_write(Path(sys.argv[1]), json.dumps(value))
    print("微信凭据已保存，仅允许本次扫码账号单聊；尚未启动消息收发。", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception:
        raise SystemExit("微信登录失败；检查固定依赖、网络及扫码结果。原绑定保留。") from None
