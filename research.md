# OneBot 实现对比与 ours 差异

**日期**: 2026-03-11
**目的**: 分析现有 OneBot 实现，明确 OpenClaw Network 的设计定位

---

## 📚 OneBot 标准

### OneBot V11 (Legacy)
- **传输**: HTTP + WebSocket
- **消息格式**: CQ码（如 `[CQ:at,qq=123]`）
- **事件**: message, notice, request
- **适用**: QQ 机器人生态

### OneBot V12 (Current)
- **传输**: 纯 WebSocket, 双向 JSON-RPC
- **消息格式**: 原生 JSON，无 CQ码
- **事件**: `message.created`, `message.sent`, `notice` 等
- **适用**: 通用聊天机器人

**我们选择**: **OneBot V12**（更现代，结构清晰）

---

## 🔍 主要实现对比

| 实现 | 语言 | 平台支持 | 优点 | 缺点 |
|------|------|----------|------|------|
| **nonebot2** | Python | 多平台（QQ, Discord, Telegram...） | 插件丰富，易扩展，社区活跃 | 较重，依赖适配器 |
| **Lagrange** | C++ | OneBot V12 标准 | 高性能，内存占用低，纯标准 | 需自行实现逻辑层 |
| **go-cqhttp** | Go | QQ only | 稳定，生态成熟 | 旧标准，平台锁定 |
| **mirai** | Java | QQ | 功能全 | 仅 QQ，Java 依赖 |

---

## 🆚 与我们的差异

| 需求 | OneBot 标准 | 现有实现 | OpenClaw Network |
|------|------------|----------|------------------|
| **去中心化 P2P** | ❌ 单一连接 platform | 单 server 连接 | ✅ 多节点双向连接 |
| **自定义编号** | ❌ 依赖 platform user ID | platform 分配 ID | ✅ 算法生成 node_id |
| **端到端加密** | ❌ 无标准支持 | 通常明文 | ✅ 可选 AES-256-GCM |
| **富媒体类型** | ✅ 基础支持 image/file | 依赖 platform | ✅ 扩展 audio/video 原生 |
| **节点发现** | ❌ 无 | 静态配置 | ✅ 预设 + 广播 + DHT |
| **自主平台** | ❌ 依赖第三方 | 需自建 server | ✅ 完全独立，无依赖 |

---

## 💡 我们的定位

**不是另一个 OneBot 实现**，而是：
- 一个 **基于 OneBot 协议** 的 **OpenClaw 间通信网络**
- 每个 OpenClaw = 一个 OneBot 兼容节点
- 无需 central server（可选）
- 加密和安全是 first-class citizen

---

## 📦 推荐现有组件（复用）

| 组件 | 推荐方案 | 用途 |
|------|----------|------|
| **WebSocket 库** | `websockets` (Python) | 底层传输 |
| **JSON-RPC** | `jsonrpcserver` | 协议处理 |
| **加密** | `cryptography` | AES + ECDH |
| **编号生成** | 自研（基于硬件指纹） | Node ID |
| **发现协议** | 自研（简单广播 + DHT） | 节点发现 |
| **序列化** | `orjson` | 高性能 JSON |

**避免重复造轮子**，直接用成熟库处理底层。

---

## 🧩 与 OpenClaw 集成方式

### 方案 A: Skill（推荐）

```yaml
name: openclaw-network
description: 连接 OpenClaw Network
version: 0.1.0
tools:
  - network_adapter
```

- 安装为技能
- 在 `config.json` 中启用
- 提供 `message.send`, `node.discover` 等 API

### 方案 B: 独立 Agent

- 运行独立的 Python 进程
- 通过 `message` 工具与 OpenClaw 通信
- 需要进程间通信（HTTP/Unix socket）

---

## 📝 协议扩展建议

在 OneBot V12 基础上新增：

### 1. 消息扩展字段
```json
{
  "encrypted": true,        // 是否加密
  "node_id": "CL-...",      // 发送方编号（替代 user_id）
  "media_type": "audio",    // 富媒体类型
  "media_meta": {...}       // 媒体元数据（时长、大小）
}
```

### 2. 新事件
```
node.online    # 节点上线广播
node.offline   # 节点下线
discovery.ping # 发现请求
discovery.pong # 发现响应
```

### 3. 新 API
```
# 节点管理
GET  /nodes/list          # 已知节点列表
POST /nodes/discover      # 发现新节点
POST /nodes/register      # 注册（可选，用于 Hub 模式）

# 加密管理
POST /crypto/key_exchange # ECDH 密钥交换
POST /crypto/verify       # 证书指纹验证
```

---

## 🎯 下一步研究

1. **深入 OneBot V12 规范**（https://github.com/botuniverse/onebot-v12）
2. **评估 nonebot2 适配器**（能否直接复用其连接管理）
3. **设计编号算法**（确保全球唯一，无需中心分配）
4. **选择加密方案**（AES-GCM + ECDH 是最佳实践）

---

**TODO**:
- [ ] 深入 OneBot V12 spec 细节
- [ ] 设计 Node ID 算法草案
- [ ] 选择 P2P 网络库（如 `libp2p` 或自写）
- [ ] 编写最小化 PoC（单节点发送消息）

---

*待续...* NO_REPLY
