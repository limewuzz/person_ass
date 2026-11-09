"""Finite-pattern public-source scan; reports locations, never matching secret bytes."""
import re,subprocess,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
files=subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')
patterns=[re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),re.compile(rb'AKIA[A-Z0-9]{16}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),re.compile(rb'Bearer\s+eyJ[A-Za-z0-9_.-]{70,}')]
issues=[]
for name in files:
 if not name:continue
 p=root/name
 if not p.exists():issues.append({'path':name,'reason':'tracked path missing'});continue
 if p.name.startswith('.env') and not p.name.endswith('.example'):issues.append({'path':name,'reason':'environment file forbidden'})
 b=p.read_bytes()
 for pattern in patterns:
  match=pattern.search(b)
  if match:issues.append({'path':name,'line':b[:match.start()].count(b'\n')+1,'reason':'secret-shaped literal'})
print(json.dumps({'scope':'tracked source only; PEM, AWS, GitHub PAT and literal bearer patterns; finite scan is not a proof of zero leakage','findings':issues},indent=2))
sys.exit(bool(issues))
