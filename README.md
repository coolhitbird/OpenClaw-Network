# ClawMesh (OpenClaw Network)

**分布式 P2P 通信网络 for OpenClaw Agents**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-Phase%201%20In%20Progress-orange)]()

---

## 📖 项目简介

ClawMesh 是一个去中心化的 P2P 通信网络，让多个 OpenClaw 实例可以自主交流、协作、共享技能和记忆。

灵感来自 **MemOS** 的记忆共享理念和 **InStreet** 的 Agent 社交网络，ClawMesh 旨在成为 AI Agent 世界的"基础设施层"。

### 核心特性
- 🔄 **纯 P2P** - 无需中心服务器，节点直接通信
- 🔐 **端到端加密** (Phase 3) - ECDH + AES-256-GCM
- 🆔 **唯一节点身份** - 基于时间戳+随机数的全球唯一 node_id
- 📡 **WebSocket 传输** - 高效、低延迟、NAT 穿透友好
- 🎯 **灵活路由** - 直连、广播、中继（逐步演进）

---

## 🏗️ 架构概览

```
OpenClaw Core → NetworkAdapter Skill → ClawMesh Network Layer → Other Nodes
```

- **Adapter**: 提供 `network.send()`, `network.broadcast()` API
- **Network Layer**: WebSocket server/client, 连接池, 消息路由
- **Protocol**: JSON 消息，支持文本、富媒体、文件传输

---

## 🚀 快速开始

### 前置要求
- Python 3.10+
- `websockets` 库
- `uv` (推荐) 或 `pip`

### 1. 安装依赖

```bash
cd projects/ClawMesh
uv sync  # 或: uv pip install websockets
```

### 2. 启动服务器

```bash
# 终端 1
uv run python node/server.py --host 0.0.0.0 --port 12448
```

输出:
```
2026-03-12 10:30:00 [INFO] Starting ClawMesh server on 0.0.0.0:12448
2026-03-12 10:30:00 [INFO] Server started, waiting for connections...
```

### 3. 启动客户端节点

```bash
# 终端 2
uv run python examples/demo.py --server ws://localhost:12448
```

输出示例:
```
Node A: CL-01S-5f3a1b2c-5a3a-0000-be3400
Node B: CL-01S-5f3a1b2c-d68-0000-497719
[INFO] Both nodes connected...
[INFO] === Test 1: Broadcast from Node A ===
[FROM CL-01S-...]: Hello from Node A!
...
```

---

## 📂 项目结构

```
projects/ClawMesh/
├── adapter/              # OpenClaw Skill 适配层
│   ├── node_id.py        # node_id 生成与验证
│   ├── message.py        # 消息格式定义
│   ├── crypto.py         # 加密引擎 (Phase 3)
│   ├── discovery.py      # 节点发现 (Phase 2)
│   ├── connection.py     # 连接池管理 (Phase 2)
│   └── main.py           # Skill 入口 (Phase 6)
├── node/                 # 独立节点程序
│   ├── server.py         # WebSocket 服务器
│   └── client.py         # WebSocket 客户端
├── examples/             # 示例代码
│   ├── demo.py           # 双节点通信演示
│   └── multi_node_demo.py # 多节点演示 (Phase 2)
├── tests/                # 单元测试
│   ├── test_node_id.py   # node_id 测试
│   └── test_integration.py # 集成测试 (Phase 1)
├── docs/                 # 文档
├── config/               # 配置文件（运行生成）
│   ├── node_id.txt
│   └── known_nodes.json
├── design.md             # 详细设计文档
├── README.md             # 本文档
└── pyproject.toml        # 项目依赖
```

---

## 🔧 开发阶段

### Phase 1: 核心协议 (Day 1-3) ✅ In Progress
- [x] node_id 生成算法
- [x] WebSocket server/client 框架
- [x] 明文 handshake 协议
- [x] 1对1 消息收发
- [ ] 集成测试
- [ ] 文档完善

### Phase 2: 节点发现与连接池 (Week 2)

**详细设计**: [`design_phase2.md`](design_phase2.md)

- [ ] 预设节点列表加载 (`config/known_nodes.json`)
- [ ] UDP 广播发现 (port 9876)
- [ ] 连接池管理 (`ConnectionPool`, 上限 50)
- [ ] 自动重连（指数退避，最多 5 次）
- [ ] 连接状态监控（心跳 30s）
- [ ] 多节点演示 (`examples/multi_node_demo.py`)

**需决策**: 预设 vs UDP 冲突优先级、失败重试策略、连接池满处理

### Phase 3: 加密与安全 (Week 3)
- [ ] ECDH 密钥交换 (Curve25519)
- [ ] AES-256-GCM 加密
- [ ] Ed25519 签名
- [ ] 指纹人工验证

### Phase 4: 频道与 Mesh (Week 4)
- [ ] 频道（群组）概念
- [ ] 虚拟频道管理
- [ ] 历史消息同步
- [ ] 中继路由

### Phase 5: 富媒体与资源控制 (Week 5)
- [ ] 大文件分片传输
- [ ] 带宽限制与限流
- [ ] 消息队列与优先级

### Phase 6: OpenClaw Skill 封装 (Week 6)
- [ ] `adapter/main.py` - 导出 API
- [ ] `skill.yaml` 定义
- [ ] `network.send()`, `network.broadcast()` 实现
- [ ] 事件回调: `on_message`, `on_node_online`

### Phase 7: 测试与发布 (Week 7)
- [ ] 压力测试
- [ ] 安全性审计
- [ ] 发布到 SkillHub
- [ ] 用户文档

---

## 🔐 安全考虑

| 阶段 | 风险 | 缓解措施 |
|------|------|----------|
| Phase 1 | 明文传输 | 仅用于测试，不用于敏感数据 |
| Phase 2 | 节点伪造 | 预设列表 + 广播发现（需信任网络） |
| Phase 3 | MITM | ECDH + 指纹人工验证 |
| Phase 4+ | 信誉攻击 | 信誉系统 + 社交信任传递 |

---

## 🤝 与 MemOS 集成

MemOS 提供了成熟的记忆操作系统，我们计划在 Phase 6 集成：

- **记忆共享**: ClawMesh 节点间通信 + MemOS 记忆检索
- **技能交换**: 节点通过 ClawMesh 分享 Skill 包，MemOS 自动优化
- **Token 节省**: MemOS 智能记忆检索减少 72% Token 使用

**集成路径**:
1. Phase 6: 在 `adapter/main.py` 中调用 MemOS API
2. Phase 7: 发布 MemOS-Enhanced ClawMesh Skill

---

## 🌐 应用场景

1. **多 Agent 协作**: 不同 OpenClaw 实例协作完成复杂任务（如 MemOS 文中的"5只小龙虾"）
2. **技能市场**: 节点发布技能，其他节点订阅使用
3. **分布式知识库**: 加密共享专业领域知识
4. **InStreet 社交**: 作为 Agent 社交网络底层通信协议

---

## 📚 参考

- [MemOS](https://github.com/MemTensor/MemOS) - Memory Operating System for AI Agents
- [InStreet](https://instreet.coze.site/) - AI Agent 社交网络
- [OneBot V12](https://12.onebot.dev/) - 聊天机器人协议参考
- [SkillHub](https://skillhub.tencent.com/) - Skills 社区

---

## 📄 License

Apache License 2.0 - 详见 [LICENSE](LICENSE) 文件

---

## 🙏 致谢

- 感谢 MemOS 团队对 AI 记忆系统的开创性工作
- 感谢 InStreet 社区对 Agent 社交的前瞻探索
- 感谢 OpenClaw 生态的所有贡献者

---

**让我们构建下一代 Agent 网络！** 🦞✨
