"""Authenticated backup envelope. Operates on local files/stdin only; no DB access.

AES-256-CBC with PBKDF2-SHA256 (200000 iterations), encrypt-then-HMAC-SHA256.
Independent file keys, authenticated header+ciphertext, verify BEFORE decryption.
Keys never enter subprocess argv, environment, stdout, or an exception message.
"""
from __future__ import annotations
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import stat
import struct
import subprocess
import sys
import tempfile

MAGIC = b'MWCP-BACKUP-1\n'
HEADER = json.dumps({'cipher': 'AES-256-CBC', 'kdf': 'PBKDF2-SHA256',
                     'iterations': 200000, 'salt_bytes': 8}, sort_keys=True).encode()


def salt_options():
    # OpenSSL 3.2 changed the PBKDF2 salt default to 16 bytes. Keep the
    # envelope portable to 3.0 (whose fixed/default size is 8 bytes).
    help_result = subprocess.run(['openssl', 'enc', '-help'],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return ['-saltlen', '8'] if b'-saltlen' in help_result.stderr else []


def read_key(path):
    path = Path(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ValueError('Key file must be private and regular')
        value = os.read(fd, 4097).strip()
        if len(value) < 32 or len(value) > 4096:
            raise ValueError('Key file length invalid')
        return value
    finally:
        os.close(fd)


def keys(enc, mac):
    a, b = read_key(enc), read_key(mac)
    if hmac.compare_digest(a, b):
        raise ValueError('Independent encryption and MAC keys required')
    # OpenSSL pass file is line based; gateb tool creates 64 ASCII hex characters.
    if any(c not in b'0123456789abcdefABCDEF' for c in a) or len(a) != 64:
        raise ValueError('Encryption key must contain 64 hexadecimal characters')
    return a, b


def digest_file(path, key):
    result = hmac.new(key, digestmod=hashlib.sha256)
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def publish(temp, target):
    # Hard link provides atomic publish-without-overwrite on the same filesystem.
    os.link(temp, target)


def encrypt(source, output, enc_key, mac_key):
    key, mac = keys(enc_key, mac_key)
    output = Path(output)
    if output.exists() or Path(str(output) + '.hmac').exists():
        raise ValueError('Backup output already exists')
    with tempfile.TemporaryDirectory(prefix='.mwcp-backup-', dir=output.parent) as tmp:
        tmp = Path(tmp)
        cipher, envelope = tmp/'cipher', tmp/'envelope'
        # Use an anonymous pipe for the passphrase, avoiding argv/path races.
        key_in, key_out = os.pipe()
        try:
            os.write(key_out, key + b'\n'); os.close(key_out); key_out = -1
            args = ['openssl', 'enc', '-aes-256-cbc', '-salt', '-pbkdf2',
                    '-iter', '200000', '-md', 'sha256', '-pass', f'fd:{key_in}', '-out', str(cipher)]
            args += salt_options()
            if str(source) != '-':
                with open(source, 'rb') as stream:
                    result = subprocess.run(args, stdin=stream, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.PIPE, pass_fds=(key_in,))
            else:
                result = subprocess.run(args, stdin=sys.stdin.buffer, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE, pass_fds=(key_in,))
            if result.returncode:
                raise ValueError('Backup encryption failed')
        finally:
            os.close(key_in)
            if key_out != -1: os.close(key_out)
        with open(envelope, 'wb') as target, open(cipher, 'rb') as stream:
            os.chmod(envelope, 0o600)
            target.write(MAGIC + struct.pack('>I', len(HEADER)) + HEADER)
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): target.write(chunk)
            target.flush(); os.fsync(target.fileno())
        signature = tmp/'signature'
        signature.write_text(digest_file(envelope, mac) + '\n'); signature.chmod(0o600)
        publish(signature, str(output) + '.hmac')
        try:
            publish(envelope, output)
        except BaseException:
            Path(str(output) + '.hmac').unlink()
            raise


def decrypt(source, output, enc_key, mac_key):
    key, mac = keys(enc_key, mac_key)
    output = Path(output)
    if output.exists(): raise ValueError('Restore output already exists')
    with tempfile.TemporaryDirectory(prefix='.mwcp-restore-', dir=output.parent) as tmp:
        tmp = Path(tmp)
        sealed = tmp/'sealed'
        # Verify a private immutable copy; never decrypt the mutable input path.
        with open(source, 'rb') as stream, open(sealed, 'wb') as target:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''): target.write(chunk)
        sealed.chmod(0o600)
        signature = Path(str(source) + '.hmac').read_text().strip()
        if len(signature) != 64 or any(c not in '0123456789abcdef' for c in signature) or not hmac.compare_digest(signature, digest_file(sealed, mac)):
            raise ValueError('Backup authentication failed; nothing decrypted')
        cipher, plain = tmp/'cipher', tmp/'plain'
        with open(sealed, 'rb') as stream:
            if stream.read(len(MAGIC)) != MAGIC: raise ValueError('Invalid backup envelope')
            raw = stream.read(4)
            if len(raw) != 4: raise ValueError('Invalid backup envelope')
            length = struct.unpack('>I', raw)[0]
            if length != len(HEADER) or stream.read(length) != HEADER:
                raise ValueError('Unsupported authenticated backup header')
            with open(cipher, 'wb') as target:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''): target.write(chunk)
        key_in, key_out = os.pipe()
        try:
            os.write(key_out, key + b'\n'); os.close(key_out); key_out = -1
            result = subprocess.run(['openssl', 'enc', '-d', '-aes-256-cbc', '-pbkdf2',
                '-iter', '200000', '-md', 'sha256', '-pass', f'fd:{key_in}',
                '-in', str(cipher), '-out', str(plain), *salt_options()], stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, pass_fds=(key_in,))
            if result.returncode: raise ValueError('Backup decryption failed')
            plain.chmod(0o600)
            publish(plain, output)
        finally:
            os.close(key_in)
            if key_out != -1: os.close(key_out)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['encrypt', 'decrypt'])
    parser.add_argument('source'); parser.add_argument('output')
    parser.add_argument('--enc-key-file', required=True)
    parser.add_argument('--mac-key-file', required=True)
    args = parser.parse_args()
    try:
        globals()[args.action](args.source, args.output, args.enc_key_file, args.mac_key_file)
    except (OSError, ValueError):
        parser.exit(1, 'Backup operation failed; no restore output published.\n')


if __name__ == '__main__': main()
