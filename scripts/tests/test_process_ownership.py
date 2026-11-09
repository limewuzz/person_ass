"""The stop command must never signal a reused or unowned process."""
from pathlib import Path
import subprocess,sys,json,shutil
import pytest
SOURCE=Path(__file__).resolve().parents[1]/'mw.mjs'
@pytest.mark.parametrize('wrong_ticks',[True,False])
def test_stop_refuses_a_foreign_or_reused_pid(tmp_path,wrong_ticks):
    (tmp_path/'scripts').mkdir();(tmp_path/'.runtime').mkdir();shutil.copyfile(SOURCE,tmp_path/'scripts/mw.mjs')
    owned_by_test=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
    try:
        ticks=Path(f'/proc/{owned_by_test.pid}/stat').read_text().split(') ')[1].split()[19]
        state={'pid':owned_by_test.pid,'start_ticks':'0' if wrong_ticks else ticks,'nonce':'not-in-child-command-line','root':str(tmp_path)}
        (tmp_path/'.runtime/local.json').write_text(json.dumps(state))
        result=subprocess.run(['node','scripts/mw.mjs','stop'],cwd=tmp_path,capture_output=True,text=True)
        assert result.returncode!=0 and 'ownership mismatch' in result.stderr
        assert owned_by_test.poll() is None
    finally:owned_by_test.terminate();owned_by_test.wait(timeout=5)
def test_stop_cleans_stale_state_without_signalling(tmp_path):
    (tmp_path/'scripts').mkdir();(tmp_path/'.runtime').mkdir();shutil.copyfile(SOURCE,tmp_path/'scripts/mw.mjs')
    (tmp_path/'.runtime/local.json').write_text(json.dumps({'pid':2147483647,'nonce':'stale','root':str(tmp_path)}))
    result=subprocess.run(['node','scripts/mw.mjs','stop'],cwd=tmp_path,capture_output=True,text=True)
    assert result.returncode==0 and 'no process signalled' in result.stdout
    assert not (tmp_path/'.runtime/local.json').exists()
