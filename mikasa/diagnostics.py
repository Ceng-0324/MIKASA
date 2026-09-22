"""Explicit model diagnostics through an ephemeral native Gateway."""
import tempfile
import uuid

from .config import Config
from .native import NativeGateways


def probe_model(config, model):
    with tempfile.TemporaryDirectory(prefix='mikasa-model-probe-') as directory:
        isolated = Config(config.root, {**config.data, 'runtime': directory})
        gateways = NativeGateways(isolated)
        try:
            gateway = gateways.for_actor(config.owner)
            session = uuid.uuid4().hex
            gateway.ensure_session(session, model)
            run = gateway.start(session, '请简短回复：模型连接验证完成。', model, uuid.uuid4().hex)
            completed = gateway.wait(run['run_id'])
            return {'backend': 'hermes-gateway', **completed.get('runtime', {})}
        finally:
            gateways.close()
