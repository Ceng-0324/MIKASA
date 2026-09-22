import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from mikasa.config import Config
from mikasa.engineering_cli import launch
from mikasa.native import prepare_profile, profile_home
from tests.support import ROOT


class NativeEngineeringTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='mke-', dir='/tmp')
        self.addCleanup(self.temp.cleanup)
        self.data = json.loads((ROOT / 'config/examples/mikasa.json').read_text())
        self.data.update(runtime=self.temp.name, members=['human'])
        self.config = Config(ROOT, self.data)
        python = ROOT / 'runtime/cache/hermes-venv/bin/python'
        if not python.is_file():
            self.skipTest('requires pinned Hermes SDK')
        env = patch.dict(os.environ, {'MIKASA_MODEL':'fixture-model',
            'MIKASA_MODEL_BASE_URL':'https://cch.invalid/v1', 'MIKASA_MODEL_API_KEY':'synthetic-secret',
            'MIKASA_MODEL_API_MODE':'codex_responses'})
        env.start()
        self.addCleanup(env.stop)

    def test_native_tools_and_preferences_survive_refresh_without_chat_guard(self):
        home, source, python, credentials = prepare_profile(self.config, self.config.owner, engineering=True)
        saved = json.loads((home / 'config.yaml').read_text())
        saved.update(agent={'max_turns':321}, terminal={'backend':'local','timeout':123},
                     platform_toolsets={'cli':['hermes-cli']}, plugins={'enabled':['mikasa','user-plugin']})
        (home / 'config.yaml').write_text(json.dumps(saved))
        (home / '.env').write_text('NATIVE_ENGINEERING_FIXTURE=enabled\n')
        prepare_profile(self.config, self.config.owner, engineering=True)
        env = {'PATH':os.environ.get('PATH',''), 'HERMES_HOME':str(home),
               'MIKASA_HERMES_SOURCE':str(source), **credentials}
        code = '''
import json,os,sys
sys.path.insert(0,os.environ['MIKASA_HERMES_SOURCE'])
from hermes_cli.config import load_config
from hermes_cli.plugins import discover_plugins,get_pre_tool_call_directive
from model_tools import get_tool_definitions
from agent.skill_commands import build_auto_load_prompt
cfg=load_config()
assert cfg['agent']['max_turns']==321 and cfg['terminal']['timeout']==123
before={t['function']['name'] for t in get_tool_definitions(enabled_toolsets=['hermes-cli'],quiet_mode=True,skip_tool_search_assembly=True)}
discover_plugins()
after={t['function']['name'] for t in get_tool_definitions(enabled_toolsets=['hermes-cli'],quiet_mode=True,skip_tool_search_assembly=True)}
assert before==after
for name in ('terminal','process_manage','write_file','delegate_task','skill_manage','session_search','web_search','browser_navigate','execute_code'):
    assert get_pre_tool_call_directive(name,{'background':True})[0] is None,name
prompt,loaded,missing=build_auto_load_prompt()
assert not missing and {'mikasa-persona','mikasa-engineering'} <= set(loaded)
assert '工程契约' in prompt and '工程工作流' in prompt
print('native engineering parity passed')
'''
        r = subprocess.run([str(python),'-c',code],env=env,cwd=home/'workspace',capture_output=True,text=True,timeout=45)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('native engineering parity passed',r.stdout)
        current = json.loads((home/'config.yaml').read_text())
        self.assertIn('user-plugin', current['plugins']['enabled'])

    def test_shared_memory_and_native_history_are_preserved(self):
        chat = profile_home(self.config,self.config.owner)
        (chat/'memories').mkdir(parents=True)
        (chat/'memories/MEMORY.md').write_text('existing owner convention')
        (chat/'config.yaml').write_text('chat preferences untouched')
        home,*_ = prepare_profile(self.config,self.config.owner,engineering=True)
        (home/'state.db').write_bytes(b'existing native history')
        (home/'memories/USER.md').write_text('shared owner profile')
        prepare_profile(self.config,self.config.owner,engineering=True)
        self.assertEqual((home/'state.db').read_bytes(), b'existing native history')
        self.assertEqual((home/'memories/MEMORY.md').read_text(),'existing owner convention')
        self.assertEqual((chat/'memories/USER.md').read_text(),'shared owner profile')
        self.assertEqual((chat/'config.yaml').read_text(),'chat preferences untouched')
        other,*_ = prepare_profile(self.config,'human',engineering=True)
        self.assertFalse((other/'memories/MEMORY.md').exists())

    def test_launcher_passes_native_arguments_cwd_and_explicit_credentials(self):
        workspace=Path(self.temp.name)/'full-repo'
        workspace.mkdir()
        args=['--','chat','--worktree','--max-turns','900','--resume','latest']
        process=Mock()
        process.wait.return_value=0
        process.poll.return_value=0
        prepared = prepare_profile(self.config, self.config.owner, engineering=True)
        with patch.dict(os.environ,{'MIKASA_GITHUB_TOKEN':'account-fixture','UNRELATED_SECRET':'not-forwarded'}), \
                patch('mikasa.engineering_cli.prepare_profile', return_value=prepared), \
                patch('mikasa.engineering_cli.subprocess.Popen',return_value=process) as start:
            self.assertEqual(launch(self.config,args,cwd=workspace),0)
        passed=start.call_args
        self.assertEqual(passed.args[0][2:],args[1:])
        self.assertEqual(passed.kwargs['cwd'], workspace.resolve())
        env=passed.kwargs['env']
        self.assertEqual(env['GH_TOKEN'],'account-fixture')
        self.assertNotIn('UNRELATED_SECRET',env)
        self.assertNotIn('HERMES_ENABLE_PROJECT_PLUGINS',env)
        home=Path(env['HERMES_HOME'])
        self.assertFalse(any(b'account-fixture' in p.read_bytes() or b'synthetic-secret' in p.read_bytes()
                             for p in home.rglob('*') if p.is_file()))


if __name__=='__main__':
    unittest.main()
