#!/usr/bin/env python3
"""Pinned-SDK verification of native history, memory and plugin/skill policy; no model calls."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.native import HERMES_REVISION, prepare_profile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='config/local/hermes-cch.json')
    args = p.parse_args()
    base = Config.load(args.config)
    with tempfile.TemporaryDirectory(prefix='mko-', dir='/tmp') as directory:
        data = json.loads(json.dumps(base.data)); data['runtime'] = directory
        config = Config(base.root, data)
        checks = {}
        home, source, python, _ = prepare_profile(config, config.owner)
        env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'HERMES_HOME':str(home), 'MIKASA_HERMES_SOURCE':str(source)}
        def execute(argv):
            r = subprocess.run(argv, env=env, cwd=home/'workspace', capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise RuntimeError('offline SDK check failed: '+r.stderr[-1800:])
            return r.stdout
        output = execute([str(python),'-c', '''import os,sys,json
from pathlib import Path
sys.path.insert(0,os.environ['MIKASA_HERMES_SOURCE'])
from hermes_cli.plugins import discover_plugins,get_plugin_manager,get_pre_tool_call_directive,render_system_prompt_sections
from agent.skill_commands import build_auto_load_prompt
from tools.memory_tool import memory_tool,load_on_disk_store
from tools.skills_tool import skill_view
from tools.session_search_tool import session_search
from model_tools import handle_function_call
from agent.tool_executor import _unwrap_tool_search_call
from types import SimpleNamespace
discover_plugins()
p = next(p for p in get_plugin_manager().list_plugins() if p['name']=='mikasa')
home=Path(os.environ['HERMES_HOME'])
from hermes_state import SessionDB
db=SessionDB(home/'state.db')
db.create_session('history-fixture',source='feishu')
db.append_message('history-fixture','user','reply-50')
db.close()
prompt,loaded,missing=build_auto_load_prompt(home_override=home)
sections=''.join(s.content for s in render_system_prompt_sections({}))
engineering=[]
for kind in ('plan','implement','review'):
 names=['mikasa-persona','mikasa-'+kind]
 body,found,absent=build_auto_load_prompt(user_config={'skills':{'auto_load':names}},home_override=home)
 engineering.append(found==names and not absent)
rules=json.loads(skill_view('mikasa-engineering'))
rule_text=json.dumps(rules,ensure_ascii=False)
canonical=(home/'skills/mikasa-engineering/SKILL.md').read_text()
on_demand=all((home/'policy'/name).read_text() in canonical and (home/'policy'/name).read_text() not in sections for name in ('engineering-contract.md','engineering-workflow.md'))
history=json.loads(session_search(query='"reply-50"'))
toolsets=['memory','skills','session_search']
described=json.loads(handle_function_call('tool_describe', {'names':['session_search']}, enabled_toolsets=toolsets))
name,args,blocked=_unwrap_tool_search_call(SimpleNamespace(enabled_toolsets=toolsets), 'tool_call', {'name':'session_search','arguments':{'profile':'other','query':'private'}})
store=load_on_disk_store()
old='Offline fixture: Shawn prefers a short weekly report.'
new='Offline fixture: Shawn confirmed a detailed weekly report; replaces the earlier short format.'
added=json.loads(memory_tool(action='add',target='memory',content=old,store=store))
replaced=json.loads(memory_tool(action='replace',target='memory',old_text=old,content=new,store=store))
user=json.loads(memory_tool(action='add',target='user',content='Offline fixture: address the user as Shawn.',store=store))
print(json.dumps({'plugin_loaded':p['enabled'] and not p['error'],
 'native_persona_auto_load':'mikasa-persona' in loaded and not missing and 'do not reconstruct personality' in prompt,
 'native_engineering_skills':all(engineering),
 'canonical_rules_on_demand':on_demand and '工程契约' in rule_text and '工程工作流' in rule_text,
 'native_history_search': 'reply-50' in json.dumps(history),
 'native_history_discovery_bridge':'session_search' in described.get('tools',{}) and name=='session_search' and blocked is None and get_pre_tool_call_directive(name,args)[0] is None,
 'native_memory_convention_update':all(r.get('success') and not r.get('staged') for r in (added,replaced,user)),
 'native_engineering_tools_unrestricted':all(get_pre_tool_call_directive(n,{})[0] is None for n in ['terminal','write_file','skill_manage','delegate_task']),
 'native_memory_skills_history_allowed':all(get_pre_tool_call_directive(n,{})[0] is None for n in ['memory','skill_view','skills_list','session_search','tool_search','tool_describe','tool_call']),
 'native_history_policy':all(get_pre_tool_call_directive('session_search',a)[0] is None for a in [{'profile':'other'},{'session_id':'other/session'}])}))'''])
        checks.update(json.loads(output))
        # A fresh SDK process loads updated native memory; no Mikasa shadow store.
        output = execute([str(python), '-c', '''import os,sys,json
sys.path.insert(0,os.environ['MIKASA_HERMES_SOURCE'])
from tools.memory_tool import load_on_disk_store
store=load_on_disk_store()
memory=store.format_for_system_prompt('memory') or ''
user=store.format_for_system_prompt('user') or ''
print(json.dumps({'native_memory_update_survives_restart':
 'Shawn confirmed a detailed weekly report' in memory and 'Shawn prefers a short weekly report' not in memory,
 'native_user_profile_survives_restart':'address the user as Shawn' in user}))'''])
        checks.update(json.loads(output))
        report={'hermes_revision':HERMES_REVISION,'checks':checks,'passed':all(checks.values())}
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
