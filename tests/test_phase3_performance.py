"""
Phase 3 Performance Benchmarks

测试加密操作性能：
- ECDH 密钥交换延迟
- AES-GCM 加密/解密吞吐量
- 1000 次加密往返耗时

运行: uv run python tests/test_phase3_performance.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from adapter.crypto import CryptoManager
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

def benchmark_ecdh(iterations: int = 100):
    """测试 ECDH 密钥交换性能"""
    times = []
    for _ in range(iterations):
        alice = CryptoManager("alice")
        bob = CryptoManager("bob")
        
        alice_pub = alice.generate_keypair()
        bob_pub = bob.generate_keypair()
        
        start = time.perf_counter()
        alice.compute_shared_secret(bob_pub)
        alice.derive_encryption_key(alice.compute_shared_secret(bob_pub))
        bob.compute_shared_secret(alice_pub)
        bob.derive_encryption_key(bob.compute_shared_secret(alice_pub))
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    
    avg = sum(times) / len(times)
    total = sum(times)
    print(f"[ECDH] {iterations} iterations: total={total:.4f}s, avg={avg*1000:.2f}ms")
    return avg

def benchmark_aes_gcm(iterations: int = 1000):
    """测试 AES-GCM 加密解密性能"""
    # 准备密钥
    alice = CryptoManager("alice")
    alice.generate_keypair()
    # 手动设置加密密钥（模拟 handshake 完成）
    other_pub = ec.generate_private_key(ec.SECP256R1()).public_key()
    shared = alice.key_pair.exchange(ec.ECDH(), other_pub)
    key = HKDF(hashes.SHA256(), 32, None, b"clawmesh-v1-encryption").derive(shared)
    alice.encryption_key = key
    
    plaintext = '{"type":"text","content":"Hello World!"}'
    
    times_enc = []
    times_dec = []
    for _ in range(iterations):
        start = time.perf_counter()
        encrypted = alice.encrypt_message(plaintext)
        times_enc.append(time.perf_counter() - start)
        
        start = time.perf_counter()
        decrypted = alice.decrypt_message(encrypted)
        times_dec.append(time.perf_counter() - start)
        assert decrypted == plaintext
    
    avg_enc = sum(times_enc) / len(times_enc)
    avg_dec = sum(times_dec) / len(times_dec)
    print(f"[AES-GCM] {iterations} ops: encrypt avg={avg_enc*1000:.2f}ms, decrypt avg={avg_dec*1000:.2f}ms")
    return avg_enc, avg_dec

def benchmark_message_throughput(messages_per_second: int = 1000, duration: float = 2.0):
    """测试消息吞吐量（理论值）"""
    alice = CryptoManager("alice")
    alice.generate_keypair()
    other_pub = ec.generate_private_key(ec.SECP256R1()).public_key()
    shared = alice.key_pair.exchange(ec.ECDH(), other_pub)
    key = HKDF(hashes.SHA256(), 32, None, b"clawmesh-v1-encryption").derive(shared)
    alice.encryption_key = key
    
    plaintext = '{"type":"text","content":"Performance test message"}'
    
    sent = 0
    start = time.perf_counter()
    while time.perf_counter() - start < duration:
        encrypted = alice.encrypt_message(plaintext)
        _ = alice.decrypt_message(encrypted)
        sent += 1
    elapsed = time.perf_counter() - start
    
    rate = sent / elapsed
    print(f"[Throughput] {sent} messages in {elapsed:.2f}s → {rate:.0f} msg/s")
    return rate

# ============ Main ============

if __name__ == "__main__":
    print("="*60)
    print("Phase 3 Performance Benchmarks")
    print("="*60)
    
    print("\n[1] ECDH Key Exchange (100 iterations)")
    avg_ecdh = benchmark_ecdh(100)
    
    print("\n[2] AES-GCM Encryption/Decryption (1000 iterations)")
    avg_enc, avg_dec = benchmark_aes_gcm(1000)
    
    print("\n[3] Message Throughput (2s burst)")
    rate = benchmark_message_throughput(1000, 2.0)
    
    print("\n" + "="*60)
    print("Benchmarks complete.")
    print("="*60)
