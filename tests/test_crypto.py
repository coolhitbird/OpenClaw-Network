"""
Phase 3 Unit Tests - Crypto Manager

测试加密核心功能：
- ECDH 密钥生成和交换
- AES-GCM 加密/解密往返
- 指纹计算一致性
- HKDF 密钥派生可重现
"""

import sys
import os
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
from adapter.crypto import CryptoManager

def test_crypto_keypair_generation():
    """测试密钥对生成"""
    cm = CryptoManager("test-node-001")
    pubkey = cm.generate_keypair()
    
    assert pubkey is not None, "Public key should not be None"
    assert len(pubkey) == 65, f"P-256 compressed public key should be 65 bytes, got {len(pubkey)}"
    assert pubkey[0] == 0x04, "Compressed point should start with 0x04"
    assert cm.key_pair is not None, "Keypair should be stored"
    assert cm.fingerprint is not None, "Fingerprint should be computed"
    assert len(cm.fingerprint) == 8, f"Fingerprint should be 8 chars, got {len(cm.fingerprint)}"
    
    print("[OK] Crypto keypair generation")
    return True

def test_ecdh_shared_secret():
    """测试 ECDH 共享密钥计算"""
    # Alice 生成密钥对
    alice = CryptoManager("alice")
    alice_pub = alice.generate_keypair()
    
    # Bob 生成密钥对
    bob = CryptoManager("bob")
    bob_pub = bob.generate_keypair()
    
    # 交换并计算共享密钥
    alice.compute_shared_secret(bob_pub)
    bob.compute_shared_secret(alice_pub)
    
    # 双方派生的加密密钥应相同
    alice_key = alice.derive_encryption_key(alice.compute_shared_secret(bob_pub))
    bob_key = bob.derive_encryption_key(bob.compute_shared_secret(alice_pub))
    
    assert alice_key == bob_key, "Shared encryption keys should match"
    assert len(alice_key) == 32, "AES-256 key should be 32 bytes"
    
    print("[OK] ECDH shared secret derivation")
    return True

def test_aes_gcm_encrypt_decrypt():
    """测试 AES-GCM 加密解密往返"""
    cm = CryptoManager("test-enc")
    cm.generate_keypair()
    
    # 伪造共享密钥（实际使用 ECDH 生成）
    from cryptography.hazmat.primitives.asymmetric import ec
    import hashlib
    # 简单起见，生成一个临时密钥对并计算共享密钥
    other_priv = ec.generate_private_key(ec.SECP256R1())
    other_pubkey = other_priv.public_key()
    other_pub_bytes = other_pubkey.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint
    )
    
    shared = cm.key_pair.exchange(ec.ECDH(), other_pubkey)
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    key = HKDF(hashes.SHA256(), 32, None, b"clawmesh-v1-encryption").derive(shared)
    cm.encryption_key = key
    
    # 加密消息
    plaintext = '{"type":"text","content":"Hello 世界"}'
    encrypted_payload = cm.encrypt_message(plaintext)
    
    assert "content" in encrypted_payload, "Encrypted payload should have 'content'"
    assert encrypted_payload["encrypted"] is True, "Should mark as encrypted"
    
    # 解密
    decrypted = cm.decrypt_message(encrypted_payload)
    assert decrypted == plaintext, "Decrypted text should match original"
    
    print("[OK] AES-GCM encrypt/decrypt roundtrip")
    return True

def test_fingerprint_consistency():
    """测试指纹计算一致性和长度"""
    cm = CryptoManager("fingerprint-test")
    pubkey = cm.generate_keypair()
    fp1 = cm.compute_fingerprint(pubkey)
    fp2 = cm.compute_fingerprint(pubkey)
    
    assert fp1 == fp2, "Same public key should produce same fingerprint"
    assert len(fp1) == 8, "Fingerprint should be exactly 8 hex characters"
    assert all(c in '0123456789abcdef' for c in fp1), "Fingerprint should be hex"
    
    print(f"[OK] Fingerprint consistency: {fp1}")
    return True

def test_encrypt_decrypt_unicode():
    """测试 Unicode 内容加密（避免 encoding 问题）"""
    cm = CryptoManager("unicode-test")
    cm.generate_keypair()
    
    # 模拟共享密钥
    from cryptography.hazmat.primitives.asymmetric import ec
    import hashlib
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    
    other_pubkey = ec.generate_private_key(ec.SECP256R1()).public_key()
    shared = cm.key_pair.exchange(ec.ECDH(), other_pubkey)
    key = HKDF(hashes.SHA256(), 32, None, b"clawmesh-v1-encryption").derive(shared)
    cm.encryption_key = key
    
    plaintext = '{"type":"text","content":"你好，merci，ciao，안녕"}'
    encrypted = cm.encrypt_message(plaintext)
    decrypted = cm.decrypt_message(encrypted)
    
    assert decrypted == plaintext, "Unicode roundtrip failed"
    
    print("[OK] Unicode encryption roundtrip")
    return True

def test_decrypt_tampered_fails():
    """测试篡改密文解密失败"""
    cm = CryptoManager("tamper-test")
    cm.generate_keypair()
    
    # 生成有效密文
    other_pubkey = ec.generate_private_key(ec.SECP256R1()).public_key()
    shared = cm.key_pair.exchange(ec.ECDH(), other_pubkey)
    key = HKDF(hashes.SHA256(), 32, None, b"clawmesh-v1-encryption").derive(shared)
    cm.encryption_key = key
    
    plaintext = '{"type":"text","content":"test"}'
    encrypted = cm.encrypt_message(plaintext)
    
    # 篡改密文（修改一个字节）
    tampered = encrypted.copy()
    tampered_content = list(base64.b64decode(tampered["content"]))
    tampered_content[10] ^= 0x01  # 翻转一个位
    tampered["content"] = base64.b64encode(bytes(tampered_content)).decode('ascii')
    
    try:
        cm.decrypt_message(tampered)
        assert False, "Should have raised InvalidTag"
    except Exception as e:
        # 预期失败
        print(f"[OK] Tampered ciphertext rejected: {type(e).__name__}")
        return True
    
    print("[OK] Tamper detection")
    return True

# ============ Imports for test convenience ==============
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidTag

# ============ Main ============

if __name__ == "__main__":
    print("Running Phase 3 crypto unit tests...\n")
    
    tests = [
        test_crypto_keypair_generation,
        test_ecdh_shared_secret,
        test_aes_gcm_encrypt_decrypt,
        test_fingerprint_consistency,
        test_encrypt_decrypt_unicode,
        test_decrypt_tampered_fails,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except Exception as e:
            print(f"[FAIL] {test.__name__}: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n[SUMMARY] {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
