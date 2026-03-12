"""
Unit tests for node_id.py

Run: uv run python tests/test_node_id.py
"""

import sys
import os
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent / "adapter"))

from node_id import (
    generate_node_id,
    verify_node_id,
    save_node_id,
    load_node_id,
    _current_timestamp_hex,
    _random_hex,
    _checksum,
    _generate_gene,
    EPOCH
)

def test_timestamp_hex_format():
    """时间戳应该是8位hex"""
    ts = _current_timestamp_hex()
    assert len(ts) == 8
    int(ts, 16)  # 应该是合法的十六进制

def test_random_hex_format():
    """随机数应该是3个hex字节（6字符）"""
    r = _random_hex(3)
    assert len(r) == 6
    int(r, 16)

def test_checksum_length():
    """校验和应该是6个hex字符"""
    raw = "CL-01S-5f3a1b2c-5a3-0000"
    cks = _checksum(raw)
    assert len(cks) == 6

def test_generate_node_id_format():
    """生成的 node_id 应该符合格式"""
    for node_type in ('S', 'B', 'G', 'D'):
        nid = generate_node_id(node_type)
        # 格式: CL-01X-8hex-4hex-4hex-6hex (rand expanded to 4 hex)
        parts = nid.split('-')
        assert len(parts) == 5
        assert parts[0] == "CL"
        assert parts[1] == f"01{node_type}"
        assert len(parts[2]) == 8  # ts
        assert len(parts[3]) == 4  # rand (4 hex chars)
        assert len(parts[4]) == 10  # gene(4)+cks(6)

def test_verify_node_id_valid():
    """验证通过的 node_id"""
    nid = generate_node_id('S')
    assert verify_node_id(nid) is True

def test_verify_node_id_invalid_prefix():
    """无效前缀"""
    assert verify_node_id("XX-01S-5f3a1b2c-5a3-0000abc123") is False

def test_verify_node_id_invalid_type():
    """无效节点类型"""
    # types: S, B, G, D only
    nid = generate_node_id('S')
    parts = nid.split('-')
    # 篡改 type
    parts[1] = "01X"
    assert verify_node_id("-".join(parts)) is False

def test_verify_node_id_wrong_checksum():
    """篡改校验和"""
    nid = generate_node_id('S')
    parts = nid.split('-')
    # 修改最后一位
    parts[4] = parts[4][:-1] + ('0' if parts[4][-1] != '0' else '1')
    assert verify_node_id("-".join(parts)) is False

def test_uniqueness():
    """生成1000个，确保唯一性"""
    ids = set()
    for _ in range(1000):
        nid = generate_node_id('S')
        assert nid not in ids, f"Duplicate found: {nid}"
        ids.add(nid)
    assert len(ids) == 1000

def test_save_and_load(tmp_path: Path):
    """测试保存和加载"""
    test_id = generate_node_id('G')
    saved_path = save_node_id(test_id, config_dir=tmp_path)
    assert saved_path.exists()
    loaded = load_node_id(config_dir=tmp_path)
    assert loaded == test_id

def test_load_nonexistent():
    """加载不存在的文件应返回 None"""
    # 使用临时空目录
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        result = load_node_id(config_dir=Path(tmp))
        assert result is None

if __name__ == "__main__":
    # 直接运行测试
    print("Running tests...")
    test_timestamp_hex_format()
    print("[OK] timestamp format")
    test_random_hex_format()
    print("[OK] random format")
    test_checksum_length()
    print("[OK] checksum length")
    test_generate_node_id_format()
    print("[OK] node_id format")
    test_verify_node_id_valid()
    print("[OK] verify valid")
    test_verify_node_id_invalid_prefix()
    print("[OK] verify invalid prefix")
    test_verify_node_id_invalid_type()
    print("[OK] verify invalid type")
    test_verify_node_id_wrong_checksum()
    print("[OK] verify wrong checksum")
    test_uniqueness()
    print("[OK] uniqueness (1000 samples)")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        test_save_and_load(Path(tmp))
        print("[OK] save and load")

    test_load_nonexistent()
    print("[OK] load nonexistent returns None")

    print("\n[SUCCESS] All tests passed!")
