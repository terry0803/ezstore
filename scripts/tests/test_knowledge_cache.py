"""Exercise the real PowerShell snapshot workflow without restarting real services."""
import os
from pathlib import Path
import shutil
import subprocess
import pytest

@pytest.mark.skipif(os.name!='nt' or not shutil.which('pwsh'),reason='Windows startup helper')
def test_sync_remembers_cache_and_copies_changed_knowledge(tmp_path):
    root=tmp_path/'repo';scripts=root/'scripts';scripts.mkdir(parents=True)
    script=scripts/'start-homework.ps1'
    shutil.copyfile(Path(__file__).resolve().parents[1]/script.name,script)
    knowledge=root/'knowledge/ezstore';knowledge.mkdir(parents=True)
    policy=knowledge/'policy.md';policy.write_text('before',encoding='utf-8')
    (root/'.env').write_text('AGENT_MODEL=test',encoding='utf-8')
    for name in ['docker-compose.yml','docker-compose.build.yml','docker-compose.advisor.yml']:
        (root/name).write_text('services: {}',encoding='utf-8')
    fake=tmp_path/'fake';fake.mkdir()
    (fake/'docker.cmd').write_text('@echo off\r\nexit /b 0\r\n',encoding='ascii')
    env={**os.environ,'PATH':str(fake)+os.pathsep+os.environ['PATH']}
    cache=tmp_path/'cache'
    def run(*args):
        subprocess.run(['pwsh','-NoProfile','-File',str(script),*args],check=True,env=env,capture_output=True,text=True)
    run('-DockerBindCache',str(cache),'-SkipBuild')
    first=list(cache.glob('snapshot-*/knowledge/policy.md'))
    assert len(first)==1 and first[0].read_text(encoding='utf-8')=='before'
    # A real user signature/edit is represented as changed bytes, not forged.
    policy.write_text('after-user-edit',encoding='utf-8')
    run('-Action','SyncKnowledge')
    import json
    override=json.loads((cache/'compose.bind-cache.json').read_text(encoding='utf-8-sig'))
    mounted=Path(override['services']['advisor']['volumes'][0]['source'])/'policy.md'
    assert mounted.read_text(encoding='utf-8')=='after-user-edit'
    assert first[0].read_text(encoding='utf-8')=='before'
    assert (root/'.docker/bind-cache-path.txt').read_text(encoding='utf-8-sig').strip()==str(cache)
