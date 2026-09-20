#!/usr/bin/env python3
"""Pinned-SDK verification of legacy import and native plugin/skill policy; no model calls."""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.native import HERMES_REVISION, prepare_profile
from mikasa.store import Store


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='config/local/hermes-cch.json')
    args = p.parse_args()
    base = Config.load(args.config)
    with tempfile.TemporaryDirectory(prefix='mko-', dir='/tmp') as directory:
        data = json.loads(json.dumps(base.data)); data['runtime'] = directory
        config = Config(base.root, data)
        store = Store(config.runtime)
        session = 'a'*32
        with store.connect() as db:
            db.execute('INSERT INTO chats(id,actor,model,created) VALUES(?,?,?,0)',(session,config.owner,'gpt-6-astra'))
            db.execute('INSERT INTO chats(id,actor,model,created) VALUES(?,?,?,0)',('b'*32,'unrelated','gpt-6-astra'))
            for i in range(51):
                db.execute('INSERT INTO chat_turns(chat_id,request_key,message,response,created) VALUES(?,?,?,?,?)',
                           (session,str(i),f'user-{i}',json.dumps({'kind':'chat','reply':f'reply-{i}'}),i))
            db.execute('INSERT INTO chat_turns(chat_id,request_key,message,response,created) VALUES(?,?,?,?,99)',
                       (session,'command','/model',json.dumps({'kind':'status','reply':'model menu'})))
        legacy_digest = hashlib.sha256(store.path.read_bytes()).hexdigest()
        home, source, python, _ = prepare_profile(config, config.owner)
        env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'), 'HERMES_HOME':str(home), 'MIKASA_HERMES_SOURCE':str(source)}
        command = [str(python), str(base.root/'workers/hermes/import_legacy.py'),str(store.path),config.owner]
        def execute(argv):
            r = subprocess.run(argv, env=env, cwd=home/'workspace', capture_output=True, text=True, timeout=60)
            if r.returncode:
                raise RuntimeError('offline SDK check failed: '+r.stderr[-1800:])
            return r.stdout
        execute(command); execute(command)
        with sqlite3.connect(home/'state.db') as db:
            rows = db.execute('SELECT role,content FROM messages WHERE session_id=? ORDER BY id',(session,)).fetchall()
            checks = {'all_51_turns_imported':len(rows)==102,
                      'import_order_and_idempotency':rows==[item for i in range(51) for item in [('user',f'user-{i}'),('assistant',f'reply-{i}')]],
                      'unrelated_actor_not_imported':db.execute('SELECT COUNT(*) FROM sessions WHERE id=?',('b'*32,)).fetchone()[0]==0,
                      'old_database_untouched':hashlib.sha256(store.path.read_bytes()).hexdigest()==legacy_digest}
        output = execute([str(python),'-c', '''import os,sys,json
from pathlib import Path
sys.path.insert(0,os.environ['MIKASA_HERMES_SOURCE'])
from hermes_cli.plugins import discover_plugins,get_plugin_manager,get_pre_tool_call_directive,render_system_prompt_sections
from agent.skill_commands import build_auto_load_prompt
from tools.memory_tool import memory_tool,load_on_disk_store
discover_plugins()
p = next(p for p in get_plugin_manager().list_plugins() if p['name']=='mikasa')
home=Path(os.environ['HERMES_HOME'])
prompt,loaded,missing=build_auto_load_prompt(home_override=home)
sections=''.join(s.content for s in render_system_prompt_sections({}))
engineering=[]
for kind in ('plan','implement','review'):
 names=['mikasa-persona','mikasa-'+kind]
 body,found,absent=build_auto_load_prompt(user_config={'skills':{'auto_load':names}},home_override=home)
 engineering.append(found==names and not absent and all((home/'policy'/name).read_text() in sections for name in ('engineering-contract.md','engineering-workflow.md')))
store=load_on_disk_store()
old='Offline fixture: Shawn prefers a short weekly report.'
new='Offline fixture: Shawn confirmed a detailed weekly report; replaces the earlier short format.'
added=json.loads(memory_tool(action='add',target='memory',content=old,store=store))
replaced=json.loads(memory_tool(action='replace',target='memory',old_text=old,content=new,store=store))
user=json.loads(memory_tool(action='add',target='user',content='Offline fixture: address the user as Shawn.',store=store))
print(json.dumps({'plugin_loaded':p['enabled'] and not p['error'],
 'native_persona_auto_load':'mikasa-persona' in loaded and not missing and 'do not reconstruct personality' in prompt,
 'native_engineering_skills_and_canonical_sections':all(engineering),
 'native_memory_convention_update':all(r.get('success') and not r.get('staged') for r in (added,replaced,user)),
 'tool_policy_blocks_side_effects':all(get_pre_tool_call_directive(n,{})[0]=='block' for n in ['terminal','write_file','skill_manage','send_message']),
 'native_memory_and_readonly_skills_allowed':all(get_pre_tool_call_directive(n,{})[0] is None for n in ['memory','skill_view','skills_list'])}))'''])
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
