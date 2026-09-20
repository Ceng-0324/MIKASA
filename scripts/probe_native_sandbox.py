#!/usr/bin/env python3
"""Verify pinned Hermes file/terminal tools in an actual offline Docker sandbox."""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mikasa.config import Config
from mikasa.native import HERMES_REVISION, prepare_profile, private_write

IMAGE = 'python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config/local/hermes-cch.json')
    p.add_argument('--image',default=IMAGE)
    p.add_argument('--report',required=True)
    args=p.parse_args(); base=Config.load(args.config)
    report_path=Path(args.report).resolve()
    if not report_path.is_relative_to(base.runtime):
        raise SystemExit('report must be under runtime')
    with tempfile.TemporaryDirectory(prefix='mks-',dir='/tmp') as directory:
        data=json.loads(json.dumps(base.data)); data['runtime']=directory
        config=Config(base.root,data)
        home,source,python,_=prepare_profile(config,config.owner)
        workspace=Path(directory)/'export'; workspace.mkdir()
        (workspace/'calc.py').write_text('VALUE = 1\n')
        native=json.loads((home/'config.yaml').read_text())
        native['terminal']={'backend':'docker','cwd':'/workspace','docker_image':args.image,
            'docker_volumes':[str(workspace)+':/workspace:rw'], 'docker_network':False,
            'container_persistent':False, 'docker_persist_across_processes':False,
            'docker_orphan_reaper':False, 'container_cpu':1, 'container_memory':256,
            'container_disk':0,'docker_run_as_host_user':True,
            'docker_extra_args':['--read-only'], 'docker_forward_env':[], 'env_passthrough':[]}
        private_write(home/'config.yaml',json.dumps(native))
        env={'PATH':os.environ.get('PATH','/usr/bin:/bin'),'HERMES_HOME':str(home),
             'PYTHONPATH':str(source), 'MIKASA_MODEL_API_KEY':'synthetic-secret-must-not-cross',
             'MIKASA_PROBE_TASK':'mikasa-sandbox-' + uuid.uuid4().hex,
             'MIKASA_CCH_TEST':'synthetic-secret-must-not-cross'}
        code='''import json,subprocess,os
from tools.file_tools import read_file_tool,write_file_tool
from tools.terminal_tool import terminal_tool,cleanup_all_environments
from tools.environments.docker import DockerEnvironment
checks={}
try:
 task=os.environ['MIKASA_PROBE_TASK']
 read=json.loads(read_file_tool('/workspace/calc.py',task_id=task))
 checks['native_read']='VALUE = 1' in json.dumps(read)
 write=json.loads(write_file_tool('/workspace/calc.py','VALUE = 2\\n',task_id=task))
 checks['native_write']=not write.get('error')
 command="python -c \\"import os; from calc import VALUE; assert VALUE == 2; assert not os.path.exists('/var/run/docker.sock'); assert not any('synthetic-secret' in v for v in os.environ.values()); print('sandbox-ok')\\""
 result=json.loads(terminal_tool(command,task_id=task,timeout=30))
 checks['native_terminal_and_secret_isolation']=result.get('exit_code')==0 and 'sandbox-ok' in result.get('output','')
 # Inspect only containers created under this unique task id; never touch unrelated containers.
 ids=subprocess.check_output(['docker','ps','-q','--filter','label=hermes-task-id='+task],text=True).split()
 checks['one_native_container']=len(ids)==1
 if ids:
  info=json.loads(subprocess.check_output(['docker','inspect',ids[0]],text=True))[0]
  host=info['HostConfig']
  checks['network_disabled']=host['NetworkMode']=='none'
  checks['rootfs_readonly']=host['ReadonlyRootfs']
  checks['resource_limits']=0<host['Memory']<=268435456 and 0<host['PidsLimit']<=256
  checks['no_new_privileges']=any('no-new-privileges' in v for v in host['SecurityOpt'])
  checks['no_docker_socket_mount']=not any(m['Destination']=='/var/run/docker.sock' for m in info['Mounts'])
finally:
 cleanup_all_environments()
 DockerEnvironment.wait_for_all_teardowns(timeout=15.0)
checks['container_removed']=not subprocess.check_output(['docker','ps','-aq','--filter','label=hermes-task-id='+task],text=True).strip()
print(json.dumps(checks))'''
        result=subprocess.run([str(python),'-c',code],cwd=home/'workspace',env=env,capture_output=True,text=True,timeout=120)
        if result.returncode:
            print(result.stderr[-2500:],file=sys.stderr)
            return 1
        checks=json.loads(result.stdout.strip().splitlines()[-1])
        checks['export_changed']= (workspace/'calc.py').read_text()=='VALUE = 2\n'
        report={'hermes_revision':HERMES_REVISION,'image':args.image,'checks':checks,'passed':all(checks.values())}
        report_path.parent.mkdir(parents=True,exist_ok=True)
        private_write(report_path,json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
        return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
