"""契约完整性回归测试（stdlib only）。

固化 v0.4 契约的版本指纹：文件哈希 + 路径/操作计数。
任何契约变更必须显式更新 VERIFICATION.md 并走评审，此测试会拦截静默篡改。
"""
import hashlib
import re
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parent.parent / "contracts"

EXPECTED_SHA256 = {
    "openapi.yaml": "d94462c44cd7c331470fc79731da29a7539d78f770b52288fce590ae3f52504f",
    "worker-protocol.schema.json": "a6d3c8b46173be068bbd218b719a46e189072323fedf10ec596a82cf07108d42",
    "capability.schema.json": "2df35f89aafb2379ea5bd0dd68be3a1a0261fb3585ad9611285995b4ccf0ce9c",
}

EXPECTED_PATHS = 79
EXPECTED_OPERATIONS = 95


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_contract_files_hash_match_v04():
    for name, expected in EXPECTED_SHA256.items():
        path = CONTRACTS / name
        assert path.exists(), f"missing contract: {name}"
        assert _sha256(path) == expected, (
            f"{name} hash changed — contract modified without review; "
            "update contracts/VERIFICATION.md via PR if intentional"
        )


def test_openapi_path_and_operation_counts():
    text = (CONTRACTS / "openapi.yaml").read_text()
    paths_section = re.search(r"^paths:\n(.*?)^components:", text, re.S | re.M)
    assert paths_section, "paths section not found"
    body = paths_section.group(1)
    paths = re.findall(r"^  /", body, re.M)
    ops = re.findall(r"^    (?:get|post|put|delete|patch):", body, re.M)
    assert len(paths) == EXPECTED_PATHS, f"paths={len(paths)} expected {EXPECTED_PATHS}"
    assert len(ops) == EXPECTED_OPERATIONS, f"operations={len(ops)} expected {EXPECTED_OPERATIONS}"


def test_no_placeholder_server_url_left_when_frozen():
    """冻结为生产契约前，占位 server 必须替换；CANDIDATE 阶段反向断言占位仍在。"""
    text = (CONTRACTS / "openapi.yaml").read_text()
    assert "control.example.invalid" in text, (
        "server placeholder was replaced — if freezing for production, "
        "update VERIFICATION.md and this test together"
    )
