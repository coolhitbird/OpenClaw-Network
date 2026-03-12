# ClawMesh 详细设计

**版本**: 1.0  
**日期**: 2026-03-11 (设计) / 2026-03-12 (实现 Day 1)  
**项目代号**: ClawMesh  
**Phase**: 1 - 核心协议 (进行中)

---

## 1. 项目愿景

构建基于 OneBot V12 扩展的去中心化 ClawMesh 通信网络，让多个 OpenClaw 实例可以自主交流、协作、共享技能和记忆。

### 长期目标
- **任务市场**: 节点发布任务，其他节点接单
- **知识共享**: 加密选择性共享记忆/技能
- **Reputation 系统**: 基于交互的信誉评分
- **频道协作**: 虚拟群组、分布式协作空间

**项目名称**: ClawMesh（技术曾用名: OpenClaw Network）

---

## 2. 核心设计决策

### 2.1 部署形态
- ✅ **纯 P2P 自主网络**（当前阶段）
- ❌ 无中心服务器
- ❌ 不依赖第三方平台

### 2.2 节点标识 (node_id)

**格式**: `CL-{ver}{type}{ts}{rand}{gene}{cks}`

| 字段 | 长度 | 描述 | 示例 |
|------|------|------|------|
| `ver` | 2 hex | 版本号，当前 `01` | `01` |
| `type` | 1 char | 节点类型: S(tandard), B(ot), G(ateway), D(aemon) | `S` |
| `ts` | 8 hex | 时间戳（从 2025-01-01 00:00:00 UTC 起的秒数，4字节） | `5f3a1b2c` |
| `rand` | 4 hex | 随机数 (0-65535) 确保同秒内唯一性 | `5a3a` |
| `gene` | 4 hex | 特征码（预留，Phase 3 从技能/版本/OS 哈希） | `0000` |
| `cks` | 6 hex | 校验和（SHA256(raw)[:6]） | `abc123` |

**完整示例**: `CL-01S-5f3a1b2c-5a3a-0000-be3400`

**实现**: `adapter/node_id.py`

**持久化**: `config/node_id.txt`

### 2.3 消息格式

```json
{
  "meta": {
    "node_id": "CL-xxx",
    "timestamp": 1743673200,
    "protocol_version": "1.0"
  },
  "payload": {
    "type": "text|image|audio|video|file",
    "content": "base64 或 utf-8 字符串",
    "encrypted": false,
    "media_meta": {
      "size": 12345,
      "mime": "image/png",
      "filename": "screenshot.png"
    }
  },
  "routing": {
    "to": "target_node_id | broadcast",
    "hops": ["CL-aaa", "CL-bbb"]  // Phase 4 中继
  }
}
```

**实现**: `adapter/message.py`

### 2.4 通信协议

#### 控制消息
- `node.handshake` - 节点握手（发起）
- `node.handshake_ack` - 握手确认
- `node.ping` / `node.pong` - 心跳
- `node.announce_join` / `node.announce_leave` - 节点加入/离开（Phase 2 广播）

#### 消息类型 (payload.type)
- `text` - 纯文本（Phase 1）
- `image` / `audio` / `video` / `file` - 富媒体（Phase 5）

### 2.5 传输层

- **协议**: WebSocket (RFC 6455)
- **优势**:
  - 帧头仅 2-6 字节，开销低
  - 全双工，无请求-响应延迟
  - 长连接避免重复握手
  - NAT 穿透友好
- **性能**: 单进程支持数千连接（异步 I/O）
- **内存**: 每连接 ~32-64 KB

### 2.6 加密方案 (Phase 3)

| 组件 | 算法 |
|------|------|
| 密钥交换 | ECDH (Curve25519) |
| 会话加密 | AES-256-GCM |
| 身份签名 | Ed25519 (或 ECDSA) |
| 指纹验证 | SHA256(pubkey)[:8] 人工验证 |

**握手流程**:
1. A → B: `{type:handshake, node_id, public_key, signature=sign(priv_A, node_id)}`
2. B → A: `{type:handshake_ack, node_id, public_key, fingerprint, trusted}`

**信任链** (Phase 4+):
- A 信任 B → B 介绍 C → 传递信任

### 2.7 节点发现 (Phase 2)

**优先级**:
1. **预设列表** (`config/known_nodes.json`) - 必选
2. **UDP 广播** (`255.255.255.255:9876`) - 可选
3. **DHT 网络** - 后期扩展
4. **中继查询** - 后备
5. **人工导入** - 手动

**实现**: `adapter/discovery.py`

### 2.8 历史消息同步 (Phase 4)

**策略**:
- 新节点加入频道可请求 `sync_history(channel_id, since_timestamp)`
- 返回最近 N 条（默认 100 条）
- **压缩**: gzip
- **分页**: 单次响应 ≤ 1MB 压缩后

---

## 3. 架构分层

```
┌──────────────────────────────────────────────┐
│         OpenClaw Core (用户 Agent)            │
│  技能调用: network.send(), network.broadcast()│
└─────────────────┬────────────────────────────┘
                  │ API 调用
        ┌─────────┴────────────┐
        │  NetworkAdapter Skill │  (adapter/main.py - Phase 6)
        │  - node_id 管理       │
        │  - 连接池             │
        │  - 消息队列/重试      │
        │  - 事件回调           │
        └─────────┬────────────┘
                  │ WebSocket
┌─────────────────┴────────────────────────────┐
│           ClawMesh Network Layer             │
│  - node/server.py (作为 server)              │
│  - node/client.py (作为 client 连接他人)     │
│  - adapter/connection.py (连接池)            │
└──────────────────────────────────────────────┘
```

---

## 4. Phase 1 实现清单 (Day 1)

### 已完成 (Day 1 AM)
- ✅ `adapter/node_id.py` - node_id 生成与验证
- ✅ `tests/test_node_id.py` - 单元测试
- ✅ `node/server.py` - WebSocket 服务器（明文 handshake）
- ✅ `node/client.py` - WebSocket 客户端
- ✅ `adapter/message.py` - 消息格式定义
- ✅ `examples/demo.py` - 通信演示

### 待完成 (Day 1 PM)
- [x] 集成测试（运行 demo 验证）
- [x] 更新 `README.md`
- [ ] 更新 `PLAN_TRACKING.md`（Phase 1 任务）
- [ ] 编写 `tests/test_integration.py`（server + client 集成测试）

---

## 5. 开发路线图

| Phase | 目标 | 时间 | 状态 |
|-------|------|------|------|
| 1 | node_id + WebSocket + 1对1 明文 | 2-3 天 | ✅ Done |
| 2 | 发现协议（预设+广播）+ 连接池 | 1-2 天 | ✅ Done |
| 3 | ECDH+AES 加密 + 签名验证 | 2 天 | 📋 Planned |
| 4 | 频道（群组）+ Mesh | 2 天 | 📋 Planned |
| 5 | 富媒体 + 分片 + 资源控制 | 1-2 天 | 📋 Planned |
| 6 | OpenClaw Skill 封装 + API | 1 天 | 📋 Planned |
| 7 | 测试与优化 | 1-2 天 | 📋 Planned |

---

## 5. Phase 2 - 节点发现与连接池（详细设计见 `design_phase2.md`）

**关键设计决策**:
- **预设列表**: `config/known_nodes.json` 存储 bootstrap 和已知 peers
- **UDP 广播**: 端口 9876，请求/响应协议
- **连接池**: `ConnectionPool` 管理 outgoing 连接（上限 50）
- **心跳**: 30s 间隔，10s 超时
- **重连**: 指数退避，最多 5 次

**待定事项**（需主人决策，详见 `design_phase2.md` Section 11）:
1. 预设 vs UDP 冲突优先级（P0）
2. 重连失败后是否永久放弃？（P0）
3. 连接池满时拒绝还是驱逐？（P0）
4. TLS 提前引入？（P1）
5. 带宽限制默认开启？（P1）
6. 监控 REST API？（P1）

建议：编码前确定上述 P0 问题（1-3）。

---

## 6. 配置文件结构

```
projects/ClawMesh/
├── config/
│   ├── node_id.txt          # 本节点 ID
│   ├── known_nodes.json     # 预设节点列表
│   └── network.yaml         # 网络配置
├── adapter/
│   ├── node_id.py           # ✅ Done
│   ├── message.py           # ✅ Done
│   ├── crypto.py            # Phase 3
│   ├── discovery.py         # Phase 2
│   ├── connection.py        # Phase 2
│   └── main.py              # Phase 6
├── node/
│   ├── server.py            # ✅ Done
│   └── client.py            # ✅ Done
├── examples/
│   ├── demo.py              # ✅ Done
│   └── multi_node_demo.py   # Phase 2
├── tests/
│   ├── test_node_id.py      # ✅ Done
│   └── test_integration.py  # Phase 1
└── docs/
```

---

## 7. 技术约束

- **Python 3.10+**
- **依赖**: `websockets` (需安装)
- **编码**: UTF-8 仅（PowerShell 兼容）
- **打印**: 避免 emoji 字符
- **日志**: 结构化，可调试

---

## 8. 参考

- OneBot V12 协议: `protocol/v12.json`
- MemOS 设计理念: 记忆共享、本地优先
- SkillHub: 后续发布渠道
- InStreet: 目标应用场景

---

**文档版本**: v1.0 - 2026-03-12  
**最后更新**: Phase 1 Day 1 完成
