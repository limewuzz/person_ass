"""Build a source/static/evidence handoff tied to the exact clean Git commit. No deployment."""
from pathlib import Path
import subprocess,json,hashlib,zipfile,shutil
root=Path(__file__).resolve().parents[1]
def git(*a):return subprocess.check_output(['git',*a],cwd=root,text=True).strip()
assert not git('status','--porcelain'),'Packaging requires clean source'
head=git('rev-parse','HEAD');tree=git('rev-parse','HEAD^{tree}')
lock=json.loads((root/'contracts/CONTRACT-LOCK.json').read_text());sha=hashlib.sha256((root/'contracts/openapi.yaml').read_bytes()).hexdigest();assert sha==lock['sha256']
report_path=root/'frontend/evidence/release/integrated-release.json'
assert report_path.is_file(),'Run node scripts/mw.mjs test first'
report=json.loads(report_path.read_text());assert report['status']=='PASSED_UNIFIED_LOCAL_RC' and set(report['heads'].values())=={head},'Evidence must pass on this exact commit'
assert json.loads((root/'frontend/dist/build-meta.json').read_text())['head']==head
out=root/'release'/head[:12];out.mkdir(parents=True,exist_ok=True)
identity={'repository':'https://github.com/limewuzz/person_ass','target_branch':'v3.0','commit':head,'tree':tree,'contract_version':lock['version'],'contract_sha256':sha,'paths':lock['paths'],'operations':lock['operations'],'local_rc':'PASSED_UNIFIED_LOCAL_RC','deployment':'DEPLOYMENT_BLOCKED','deployed':False,'pg_runtime':'NOT_RUN'}
(out/'RELEASE-IDENTITY.json').write_text(json.dumps(identity,indent=2)+'\n')
subprocess.run(['git','archive','--format=zip','--prefix=MagicWorkshop/','--output='+str(out/'MagicWorkshop-source.zip'),head],cwd=root,check=True)
with zipfile.ZipFile(out/'MagicWorkshop-static-candidate.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in sorted((root/'frontend/dist').rglob('*')):
  if p.is_file():z.write(p,'dist/'+str(p.relative_to(root/'frontend/dist')))
 z.write(out/'RELEASE-IDENTITY.json','RELEASE-IDENTITY.json')
with zipfile.ZipFile(out/'MagicWorkshop-validation.zip','w',zipfile.ZIP_DEFLATED) as z:
 # Logs/JUnit and selected screenshots, plus all screenshot hashes; successful browser traces contain no credentials.
 ev=root/'frontend/evidence'
 for p in sorted((ev/'release').glob('*')):
  if p.is_file():z.write(p,'release/'+p.name)
 for n in ['unit-junit.xml','e2e-junit.xml','live-integration/junit.xml','live-integration/http-exchanges.json','session/junit.xml','screenshots/home-1600.png','screenshots/tasks-390.png','live-integration/screenshots/real-task-success.png']:
  p=ev/n
  if p.is_file():z.write(p,n)
 inventory=[]
 for folder in [ev/'screenshots',ev/'live-integration/screenshots']:
  for p in sorted(folder.glob('*.png')):inventory.append({'path':str(p.relative_to(ev)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
 for folder in [ev/'workspace',ev/'prefix']:
  for p in sorted(folder.glob('*')):
   if p.is_file() and p.suffix in {'.png','.xml'}:z.write(p,str(p.relative_to(ev)))
 z.writestr('SCREENSHOT-INVENTORY.json',json.dumps(inventory,indent=2))
 z.write(out/'RELEASE-IDENTITY.json','RELEASE-IDENTITY.json')
shutil.copyfile(root/'docs/GLM-DEPLOYMENT-HANDOFF.md',out/'GLM-DEPLOYMENT-HANDOFF.md')
files=[p for p in out.iterdir() if p.is_file() and p.name not in {'MANIFEST.json','SHA256SUMS.txt'}]
manifest={'identity':identity,'files':[{'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(files)]}
(out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
files.append(out/'MANIFEST.json')
(out/'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(files)))
print(json.dumps({'handoff_directory':str(out),'identity':identity},indent=2))
