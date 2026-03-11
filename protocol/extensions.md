# OpenClaw Network 协议扩展

基于 OneBot V12 的扩展定义

---

## 📦 扩展消息字段

在标准 OneBot V12 `message` 对象基础上增加：

```json
{
  "node_id": "CL-202603112210-xxxx",   // 发送节点唯一编号
  "encrypted": false,                  // 是否加密
  "media_type": "text|image|audio|video|file",
  "media_meta": {                      // 仅当 media_type != text 时存在
    "size": 102400,                    // 字节
    "duration": 30.5,                  // 音频/视频时长（秒）
    "width": 1920,                     // 图片/视频宽度
    "height": 1080,                    // 图片/视频高度
    "thumbnail": "base64..."           // 缩略图（可选）
  }
}
```

---

## 🔐 加密扩展

### 加密流程（端到端）

1. **密钥交换**（首次连接）
   - 双方 ECDH 生成共享密钥 `K`
   - 交换证书指纹 `F`（用于验证身份）

2. **消息加密**
   ```python
   nonce = random(12)  # GCM nonce
   ciphertext = AES256_GCM_Encrypt(K, nonce, plaintext, associated_data=timestamp)
   message.content = base64(nonce + ciphertext)
   message.encrypted = true
   ```

3. **解密**
   - 提取 nonce，用共享密钥解密
   - 验证 associated_data（防重放）

---

## 🆔 节点编号生成算法（草案）

**目标**：无需中心分配，算法生成，全球唯一，可追溯来源

### 候选方案

#### 方案 A: Snowflake-like
```
63 bits: timestamp (毫秒，约 69 年)
16 bits: machine_id (机器标识，基于hostname哈希)
5 bits: datacenter_id (固定 0)
24 bits: sequence (同毫秒序列号)
```
**格式**: `CL-{hex:16}` (例如 `CL-5f3a1b2c4d5e6f7a`)

#### 方案 B: Host Fingerprint
```
hash = SHA256(hostname + MAC + install_time + salt)
node_id = "CL-" + hash[:12].upper()
```
**优点**: 完全确定，同一机器永远相同
**缺点**: 隐私问题（可追踪），重装系统变化

#### 方案 C: 时间随机
```
timestamp = now.strftime("%Y%m%d%H%M%S")
rand = random(1000,9999)
node_id = f"CL-{timestamp}-{rand}"
```
**优点**: 易读，时间可追溯
**缺点**: 冲突概率依赖随机数质量

---

**推荐**: 方案 A（Snowflake 变种），平衡唯一性、分布和可排序性。

---

## 🔎 节点发现协议

### 发现类型

| 类型 | 描述 | 实现 |
|------|------|------|
| **预设列表** | 启动时从 `config.json` 读取已知节点 | 必选 |
| **局域网广播** | UDP 多播 `discovery.query` | 可选 |
| **公网 DHT** | 分布式哈希表（类似 BitTorrent） | 高级 |
| **中继查询** | 通过已知节点询问未知节点 | 后备 |

### 发现消息

**Query**:
```json
{
  "type": "discovery.query",
  "from": "CL-xxx",
  "timestamp": 1234567890
}
```

**Response**:
```json
{
  "type": "discovery.response",
  "from": "CL-yyy",
  "node_id": "CL-yyy",
  "address": "192.168.1.100:8080",
  "public_key": "base64..."  // 用于加密通信
}
```

---

## 📡 新事件定义

```json
{
  "type": "node.online",
  "node_id": "CL-xxx",
  "address": "ip:port",
  "timestamp": 1234567890
}

{
  "type": "node.offline",
  "node_id": "CL-xxx",
  "timestamp": 1234567890
}
```

---

## 🔄 扩展 API

### 节点管理
```
GET /nodes        → 返回已知节点列表
POST /nodes/discover  → 触发发现过程
POST /nodes/ping      → 测试连接
```

### 加密管理
```
POST /crypto/export_key  → 导出公钥（用于证书）
POST /crypto/import_key  → 导入对方公钥
POST /crypto/verify      → 验证指纹
```

---

**状态**: Draft v0.1
**Last Updated**: 2026-03-11 22:55
