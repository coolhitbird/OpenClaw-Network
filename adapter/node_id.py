"""
OpenClaw Network - ClawMesh Node ID Generation

生成符合规范的全局唯一节点标识符。

node_id 格式: CL-{ver}{type}{ts}{rand}{gene}{cks}
- ver (2 hex): 版本号, 当前 01
- type (1 char): 节点类型 S=Standard, B=Bot, G=Gateway, D=Daemon
- ts (8 hex): 时间戳（从 2025-01-01 00:00:00 UTC 起的秒数，4字节）
- rand (4 hex): 随机数 (0-65535) - 调整为 4 hex 提高唯一性
- gene (4 hex): 特征码（预留，从技能/版本/OS哈希，Phase 3 实现）
- cks (6 hex): 校验和（SHA256(raw)[:6]）

示例: CL-01S-5f3a1b2c-5a3a-0000-cks123 (注意: rand 为 4 位)
"""

import hashlib
import os
import time
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# 基准时间戳：2025-01-01 00:00:00 UTC
EPOCH = int(datetime(2025, 1, 1, tzinfo=timezone.utc).timestamp())

def _current_timestamp_hex() -> str:
    """当前时间戳（hex，8位）"""
    ts = int(time.time()) - EPOCH
    return f"{ts:08x}"

def _random_hex_4() -> str:
    """
    生成 4 个 hex 字符的随机数（0-65535，即 0xFFFF）。
    对应 rand 字段（4 hex 以确保同秒内唯一性足够高）。
    """
    r = int.from_bytes(os.urandom(2), 'big')  # 2 bytes = 16 bits
    return f"{r:04x}"

def _generate_gene() -> str:
    """
    生成节点特征码（4 hex）。

    TODO Phase 3: 从已安装技能列表、OpenClaw版本、操作系统特征哈希生成。
    目前返回固定值 '0000'。
    """
    return "0000"

def _checksum(raw_id: str) -> str:
    """计算校验和：SHA256(raw_id)[:6]"""
    h = hashlib.sha256(raw_id.encode('utf-8')).hexdigest()
    return h[:6]

def generate_node_id(node_type: str = 'S') -> str:
    """
    生成节点唯一标识符。

    Args:
        node_type: 节点类型字符 (S/B/G/D)

    Returns:
        完整的 node_id 字符串，如 "CL-01S-5f3a1b2c-5a3a-0000-cks123"
        注意：最后一段是 gene(4) + cks(6)，10 个字符，中间无分隔符
    """
    if node_type not in ('S', 'B', 'G', 'D'):
        raise ValueError(f"node_type must be one of 'S', 'B', 'G', 'D', got {node_type}")

    ver = "01"
    ts = _current_timestamp_hex()  # 8 hex chars
    rand = _random_hex_4()  # 4 hex chars
    gene = _generate_gene()  # 4 hex chars

    # 组装不含 checksum 的原始部分
    # 格式: CL-{ver}{type}-{ts}-{rand}-{gene}
    raw = f"CL-{ver}{node_type}-{ts}-{rand}-{gene}"
    cks = _checksum(raw)

    node_id = f"{raw}{cks}"  # gene + checksum，无分隔符
    return node_id

def verify_node_id(node_id: str) -> bool:
    """
    验证 node_id 格式和校验和。

    Returns:
        True 如果格式正确且校验和匹配，否则 False
    """
    try:
        parts = node_id.split('-')
        if len(parts) != 5:
            print(f"[DEBUG] parts length != 5: {len(parts)}, parts={parts}")
            return False

        prefix, type_ts, ts, rand, gene_cks = parts
        if prefix != "CL":
            print(f"[DEBUG] prefix != CL: {prefix}")
            return False

        # 解析前缀 CL-01S (3 字符: 2 ver + 1 type)
        if len(type_ts) != 3 or not type_ts.startswith('01'):
            print(f"[DEBUG] type_ts invalid: {type_ts}")
            return False
        node_type = type_ts[2]
        if node_type not in ('S', 'B', 'G', 'D'):
            print(f"[DEBUG] node_type invalid: {node_type}")
            return False

        # 解析各段长度
        if len(ts) != 8 or len(rand) != 4 or len(gene_cks) != 10:
            print(f"[DEBUG] lengths invalid: ts={len(ts)}, rand={len(rand)}, gene_cks={len(gene_cks)}")
            return False
        gene = gene_cks[:4]
        cks = gene_cks[4:]

        # 重新计算校验和
        raw = f"CL-01{node_type}-{ts}-{rand}-{gene}"
        expected_cks = _checksum(raw)
        if cks != expected_cks:
            print(f"[DEBUG] checksum mismatch: given={cks}, expected={expected_cks}, raw={raw}")
            return False
        return True
    except Exception as e:
        print(f"[DEBUG] Exception: {e}")
        return False

def save_node_id(node_id: str, config_dir: Optional[Path] = None) -> Path:
    """
    持久化 node_id 到配置文件。

    Args:
        node_id: 要保存的节点ID
        config_dir: 配置目录（默认 workspace/config）

    Returns:
        保存的文件路径
    """
    if config_dir is None:
        config_dir = Path("config")
    config_dir.mkdir(parents=True, exist_ok=True)

    file_path = config_dir / "node_id.txt"
    file_path.write_text(node_id.strip() + "\n", encoding='utf-8')
    return file_path

def load_node_id(config_dir: Optional[Path] = None) -> Optional[str]:
    """
    从配置文件加载 node_id。

    Returns:
        节点ID字符串，如文件不存在则返回 None
    """
    if config_dir is None:
        config_dir = Path("config")
    file_path = config_dir / "node_id.txt"
    if file_path.exists():
        return file_path.read_text(encoding='utf-8').strip()
    return None

# 如果直接运行，生成并显示示例
if __name__ == "__main__":
    # 生成 5 个示例
    print("Node ID 生成示例:")
    for i in range(5):
        nid = generate_node_id('S')
        valid = verify_node_id(nid)
        print(f"  {nid} - valid: {valid}")

    # 测试保存/加载
    test_id = generate_node_id('B')
    saved = save_node_id(test_id)
    loaded = load_node_id()
    print(f"\nSaved to: {saved}")
    print(f"Loaded: {loaded}")
    print(f"Match: {loaded == test_id}")
