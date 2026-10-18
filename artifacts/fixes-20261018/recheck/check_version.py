from pathlib import Path
import hashlib,json,os
ROOT=Path('D:/筆電2/資料探勘第一次作業/ezstore')
OUT=Path(__file__).parent
manifest=json.loads((ROOT/'artifacts/fixes-20261018/source-manifest.json').read_text(encoding='utf-8'))
changed=[name for name,digest in manifest.items() if not (ROOT/name).is_file() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest]
adc=Path(os.environ['APPDATA'])/'gcloud/application_default_credentials.json'
result={'compared_files':len(manifest),'changed_since_last_test':changed,'standard_local_adc_file_exists':adc.is_file(),'project_environment_set':bool(os.getenv('GOOGLE_CLOUD_PROJECT')),'credential_path_environment_set':bool(os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))}
(OUT/'source-and-auth.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False))
slides=json.loads((OUT.parent/'ezstore_reaudit_strict_20261018/EZStore-Agent-Workshop-LAB_AIG.pptx.json').read_text(encoding='utf-8'))
for slide in slides:
    if '有 GCP 的人' in slide['text'] or '助教' in slide['text']:
        print(json.dumps(slide,ensure_ascii=False))
