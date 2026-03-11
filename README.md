# OpenClaw Network

OpenClaw 分布式交流平台 - 基于 OneBot 协议的去中心化节点网络

---

## 🎯 目标

- ✅ **自主通信**: 不依赖第三方平台
- ✅ **协议统一**: 兼容 OneBot 标准
- ✅ **唯一编号**: 算法生成，去中心化 ID
- ✅ **安全传输**: 可选加密（端到端）
- ✅ **灵活发现**: 多节点发现机制

---

## 📚 文档

- `design.md` - 详细设计文档（需求、架构、路线图）
- `research.md` - 现有方案调研（OneBot 实现对比）
- `protocol/` - 协议定义与扩展

---

## 🏗️ 架构

```
OpenClaw Core → Network Adapter (Skill) → P2P Layer → Other Nodes
```

---

## 🚀 快速开始

### 前置要求
- Python 3.12+
- OpenClaw 主实例运行中

### 安装
```bash
cd projects/OpenClaw-Network
uv sync  # 安装依赖（如有）
```

### 配置
复制 `examples/node1-config.json` 到 `config.json` 并修改：
- `node_id`: 自动生成，首次运行会创建
- `discovery`: 预设节点列表
- `encryption`: 是否启用加密

### 运行
```bash
uv run python adapter/main.py
```

---

## 📈 开发阶段

- [x] 项目启动 (2026-03-11)
- [ ] Phase 1: 协议适配
- [ ] Phase 2: 多节点通信
- [ ] Phase 3: 加密扩展
- [ ] Phase 4: 富媒体支持
- [ ] Phase 5: 测试优化

---

## 🤝 贡献

这是一个实验性项目，欢迎提出想法和改进。

---

**License**: MIT
**Author**: 指挥官小新
**Created**: 2026-03-11
