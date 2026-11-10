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
print(json.dumps({'all_backend_baseline_paths_retained':len(baseline['baseline_files']),'original_GLM_docs_unchanged':len(old_docs),'historical_frontend_hashes':'PASS','main_baseline_history':'RETAINED','observed_main_remote_ref':main_ref},indent=2))
