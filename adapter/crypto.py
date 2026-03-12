"""
ClawMesh - Crypto Manager (Phase 3)

实现端到端加密和身份验证功能。

功能：
- ECDH 密钥协商（NIST P-256）
- AES-256-GCM 消息加密/解密
- 公钥指纹计算（用于人工验证）
- HKDF 密钥派生

设计原则：
- 每个连接使用临时密钥（Forward Secrecy）
- 加密失败立即断开连接
- 指纹验证可选但推荐（首次连接）
"""

import os
import base64
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass, field
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag

logger = logging.getLogger(__name__)

# ============= 配置常量 =============

CURVE = ec.SECP256R1()  # NIST P-256
HKDF_INFO = b"clawmesh-v1-encryption"  # 密钥派生 info
FINGERPRINT_SIZE = 8  # 指纹长度（字符数）

# ============= 数据类 ==============

@dataclass
class CryptoConfig:
    """加密配置"""
    mode: str = "required"  # "required" | "optional" | "disabled"
    require_fingerprint_verification: bool = True
    allow_fallback: bool = False
    trusted_fingerprints_file: str = "config/trusted_fingerprints.json"

@dataclass
class HandshakeState:
    """Handshake 状态跟踪"""
    node_id: str
    crypto: 'CryptoManager'
    mode: str  # required/optional/disabled
    verified: bool = False

# ============= Crypto Manager ==============

class CryptoManager:
    """
    管理单个连接的加密状态
    
    生命周期：
    1. generate_keypair() - 生成临时 ECDH 密钥对
    2. compute_shared_secret(peer_pubkey_bytes) - 计算共享密钥
    3. derive_encryption_key() - 派生 AES-256 密钥
    4. encrypt_message() / decrypt_message() - 消息加解密
    5. compute_fingerprint() - 计算自己的指纹（显示给对方）
    6. verify_fingerprint(peer_fp) - 验证对方指纹
    """
    
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.key_pair: Optional[ec.EllipticCurvePrivateKey] = None
        self.peer_public_key: Optional[ec.EllipticCurvePublicKey] = None
        self.encryption_key: Optional[bytes] = None
        self.fingerprint: Optional[str] = None
        self._handshake_complete: bool = False
    
    def generate_keypair(self) -> bytes:
        """
        生成临时 ECDH 密钥对
        
        Returns:
            public_key_bytes: 压缩格式公钥（65 bytes，0x04 前缀）
        """
        self.key_pair = ec.generate_private_key(CURVE)
        public_key = self.key_pair.public_key()
        
        # 序列化为压缩格式（65 bytes: 0x04 + X + Y）
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.CompressedPoint
        )
        
        # 计算自己的指纹（用于对方验证）
        self.fingerprint = self.compute_fingerprint(public_bytes)
        
        logger.debug(f"Generated ECDH keypair for {self.node_id}, fingerprint: {self.fingerprint}")
        return public_bytes
    
    def compute_shared_secret(self, peer_public_key_bytes: bytes) -> bytes:
        """
        与对方公钥计算共享秘密
        
        Args:
            peer_public_key_bytes: 对方的压缩公钥（65 bytes）
            
        Returns:
            shared_secret: 32 bytes（P-256 输出长度）
            
        Raises:
            ValueError: 公钥格式无效
        """
        try:
            peer_public_key = ec.EllipticCurvePublicKey.from_encoded_point(CURVE, peer_public_key_bytes)
        except Exception as e:
            logger.error(f"Failed to deserialize peer public key: {e}")
            raise ValueError("Invalid peer public key") from e
        
        # 计算 ECDH 共享秘密
        shared_secret = self.key_pair.exchange(ec.ECDH(), peer_public_key)
        self.peer_public_key = peer_public_key
        
        logger.debug(f"Computed shared secret for {self.node_id} ({len(shared_secret)} bytes)")
        return shared_secret
    
    def derive_encryption_key(self, shared_secret: bytes) -> bytes:
        """
        使用 HKDF 派生加密密钥
        
        Args:
            shared_secret: ECDH 共享秘密（32 bytes）
            
        Returns:
            encryption_key: AES-256 密钥（32 bytes）
        """
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=HKDF_INFO
        )
        self.encryption_key = hkdf.derive(shared_secret)
        
        logger.debug(f"Derived encryption key for {self.node_id}")
        return self.encryption_key
    
    def encrypt_message(self, message_plaintext: str) -> Dict[str, Any]:
        """
        加密整个消息内容
        
        Args:
            message_plaintext: UTF-8 字符串（原始消息 JSON 的字符串）
            
        Returns:
            dict: 加密后的 payload 字典
                {
                    "content": "base64(iv + ciphertext + tag)",
                    "encrypted": True
                }
                
        Raises:
            RuntimeError: 加密前未完成密钥派生
        """
        if not self.encryption_key:
            raise RuntimeError("Encryption key not derived. Call compute_shared_secret() and derive_encryption_key() first.")
        
        # 生成随机 nonce（12 bytes）
        nonce = os.urandom(12)
        
        # 使用 AES-GCM 加密
        aesgcm = AESGCM(self.encryption_key)
        ciphertext = aesgcm.encrypt(nonce, message_plaintext.encode('utf-8'), None)
        # ciphertext 格式: ciphertext_bytes + tag_bytes (16 bytes)
        
        # 合并传输: iv + ciphertext + tag
        encrypted_data = nonce + ciphertext
        
        return {
            "content": base64.b64encode(encrypted_data).decode('ascii'),
            "encrypted": True
        }
    
    def decrypt_message(self, encrypted_payload: Dict[str, Any]) -> str:
        """
        解密消息
        
        Args:
            encrypted_payload: 包含 "content" (base64 string) 的字典
            
        Returns:
            plaintext: 解密后的 UTF-8 字符串
            
        Raises:
            RuntimeError: 未完成密钥派生
            InvalidTag: 认证失败（密文被篡改或密钥错误）
            ValueError: 数据格式错误
        """
        if not self.encryption_key:
            raise RuntimeError("Decryption attempted before key derivation")
        
        encrypted_data = base64.b64decode(encrypted_payload["content"])
        
        # 拆分 nonce (12) + ciphertext + tag (16)
        if len(encrypted_data) < 28:  # 12 nonce + 16 tag 最小
            raise ValueError("Encrypted data too short")
        
        nonce = encrypted_data[:12]
        ciphertext_with_tag = encrypted_data[12:]
        
        aesgcm = AESGCM(self.encryption_key)
        try:
            plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_with_tag, None)
        except InvalidTag as e:
            logger.error(f"Decryption failed: Invalid tag (tampered or wrong key)")
            raise
        
        return plaintext_bytes.decode('utf-8')
    
    def compute_fingerprint(self, public_key_bytes: Optional[bytes] = None) -> str:
        """
        计算公钥指纹（用于人工验证）
        
        Args:
            public_key_bytes: 公钥字节。如果 None，使用自己的公钥。
            
        Returns:
            fingerprint: 8 字符十六进制字符串（SHA256 前 4 字节）
        """
        if public_key_bytes is None:
            if not self.key_pair:
                raise RuntimeError("Keypair not generated yet")
            public_key_bytes = self.key_pair.public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.CompressedPoint
            )
        
        digest = hashes.Hash(hashes.SHA256())
        digest.update(public_key_bytes)
        full = digest.finalize()
        
        # 取前 4 字节 → 8 个十六进制字符
        fingerprint = full[:4].hex()
        return fingerprint
    
    def verify_fingerprint(self, peer_fingerprint: str, peer_public_key_bytes: bytes) -> bool:
        """
        验证对方公钥指纹是否匹配
        
        流程：
        1. 使用 received public_key 计算 fingerprint
        2. 与提供的 peer_fingerprint 比对
        3. 一致则返回 True
        
        Args:
            peer_fingerprint: 对方声称的指纹（8 hex 字符）
            peer_public_key_bytes: 对方的公钥字节
            
        Returns:
            bool: 是否匹配
        """
        computed = self.compute_fingerprint(peer_public_key_bytes)
        
        if computed == peer_fingerprint:
            logger.info(f"Fingerprint verified: {peer_fingerprint}")
            return True
        else:
            logger.warning(f"Fingerprint mismatch: expected {peer_fingerprint}, got {computed}")
            return False
    
    def to_dict(self) -> Dict[str, Any]:
        """序列化 crypto 状态（仅用于调试/日志）"""
        return {
            "node_id": self.node_id,
            "has_keypair": self.key_pair is not None,
            "has_peer_key": self.peer_public_key is not None,
            "has_encryption_key": self.encryption_key is not None,
            "fingerprint": self.fingerprint,
            "handshake_complete": self._handshake_complete
        }

# ============= Helper: Trusted Fingerprints Store ==============

class TrustedFingerprints:
    """管理已信任的节点指纹"""
    
    def __init__(self, filepath: str):
        self.filepath = filepath
        self._store: Dict[str, str] = {}  # node_id -> fingerprint
        self._load()
    
    def _load(self):
        """从 JSON 文件加载"""
        try:
            import json
            with open(self.filepath, 'r') as f:
                self._store = json.load(f)
            logger.info(f"Loaded {len(self._store)} trusted fingerprints from {self.filepath}")
        except FileNotFoundError:
            self._store = {}
            logger.info(f"No trusted fingerprints file found, starting fresh")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse trusted fingerprints: {e}, starting fresh")
            self._store = {}
    
    def save(self):
        """保存到 JSON 文件"""
        import json
        os.makedirs(os.path.dirname(self.filepath) or ".", exist_ok=True)
        with open(self.filepath, 'w') as f:
            json.dump(self._store, f, indent=2)
        logger.info(f"Saved {len(self._store)} trusted fingerprints")
    
    def get(self, node_id: str) -> Optional[str]:
        """获取已信任的指纹"""
        return self._store.get(node_id)
    
    def set(self, node_id: str, fingerprint: str):
        """添加/更新信任指纹"""
        if node_id in self._store:
            logger.info(f"Updating trusted fingerprint for {node_id}: {self._store[node_id]} -> {fingerprint}")
        else:
            logger.info(f"Adding new trusted fingerprint for {node_id}: {fingerprint}")
        self._store[node_id] = fingerprint
        self.save()
    
    def verify(self, node_id: str, expected_fingerprint: str) -> bool:
        """
        验证节点指纹
        
        Args:
            node_id: 节点 ID
            expected_fingerprint: 期望的指纹
            
        Returns:
            bool: 验证通过
        """
        stored = self.get(node_id)
        if stored is None:
            return False  # 未知节点，需要首次验证
        
        if stored == expected_fingerprint:
            return True
        else:
            logger.warning(f"Fingerprint changed for {node_id}: stored={stored}, got={expected_fingerprint}")
            return False
    
    def list(self) -> Dict[str, str]:
        """列出所有信任指纹"""
        return self._store.copy()

# 全局单例（可选）
_global_store: Optional[TrustedFingerprints] = None

def get_trusted_fingerprints(filepath: str = "config/trusted_fingerprints.json") -> TrustedFingerprints:
    global _global_store
    if _global_store is None or _global_store.filepath != filepath:
        _global_store = TrustedFingerprints(filepath)
    return _global_store
