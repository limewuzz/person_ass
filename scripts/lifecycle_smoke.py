"""Exercise the public local start/stop CLI and refusal to reuse an occupied port."""
import subprocess,socket,time,json,urllib.request,urllib.error
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def command(name):return subprocess.run(['node','scripts/mw.mjs',name,'--static'],cwd=root,capture_output=True,text=True,timeout=45)
def open_port(port):
 with socket.socket() as s:s.settimeout(.2);return s.connect_ex(('127.0.0.1',port))==0
with socket.socket() as sentinel:
 sentinel.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
 sentinel.bind(('127.0.0.1',5174));sentinel.listen(1)
 r=command('start');assert r.returncode!=0,'start unexpectedly reused occupied port'
 assert sentinel.getsockname()[1]==5174,'sentinel was altered'
started=False
try:
 r=command('start');assert r.returncode==0,r.stderr;started=True
 assert urllib.request.urlopen('http://127.0.0.1:5174/',timeout=3).status==200
 assert urllib.request.urlopen('http://127.0.0.1:8127/api/v1/health/live',timeout=3).status==200
 try:urllib.request.urlopen('http://127.0.0.1:8127/api/v1/health/ready',timeout=3);raise AssertionError('readiness incorrectly healthy')
 except urllib.error.HTTPError as e:assert e.code==503
finally:
 if started:
  stopped=command('stop');assert stopped.returncode==0,stopped.stderr
for _ in range(100):
 if not any(open_port(p) for p in [5174,8127,8128]):break
 time.sleep(.1)
assert not any(open_port(p) for p in [5174,8127,8128]),'owned listeners survived stop'
result={'occupied_port_refused':True,'existing_sentinel_preserved':True,'start_api_bff_static':'PASS','live':200,'ready':503,'stop_owned_listeners':'PASS'}
print(json.dumps(result,indent=2))
