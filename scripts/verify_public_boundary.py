"""Bounded, anonymous website checks. No tokens, cookies, writes or response bodies."""
import argparse,json,datetime,urllib.request,urllib.error,urllib.parse,sys
p=argparse.ArgumentParser();p.add_argument('--origin',required=True);p.add_argument('--output');a=p.parse_args()
u=urllib.parse.urlsplit(a.origin)
if u.scheme!='https' or u.username or u.password or u.path or u.query or u.fragment:
    raise SystemExit('Use an exact authorized HTTPS origin')
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
client=urllib.request.build_opener(NoRedirect())
rows=[]
for path in ['me','tasks','nodes','audit','events']:
    try:r=client.open(a.origin+'/api/v1/'+path,timeout=10)
    except urllib.error.HTTPError as e:r=e
    except (OSError,urllib.error.URLError) as e:
        rows.append({'path':'/api/v1/'+path,'result':'FAIL','reason':type(e).__name__});continue
    rows.append({'path':'/api/v1/'+path,'status':r.status,'result':'PASS' if r.status==401 else 'FAIL','cache_control':r.headers.get('Cache-Control')})
    r.close()
report={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'origin':a.origin,'scope':'ANONYMOUS_READ_ONLY_NO_BODY','checks':rows,'result':'PASS' if all(r['result']=='PASS' for r in rows) else 'BLOCKED'}
if a.output:__import__('pathlib').Path(a.output).write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2));sys.exit(report['result']!='PASS')
