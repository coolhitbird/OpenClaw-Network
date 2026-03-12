# ClawMesh Phase 3 详细设计 - 加密与安全

**版本**: 1.0  
**日期**: 2026-03-12  
**项目**: ClawMesh (OpenClaw Network)  
**Phase**: 3 - 加密与安全  
**状态**: Implementation (2026-03-12)

---

## 1. Phase 3 目标

### 核心目标
- 实现端到端加密（E2EE）防止中间人监听
- 实现身份验证和防篡改（数字签名）
- 设计密钥协商协议（ECDH）
- 支持密钥指纹人工验证流程（初始信任锚）
- 兼容现有的明文连接和渐进式迁移

### 成功标准
- [ ] 所有节点间通信默认加密（可配置明文兼容模式）
- [ ] 握手阶段完成 ECDH 密钥交换
- [ ] 消息使用 AES-GCM 加密（认证加密）
- [ ] 提供指纹验证机制，防止 MITM
- [ ] 现有 demo 可无缝升级到加密模式
- [ ] 向后兼容：明文节点仍可连接（降级警告）

---

## 2. 威胁模型与安全需求

### 威胁
1. **窃听**: 网络嗅探获取消息内容
2. **篡改**: 中间人修改消息内容
3. **伪装**: 攻击者伪装成合法节点
4. **重放**: 旧消息重复使用

### 防护措施
- **窃听** → AES-256-GCM 加密
- **篡改** → GCM tag 验证 + 消息签名
- **伪装** → ECDH 密钥交换 + 指纹验证
- **重放** → 时间戳 + 消息计数器（可选）

---

## 3. 加密协议设计

### 3.1 密钥交换：ECDH (NIST P-256)

**选择理由**:
- 安全性：128 位安全强度（足够）
- 兼容性：Python `cryptography` 库内置支持
- 标准化：NIST 标准，广泛审计

**流程**:
```
Client                                         Server
  |                                              |
  |  1. Client 生成临时 ECDH 密钥对 ( ephemeral ) |
  |  2. 发送 client_public_key (65 bytes)       |
  |  3. 接收 server_public_key                   |
  |  4. 计算 shared_secret = ECDH(client_priv, server_pub) |
  |                                              |
  |                                              | 1. 生成 ECDH 密钥对
  |                                              | 2. 发送 server_public_key
  |                                              | 3. 接收 client_public_key
  |                                              | 4. 计算 shared_secret = ECDH(server_priv, client_pub)
```

**Shared Secret 派生**:
```python
shared_secret = ecdh.exchange(peer_public_key)
# 使用 HKDF 派生加密密钥（32 bytes for AES-256）
encryption_key = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=None,
    info=b"clawmesh-v1-encryption"
).derive(shared_secret)
```

### 3.2 消息加密：AES-GCM

**参数**:
- 密钥长度：256 位（32 字节）
- IV/nonce：12 字节（96 位），随机生成，每个消息唯一
- tag：16 字节（128 位），认证标签

**消息格式**:
```json
{
  "meta": { ... },
  "payload": {
    "type": "text",
    "content": "Base64( IV + ciphertext + tag )",  # 加密后合并传输
    "encrypted": true,
    "nonce": "Base64(IV)",      // 可选：单独存储
    "tag": "Base64(tag)"        // 可选：单独存储
  },
  "routing": { ... }
}
```

**加密函数**:
```python
def encrypt_message(key: bytes, plaintext: str) -> dict:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    # ciphertext = ciphertext_bytes + tag_bytes (16 bytes at end)
    return {
        "content": base64.b64encode(ciphertext).decode('ascii'),
        "encrypted": True
    }
```

**解密函数**:
```python
def decrypt_message(key: bytes, encrypted_content: str) -> str:
    data = base64.b64decode(encrypted_content)
    nonce = data[:12]
    ciphertext = data[:-16]
    tag = data[-16:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    return plaintext.decode('utf-8')
```

### 3.3 身份验证与指纹

**指纹计算**:
```python
# 使用 SHA256 公钥，取前 8 字符（4 字节）
public_key_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
fingerprint = hashlib.sha256(public_key_bytes).hexdigest()[:8]
# 示例: "a1b2c3d4"
```

**人工验证流程**:
1. Client 连接 Server 后，Server 在 handshake_ack 中发送 `fingerprint`
2. Client 显示指纹给用户："首次连接到 CL-01S-SERVER-001，指纹: a1b2c3d4"
3. 用户通过带外渠道（电话、面对面）确认指纹
4. 用户输入 `yes` 确认，否则拒绝连接

**首次信任锚存储**:
```json
// config/trusted_fingerprints.json
{
  "CL-01S-SERVER-001": "a1b2c3d4",
  "CL-01S-CLIENT-B": "e5f6g7h8"
}
```

后续连接时验证 server 指纹是否匹配，如果不匹配则警告 MITM 可能。

### 3.4 防重放攻击

**措施**:
- 每个消息包含时间戳（meta.timestamp）
- 接收方检查时间窗口（±5 分钟）
- 可选：消息计数器（connection level）防止乱序重放

---

## 4. Handshake 协议扩展

### 4.1 明文 Handshake（当前）

```json
// Client → Server
{
  "type": "node.handshake",
  "node_id": "CL-01S-CLIENT-B"
}

// Server → Client
{
  "type": "node.handshake_ack",
  "node_id": "CL-01S-SERVER-001",
  "trusted": true
}
```

### 4.2 加密 Handshake（Phase 3）

**Step 1: Client 发送 handshake（包含 client 公钥）**

```json
{
  "type": "node.handshake",
  "node_id": "CL-01S-CLIENT-B",
  "public_key": "Base64( client_ephemeral_public_key )",  // 65 bytes P-256 compressed
  "signature": "Base64( ECDSA_signature )",  // 可选：签名 client 的 node_id
  "encryption_mode": "required" | "optional" | "fallback"  // 客户端偏好
}
```

**Step 2: Server 回复 handshake_ack（包含 server 公钥 + 指纹）**

```json
{
  "type": "node.handshake_ack",
  "node_id": "CL-01S-SERVER-001",
  "public_key": "Base64( server_ephemeral_public_key )",
  "fingerprint": "a1b2c3d4",
  "trusted": true,
  "encryption_mode": "required" | "optional",
  "session_id": "uuid"  // 可选：用于密钥派生
}
```

**Step 3: 双方立即切换到加密模式**

- 双方计算 shared_secret
- 派生 encryption_key
- 后续所有消息加密（即使 plain text 类型）
- 连接建立后，若 `encryption_mode` 为 `required` 而对方不支持加密，则断开

### 4.3 降级处理

**Scenario**: Client 要求加密 (`encryption_mode: "required"`)，但 Server 不支持

```json
// Server handshake_ack
{
  "type": "node.handshake_ack",
  "node_id": "...",
  "encryption_mode": "unsupported",
  "reason": "This server does not support encryption (Phase 1 only)"
}
```
→ Client 断开连接，报错 "Encryption required but not supported"

**Scenario**: 混合模式（支持加密的节点连接旧节点）

- 如果一端 `encryption_mode="fallback"`，则接受明文
- 记录警告日志（降低安全性）
- 不需要用户干预（自动降级）

---

## 5. 组件设计

### 5.1 `adapter/crypto.py`

**职责**:
- 密钥对生成（ECDH P-256）
- ECDH 协商
- AES-GCM 加密/解密
- 指纹计算
- 密钥派生（HKDF）

**接口**:

```python
class CryptoManager:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.key_pair: Optional[ec.EllipticCurvePrivateKey] = None
        self.peer_public_key: Optional[ec.EllipticCurvePublicKey] = None
        self.encryption_key: Optional[bytes] = None
        self.fingerprint: Optional[str] = None
    
    def generate_keypair(self) -> bytes:
        """生成 ECDH 密钥对，返回压缩格式公钥（65 bytes）"""
    
    def compute_shared_secret(self, peer_public_key_bytes: bytes) -> bytes:
        """与对方公钥计算共享秘密"""
    
    def derive_encryption_key(self, shared_secret: bytes) -> bytes:
        """使用 HKDF 派生 AES-256 密钥"""
    
    def encrypt_message(self, message_dict: dict) -> dict:
        """加密整个 Message 对象的 payload 部分，返回加密后的 payload dict"""
    
    def decrypt_message(self, encrypted_payload: dict) -> dict:
        """解密 payload，返回原始 dict"""
    
    def compute_fingerprint(self, public_key_bytes: bytes) -> str:
        """计算公钥指纹（8 字符）"""
    
    def verify_fingerprint(self, expected: str) -> bool:
        """验证对方指纹是否匹配"""
```

**实现依赖**:
```python
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
```

### 5.2 修改 `adapter/connection.py`

**新增配置**:
```python
@dataclass
class ConnectionConfig:
    encryption_required: bool = True          # 强制加密
    allow_fallback: bool = False             # 允许降级明文（仅警告）
    fingerprint_verification: bool = True    # 启用指纹验证
    trusted_fingerprints_file: str = "config/trusted_fingerprints.json"
```

**OutgoingConnection 集成**:
- 属性: `crypto: Optional[CryptoManager]`（连接成功后初始化）
- 发送消息前检查 `crypto`，若需要加密则调用 `encrypt_message`
- 接收消息后解密，验证完整性

### 5.3 修改 `node/server.py`

**新增**:
- `CryptoManager` 实例（按连接创建）
- `pending_connections: Dict[websocket, ClientHandshakeState]` 存储 handshake 状态
- `trusted_fingerprints: Dict[str, str]` 加载信任的指纹

**handshake 流程**:
```python
async def handle_connection(self, websocket, path):
    # 1. 接收 client handshake（明文）
    handshake = await self._receive_handshake(websocket)
    
    # 2. 检查加密偏好冲突
    if handshake.encryption_required and not self.server_supports_encryption:
        await self._send_encryption_unsupported(websocket)
        return
    
    # 3. 生成 ECDH 密钥对
    server_crypto = CryptoManager(self._get_own_node_id())
    server_crypto.generate_keypair()
    
    # 4. 计算 shared_secret
    server_crypto.compute_shared_secret(handshake.client_public_key)
    server_crypto.derive_encryption_key()
    
    # 5. 构建 handshake_ack（加密模式协商）
    ack = {
        "type": "node.handshake_ack",
        "node_id": self_node_id,
        "public_key": server_crypto.get_public_key_bytes_b64(),
        "fingerprint": server_crypto.compute_fingerprint(),
        "encryption_mode": "required" if server_crypto else "unsupported",
        "trusted": True
    }
    await websocket.send(json.dumps(ack))
    
    # 6. 将 server_crypto 绑定到后续连接状态
    peer = Peer(websocket, handshake.node_id, remote_addr, crypto=server_crypto)
    ...
```

### 5.4 修改 `node/client.py`

**连接流程**:
```python
async def connect(self):
    # 1. 生成 client ECDH 密钥对
    client_crypto = CryptoManager(self.node_id)
    client_crypto.generate_keypair()
    
    # 2. 发送 handshake（包含公钥）
    handshake = {
        "type": "node.handshake",
        "node_id": self.node_id,
        "public_key": client_crypto.get_public_key_bytes_b64(),
        "encryption_mode": "required"  # Phase 3 默认要求
    }
    await websocket.send(json.dumps(handshake))
    
    # 3. 接收 handshake_ack
    ack = json.loads(await websocket.recv())
    
    # 4. 检查 encryption_mode
    if ack["encryption_mode"] != "required":
        if self.config.encryption_required:
            raise ConnectionError("Server does not support encryption")
        else:
            logger.warning("Falling back to plaintext (server doesn't support encryption)")
    
    # 5. 计算 shared_secret
    server_pubkey_bytes = base64.b64decode(ack["public_key"])
    client_crypto.compute_shared_secret(server_pubkey_bytes)
    client_crypto.derive_encryption_key()
    
    # 6. 指纹验证（从 config/trusted_fingerprints.json 加载预期指纹）
    expected_fp = self._load_trusted_fingerprint(ack["node_id"])
    if expected_fp and ack["fingerprint"] != expected_fp:
        # 首次连接：询问用户
        if self._prompt_fingerprint_verification(ack["fingerprint"]):
            self._save_trusted_fingerprint(ack["node_id"], ack["fingerprint"])
        else:
            await websocket.close()
            return
    
    # 7. 将 client_crypto 存储到连接状态
    self.crypto = client_crypto
```

---

## 6. 迁移策略

### Phase 3 发布时
- 所有新节点默认 `encryption_required = True`
- 旧节点（Phase 1/2）可继续运行，但连接新节点会降级（警告）
- 提供配置开关：`encryption_mode: required|optional|disabled`
- 6 个月后强制要求，旧节点升级

### 配置选项（`network.yaml`）

```yaml
encryption:
  mode: "required"  # required | optional | disabled
  require_fingerprint_verification: true
  allow_fallback: false

  trusted_fingerprints:
    CL-01S-SERVER-001: "a1b2c3d4"
    # 自动更新：首次验证后写入 trusted_fingerprints.json

fingerprint_prompt:
  auto_accept_known: true  # 已信任的自动接受
  first_connection_prompt: true  # 首次询问用户
```

---

## 7. 测试计划
## 7. 测试结果（截至 2026-03-12）

### Unit Tests ✅
- ✅ CryptoManager 密钥生成（非空，可计算共享密钥）
- ✅ ncrypt_message / decrypt_message 往返测试（加密可解密）
- ✅ compute_fingerprint 一致性和长度（8 chars）
- ✅ HKDF 派生密钥可重现（相同输入→相同输出）
- ✅ Unicode 内容加密往返
- ✅ 篡改密文拒绝（InvalidTag）

**文件**: 	ests/test_crypto.py - **6/6 passed**

### Integration Tests ✅
- ✅ 完整 handshake + 加密消息交换（Client ↔ Server）
- ✅ 指纹验证流程（TrustedFingerprints store）
- ✅ 加密消息路由（客户端→服务端→另一客户端）
- ✅ 降级处理（required vs required 匹配，未测试降级场景）

**文件**: 	ests/test_phase3_integration.py - **3/3 passed**

### Manual Demo ✅
- ✅ xamples/secure_multi_node_demo.py 展示加密网络
- ✅ 快速验证脚本 	ests/quick_secure_test.py 成功运行

**验证**: Server + 2 Clients 同时连接，handshake 成功，加密消息 A→B 正常收发。

_准备开始实现。Next: 编写 `adapter/crypto.py`_
# ClawMesh Phase 3 详细设计 - 加密与安全

**版本**: 1.0  
**日期**: 2026-03-12  
**项目**: ClawMesh (OpenClaw Network)  
**Phase**: 3 - 加密与安全  
**状态**: Implementation (2026-03-12)

---

## 1. Phase 3 目标

### 核心目标
- 实现端到端加密（E2EE）防止中间人监听
- 实现身份验证和防篡改（数字签名）
- 设计密钥协商协议（ECDH）
- 支持密钥指纹人工验证流程（初始信任锚）
- 兼容现有的明文连接和渐进式迁移

### 成功标准
- [ ] 所有节点间通信默认加密（可配置明文兼容模式）
- [ ] 握手阶段完成 ECDH 密钥交换
- [ ] 消息使用 AES-GCM 加密（认证加密）
- [ ] 提供指纹验证机制，防止 MITM
- [ ] 现有 demo 可无缝升级到加密模式
- [ ] 向后兼容：明文节点仍可连接（降级警告）

---

## 2. 威胁模型与安全需求

### 威胁
1. **窃听**: 网络嗅探获取消息内容
2. **篡改**: 中间人修改消息内容
3. **伪装**: 攻击者伪装成合法节点
4. **重放**: 旧消息重复使用

### 防护措施
- **窃听** → AES-256-GCM 加密
- **篡改** → GCM tag 验证 + 消息签名
- **伪装** → ECDH 密钥交换 + 指纹验证
- **重放** → 时间戳 + 消息计数器（可选）

---

## 3. 加密协议设计

### 3.1 密钥交换：ECDH (NIST P-256)

**选择理由**:
- 安全性：128 位安全强度（足够）
- 兼容性：Python `cryptography` 库内置支持
- 标准化：NIST 标准，广泛审计

**流程**:
```
Client                                         Server
  |                                              |
  |  1. Client 生成临时 ECDH 密钥对 ( ephemeral ) |
  |  2. 发送 client_public_key (65 bytes)       |
  |  3. 接收 server_public_key                   |
  |  4. 计算 shared_secret = ECDH(client_priv, server_pub) |
  |                                              |
  |                                              | 1. 生成 ECDH 密钥对
  |                                              | 2. 发送 server_public_key
  |                                              | 3. 接收 client_public_key
  |                                              | 4. 计算 shared_secret = ECDH(server_priv, client_pub)
```

**Shared Secret 派生**:
```python
shared_secret = ecdh.exchange(peer_public_key)
# 使用 HKDF 派生加密密钥（32 bytes for AES-256）
encryption_key = HKDF(
    algorithm=hashes.SHA256(),
    length=32,
    salt=None,
    info=b"clawmesh-v1-encryption"
).derive(shared_secret)
```

### 3.2 消息加密：AES-GCM

**参数**:
- 密钥长度：256 位（32 字节）
- IV/nonce：12 字节（96 位），随机生成，每个消息唯一
- tag：16 字节（128 位），认证标签

**消息格式**:
```json
{
  "meta": { ... },
  "payload": {
    "type": "text",
    "content": "Base64( IV + ciphertext + tag )",  # 加密后合并传输
    "encrypted": true,
    "nonce": "Base64(IV)",      // 可选：单独存储
    "tag": "Base64(tag)"        // 可选：单独存储
  },
  "routing": { ... }
}
```

**加密函数**:
```python
def encrypt_message(key: bytes, plaintext: str) -> dict:
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode('utf-8'), None)
    # ciphertext = ciphertext_bytes + tag_bytes (16 bytes at end)
    return {
        "content": base64.b64encode(ciphertext).decode('ascii'),
        "encrypted": True
    }
```

**解密函数**:
```python
def decrypt_message(key: bytes, encrypted_content: str) -> str:
    data = base64.b64decode(encrypted_content)
    nonce = data[:12]
    ciphertext = data[:-16]
    tag = data[-16:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    return plaintext.decode('utf-8')
```

### 3.3 身份验证与指纹

**指纹计算**:
```python
# 使用 SHA256 公钥，取前 8 字符（4 字节）
public_key_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
fingerprint = hashlib.sha256(public_key_bytes).hexdigest()[:8]
# 示例: "a1b2c3d4"
```

**人工验证流程**:
1. Client 连接 Server 后，Server 在 handshake_ack 中发送 `fingerprint`
2. Client 显示指纹给用户："首次连接到 CL-01S-SERVER-001，指纹: a1b2c3d4"
3. 用户通过带外渠道（电话、面对面）确认指纹
4. 用户输入 `yes` 确认，否则拒绝连接

**首次信任锚存储**:
```json
// config/trusted_fingerprints.json
{
  "CL-01S-SERVER-001": "a1b2c3d4",
  "CL-01S-CLIENT-B": "e5f6g7h8"
}
```

后续连接时验证 server 指纹是否匹配，如果不匹配则警告 MITM 可能。

### 3.4 防重放攻击

**措施**:
- 每个消息包含时间戳（meta.timestamp）
- 接收方检查时间窗口（±5 分钟）
- 可选：消息计数器（connection level）防止乱序重放

---

## 4. Handshake 协议扩展

### 4.1 明文 Handshake（当前）

```json
// Client → Server
{
  "type": "node.handshake",
  "node_id": "CL-01S-CLIENT-B"
}

// Server → Client
{
  "type": "node.handshake_ack",
  "node_id": "CL-01S-SERVER-001",
  "trusted": true
}
```

### 4.2 加密 Handshake（Phase 3）

**Step 1: Client 发送 handshake（包含 client 公钥）**

```json
{
  "type": "node.handshake",
  "node_id": "CL-01S-CLIENT-B",
  "public_key": "Base64( client_ephemeral_public_key )",  // 65 bytes P-256 compressed
  "signature": "Base64( ECDSA_signature )",  // 可选：签名 client 的 node_id
  "encryption_mode": "required" | "optional" | "fallback"  // 客户端偏好
}
```

**Step 2: Server 回复 handshake_ack（包含 server 公钥 + 指纹）**

```json
{
  "type": "node.handshake_ack",
  "node_id": "CL-01S-SERVER-001",
  "public_key": "Base64( server_ephemeral_public_key )",
  "fingerprint": "a1b2c3d4",
  "trusted": true,
  "encryption_mode": "required" | "optional",
  "session_id": "uuid"  // 可选：用于密钥派生
}
```

**Step 3: 双方立即切换到加密模式**

- 双方计算 shared_secret
- 派生 encryption_key
- 后续所有消息加密（即使 plain text 类型）
- 连接建立后，若 `encryption_mode` 为 `required` 而对方不支持加密，则断开

### 4.3 降级处理

**Scenario**: Client 要求加密 (`encryption_mode: "required"`)，但 Server 不支持

```json
// Server handshake_ack
{
  "type": "node.handshake_ack",
  "node_id": "...",
  "encryption_mode": "unsupported",
  "reason": "This server does not support encryption (Phase 1 only)"
}
```
→ Client 断开连接，报错 "Encryption required but not supported"

**Scenario**: 混合模式（支持加密的节点连接旧节点）

- 如果一端 `encryption_mode="fallback"`，则接受明文
- 记录警告日志（降低安全性）
- 不需要用户干预（自动降级）

---

## 5. 组件设计

### 5.1 `adapter/crypto.py`

**职责**:
- 密钥对生成（ECDH P-256）
- ECDH 协商
- AES-GCM 加密/解密
- 指纹计算
- 密钥派生（HKDF）

**接口**:

```python
class CryptoManager:
    def __init__(self, node_id: str):
        self.node_id = node_id
        self.key_pair: Optional[ec.EllipticCurvePrivateKey] = None
        self.peer_public_key: Optional[ec.EllipticCurvePublicKey] = None
        self.encryption_key: Optional[bytes] = None
        self.fingerprint: Optional[str] = None
    
    def generate_keypair(self) -> bytes:
        """生成 ECDH 密钥对，返回压缩格式公钥（65 bytes）"""
    
    def compute_shared_secret(self, peer_public_key_bytes: bytes) -> bytes:
        """与对方公钥计算共享秘密"""
    
    def derive_encryption_key(self, shared_secret: bytes) -> bytes:
        """使用 HKDF 派生 AES-256 密钥"""
    
    def encrypt_message(self, message_dict: dict) -> dict:
        """加密整个 Message 对象的 payload 部分，返回加密后的 payload dict"""
    
    def decrypt_message(self, encrypted_payload: dict) -> dict:
        """解密 payload，返回原始 dict"""
    
    def compute_fingerprint(self, public_key_bytes: bytes) -> str:
        """计算公钥指纹（8 字符）"""
    
    def verify_fingerprint(self, expected: str) -> bool:
        """验证对方指纹是否匹配"""
```

**实现依赖**:
```python
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64
```

### 5.2 修改 `adapter/connection.py`

**新增配置**:
```python
@dataclass
class ConnectionConfig:
    encryption_required: bool = True          # 强制加密
    allow_fallback: bool = False             # 允许降级明文（仅警告）
    fingerprint_verification: bool = True    # 启用指纹验证
    trusted_fingerprints_file: str = "config/trusted_fingerprints.json"
```

**OutgoingConnection 集成**:
- 属性: `crypto: Optional[CryptoManager]`（连接成功后初始化）
- 发送消息前检查 `crypto`，若需要加密则调用 `encrypt_message`
- 接收消息后解密，验证完整性

### 5.3 修改 `node/server.py`

**新增**:
- `CryptoManager` 实例（按连接创建）
- `pending_connections: Dict[websocket, ClientHandshakeState]` 存储 handshake 状态
- `trusted_fingerprints: Dict[str, str]` 加载信任的指纹

**handshake 流程**:
```python
async def handle_connection(self, websocket, path):
    # 1. 接收 client handshake（明文）
    handshake = await self._receive_handshake(websocket)
    
    # 2. 检查加密偏好冲突
    if handshake.encryption_required and not self.server_supports_encryption:
        await self._send_encryption_unsupported(websocket)
        return
    
    # 3. 生成 ECDH 密钥对
    server_crypto = CryptoManager(self._get_own_node_id())
    server_crypto.generate_keypair()
    
    # 4. 计算 shared_secret
    server_crypto.compute_shared_secret(handshake.client_public_key)
    server_crypto.derive_encryption_key()
    
    # 5. 构建 handshake_ack（加密模式协商）
    ack = {
        "type": "node.handshake_ack",
        "node_id": self_node_id,
        "public_key": server_crypto.get_public_key_bytes_b64(),
        "fingerprint": server_crypto.compute_fingerprint(),
        "encryption_mode": "required" if server_crypto else "unsupported",
        "trusted": True
    }
    await websocket.send(json.dumps(ack))
    
    # 6. 将 server_crypto 绑定到后续连接状态
    peer = Peer(websocket, handshake.node_id, remote_addr, crypto=server_crypto)
    ...
```

### 5.4 修改 `node/client.py`

**连接流程**:
```python
async def connect(self):
    # 1. 生成 client ECDH 密钥对
    client_crypto = CryptoManager(self.node_id)
    client_crypto.generate_keypair()
    
    # 2. 发送 handshake（包含公钥）
    handshake = {
        "type": "node.handshake",
        "node_id": self.node_id,
        "public_key": client_crypto.get_public_key_bytes_b64(),
        "encryption_mode": "required"  # Phase 3 默认要求
    }
    await websocket.send(json.dumps(handshake))
    
    # 3. 接收 handshake_ack
    ack = json.loads(await websocket.recv())
    
    # 4. 检查 encryption_mode
    if ack["encryption_mode"] != "required":
        if self.config.encryption_required:
            raise ConnectionError("Server does not support encryption")
        else:
            logger.warning("Falling back to plaintext (server doesn't support encryption)")
    
    # 5. 计算 shared_secret
    server_pubkey_bytes = base64.b64decode(ack["public_key"])
    client_crypto.compute_shared_secret(server_pubkey_bytes)
    client_crypto.derive_encryption_key()
    
    # 6. 指纹验证（从 config/trusted_fingerprints.json 加载预期指纹）
    expected_fp = self._load_trusted_fingerprint(ack["node_id"])
    if expected_fp and ack["fingerprint"] != expected_fp:
        # 首次连接：询问用户
        if self._prompt_fingerprint_verification(ack["fingerprint"]):
            self._save_trusted_fingerprint(ack["node_id"], ack["fingerprint"])
        else:
            await websocket.close()
            return
    
    # 7. 将 client_crypto 存储到连接状态
    self.crypto = client_crypto
```

---

## 6. 迁移策略

### Phase 3 发布时
- 所有新节点默认 `encryption_required = True`
- 旧节点（Phase 1/2）可继续运行，但连接新节点会降级（警告）
- 提供配置开关：`encryption_mode: required|optional|disabled`
- 6 个月后强制要求，旧节点升级

### 配置选项（`network.yaml`）

```yaml
encryption:
  mode: "required"  # required | optional | disabled
  require_fingerprint_verification: true
  allow_fallback: false

  trusted_fingerprints:
    CL-01S-SERVER-001: "a1b2c3d4"
    # 自动更新：首次验证后写入 trusted_fingerprints.json

fingerprint_prompt:
  auto_accept_known: true  # 已信任的自动接受
  first_connection_prompt: true  # 首次询问用户
```

---

## 7. 测试计划

### Unit Tests
- [ ] `CryptoManager` 密钥生成（非空，可计算共享密钥）
- [ ] `encrypt_message` / `decrypt_message` 往返测试（加密可解密）
- [ ] `compute_fingerprint` 一致性和长度（8 chars）
- [ ] HKDF 派生密钥可重现（相同输入→相同输出）

### Integration Tests
- [ ] 完整 handshake + 加密消息交换（Client ↔ Server）
- [ ] 指纹验证流程（正确/错误/首次）
- [ ] 降级处理（required vs unsupported）
- [ ] 加密连接期间广播消息（多节点）

### Manual Demo
- [ ] `examples/secure_multi_node_demo.py` 展示加密网络
- [ ] 指纹显示和确认流程

---

## 8. 实现任务分解

| ID | 任务 | 状态 | 预计工时 |
|----|------|------|----------|
| CM-21 | 创建 `adapter/crypto.py` 基础框架 | 📋 To Do | 2h |
| CM-22 | 实现 ECDH 密钥生成与交换 | 📋 To Do | 2h |
| CM-23 | 实现 AES-GCM 加密/解密 | 📋 To Do | 1h |
| CM-24 | 指纹计算与验证 | 📋 To Do | 1h |
| CM-25 | 修改 `node/server.py` handshake | 📋 To Do | 3h |
| CM-26 | 修改 `node/client.py` handshake | 📋 To Do | 3h |
| CM-27 | 修改 `adapter/connection.py` 集成 crypto | 📋 To Do | 2h |
| CM-28 | 配置 trusted_fingerprints.json | 📋 To Do | 1h |
| CM-29 | Unit tests: `tests/test_crypto.py` | 📋 To Do | 2h |
| CM-30 | Integration tests: `tests/test_phase3_integration.py` | 📋 To Do | 2h |
| CM-31 | 更新 `design.md` 和 `README.md` | 📋 To Do | 1h |
| CM-32 | 文档：加密配置与指纹验证用户指南 | 📋 To Do | 2h |

**总计**: ~22 小时（2.5 天）

---

## 9. 注意事项

### Windows 兼容性
- 使用 `os.urandom(12)` 生成 nonce，确保跨平台
- 日志避免 emoji
- 文件路径使用 `Path` 对象或 `r"..."` 原始字符串

### 性能
- AES-GCM 软件实现开销约 0.1ms/消息（现代 CPU）
- ECDH 密钥交换只在 handshake，可接受
- 避免每次加密重新派生密钥

### 安全审计
- **密钥存储**: 内存中不持久化私钥（每次重启生成 ephemeral）
- **随机数**: 使用操作系统 CSPRNG
- **IV**: 每次加密随机生成，不可重复
- **错误处理**: 解密失败立即断开（拒绝无效密文）

---

_准备开始实现。Next: 编写 `adapter/crypto.py`_
