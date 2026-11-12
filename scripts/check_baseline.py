"""No baseline path deletion; original GLM documentation and historical frontend bytes stay intact."""
import subprocess,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1];baseline=json.loads((root/'docs/UNIFIED-BASELINE.json').read_text());base=baseline['backend_base']
missing=[p for p in baseline['baseline_files'] if not (root/p).is_file()];assert not missing,missing
old_docs=subprocess.check_output(['git','ls-tree','-r','--name-only',base,'--','docs'],cwd=root,text=True).splitlines()
relocated={'docs/r4_contract_check.py':'docs/archive/r4_contract_check-1.1.1.py'}
changed=[p for p in old_docs if (root/relocated.get(p,p)).read_bytes()!=subprocess.check_output(['git','show',base+':'+p],cwd=root)];assert not changed,changed
main_ref=subprocess.check_output(['git','rev-parse','origin/main'],cwd=root,text=True).strip()
subprocess.run(['git','merge-base','--is-ancestor',baseline['main_frozen'],main_ref],cwd=root,check=True)
history=json.loads((root/'frontend/docs/DESIGN-HASHES.json').read_text())
for p,x in history.items():
 b=(root/'frontend'/p).read_bytes();assert len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256']
archive=root/'releases/v3.0.1/drive-originals'
originals=json.loads((archive/'MANIFEST.json').read_text())['files']
assert {x['path'] for x in originals}=={'START-HERE.md','DEPLOYMENT.md','CHANGES-AND-KNOWN-ISSUES.md','PATCH.diff','VERSION.json','SHA256.json'}
for entry in originals:
 b=(archive/entry['path']).read_bytes();assert len(b)==entry['bytes'] and hashlib.sha256(b).hexdigest()==entry['sha256'],entry['path']
by_name={x['source_name']:x for x in originals}
for ref in json.loads((archive/'SHA256.json').read_text())['files']:
 entry=by_name[ref['name']];assert entry['bytes']==ref['bytes'] and entry['sha256']==ref['sha256']
assert (root/'patches/v3.0.1.patch').read_bytes()==(archive/'PATCH.diff').read_bytes()
print(json.dumps({'v3.0.1_Drive_originals_byte_verified':len(originals),'archive_patch_unchanged':True}))
print(json.dumps({'all_backend_baseline_paths_retained':len(baseline['baseline_files']),'original_GLM_docs_unchanged':len(old_docs),'historical_frontend_hashes':'PASS','main_baseline_history':'RETAINED','observed_main_remote_ref':main_ref},indent=2))
