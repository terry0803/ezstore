"""Local self-evaluation, explicitly NOT the managed instructor grading service.

Generate genuine traces with agents-cli, evaluate them using the existing local
adapters, then reuse the original suite scoring and database checks. No ADC or
fake cloud credentials are supplied. Only the isolated test stack is accepted.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent

def load(name):
    path=HERE/(name+'.py')
    if name in ('grade_agent','link_presence'):
        path=HERE.parent/'grading'/(name+'.py')
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

grader=load('grade_agent')
metrics={name:load(file) for name,file in {
    'custom_response_quality':'response_quality',
    'refusal_or_action':'refusal_or_action_local',
    'link_present':'link_presence',
}.items()}

def text(content):
    return ''.join(part.get('text','') for part in (content or {}).get('parts',[]))

def instance(case):
    prompt=case.get('prompt')
    if not prompt:
        for turn in (case.get('agent_data') or {}).get('turns',[]):
            for event in turn.get('events',[]):
                if event.get('author')=='user' and event.get('content'):
                    prompt=event['content']
    responses=case.get('responses') or []
    if len(responses)!=1 or not text(responses[0].get('response')):
        raise ValueError(f"Missing or ambiguous response for {case.get('eval_case_id')}")
    return {'eval_case_id':case['eval_case_id'],'prompt':text(prompt),'response':responses[0]['response'],
            'reference':(case.get('reference') or {}).get('response'),
            'agent_data':case.get('agent_data') or {}}

def run_eval(agent_dir,dataset,config,output):
    trace_path=output/'traces.json'
    proc=subprocess.run(['agents-cli','eval','generate','--dataset',str(dataset),
        '--output',str(trace_path),'--url','http://127.0.0.1:58501','--app-name','quotation_agent',
        '--concurrency','1'],cwd=agent_dir,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (output/'generate.log').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf-8',newline='\n')
    if proc.returncode:
        raise RuntimeError('Trace generation failed; no valid grade was produced.\n'+(proc.stdout+'\n'+proc.stderr)[-5000:])
    trace=json.loads(trace_path.read_text(encoding='utf-8'))
    expected=json.loads(dataset.read_text(encoding='utf-8'))['eval_cases']
    cases=trace['eval_cases']
    if [c['eval_case_id'] for c in cases]!=[c['eval_case_id'] for c in expected]:
        raise ValueError('Generated case list does not match the unchanged input dataset')
    results=[]
    for case in cases:
        inp=instance(case)
        scores={name:metric.evaluate(inp) for name,metric in metrics.items()}
        scores['agent_turn_count']={'score':len(inp['agent_data'].get('turns',[]))}
        results.append({'response_candidate_results':[{'metric_results':scores}]})
        print(f"Local metrics: {case['eval_case_id']} "+json.dumps(scores,ensure_ascii=False),flush=True)
    result={'evaluation_dataset':[trace],'eval_case_results':results,
            'execution_mode':'local_adapters_not_managed_teacher_grader',
            'agent_model':os.environ.get('AGENT_MODEL'), 'judge_model':os.environ.get('JUDGE_MODEL'),
            'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.glob('*.py')}}
    (output/f'results_{time.time_ns()}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8',newline='\n')
    return True,'Completed local adapters; not a managed teacher grade.'

if __name__=='__main__':
    for flag,value in [('--backend','http://127.0.0.1:58080'),('--mcp-url','http://127.0.0.1:58010/mcp')]:
        if flag not in sys.argv or sys.argv[sys.argv.index(flag)+1]!=value:
            raise SystemExit(f'Required isolated target: {flag} {value}')
    if '--no-reseed' not in sys.argv:
        raise SystemExit('Pass --no-reseed after manually seeding only the isolated database.')
    grader.run_eval=run_eval
    sys.exit(grader.main())
