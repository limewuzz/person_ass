import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('backup_crypto', Path(__file__).parents[1]/'backup_crypto.py')
crypto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(crypto)


@pytest.fixture
def files(tmp_path):
    plain, enc, mac = [tmp_path/n for n in ('dump', 'enc', 'mac')]
    plain.write_bytes(b'local fake pg dump\x00'*4096)
    enc.write_text('a1'*32); enc.chmod(0o600)
    mac.write_text('b2'*32); mac.chmod(0o600)
    return plain, enc, mac, tmp_path/'backup', tmp_path/'restored'


def test_roundtrip_is_authenticated_and_private(files):
    plain, enc, mac, sealed, restored = files
    crypto.encrypt(plain, sealed, enc, mac)
    crypto.decrypt(sealed, restored, enc, mac)
    assert restored.read_bytes() == plain.read_bytes()
    assert sealed.stat().st_mode & 0o777 == 0o600
    assert restored.stat().st_mode & 0o777 == 0o600
    assert plain.read_bytes() not in sealed.read_bytes()


@pytest.mark.parametrize('part', ['ciphertext', 'header', 'mac'])
def test_tampering_rejected_before_any_decryption(files, monkeypatch, part):
    plain, enc, mac, sealed, restored = files
    crypto.encrypt(plain, sealed, enc, mac)
    target = Path(str(sealed)+'.hmac') if part == 'mac' else sealed
    value = bytearray(target.read_bytes())
    value[0 if part != 'ciphertext' else -1] ^= 1
    target.write_bytes(value)
    def forbidden(*a, **kw):
        pytest.fail('Must authenticate before running openssl')
    monkeypatch.setattr(crypto.subprocess, 'run', forbidden)
    with pytest.raises(ValueError): crypto.decrypt(sealed, restored, enc, mac)
    assert not restored.exists()
    assert not list(restored.parent.glob('.mwcp-restore-*'))


def test_rejects_shared_keys_and_insecure_permissions(files):
    plain, enc, mac, sealed, _ = files
    with pytest.raises(ValueError): crypto.encrypt(plain, sealed, enc, enc)
    mac.chmod(0o644)
    with pytest.raises(ValueError): crypto.encrypt(plain, sealed, enc, mac)
    assert not sealed.exists()


def test_wrong_key_and_existing_output_do_not_overwrite(files):
    plain, enc, mac, sealed, restored = files
    crypto.encrypt(plain, sealed, enc, mac)
    mac.write_text('c3'*32)
    with pytest.raises(ValueError): crypto.decrypt(sealed, restored, enc, mac)
    assert not restored.exists()
    restored.write_text('keep')
    with pytest.raises(ValueError): crypto.decrypt(sealed, restored, enc, mac)
    assert restored.read_text() == 'keep'
