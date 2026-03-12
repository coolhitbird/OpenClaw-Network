# ClawMesh 加密配置与指纹验证用户指南

**版本**: 1.0  
**日期**: 2026-03-12  
**适用**: Phase 3 - 加密与安全

---

## 1. 概述

ClawMesh 在 Phase 3 引入了端到端加密（E2EE），保护节点间通信免受窃听和篡改。本指南说明：

- 如何配置加密模式
- 如何验证节点指纹（防止 MITM 攻击）
- 常见问题与故障排除

---

## 2. 加密模式

### 2.1 配置位置

加密配置在 `config/network.yaml`（或代码中 `ConnectionConfig`）：

```yaml
encryption:
  mode: "required"           # "required" | "optional" | "disabled"
  require_fingerprint_verification: true   # 首次连接是否要求验证
  allow_fallback: false      # 允许降级到明文（仅警告）
```

### 2.2 模式说明

| 模式 | 行为 |
|------|------|
| `required` | 只连接支持加密的节点，拒绝明文连接 |
| `optional` | 优先加密，若无加密支持则降级（需 `allow_fallback=true`） |
| `disabled` | 关闭加密，仅用于测试环境 |

**默认**: `required`（生产环境建议）

---

## 3. 指纹验证流程

### 3.1 什么是指纹？

指纹是节点公钥的 SHA256 哈希（前 4 字节），用于验证对方身份，防止中间人攻击。

示例：
```
Server fingerprint: a1b2c3d4
```

### 3.2 首次连接验证

当您首次连接到一个新节点时，系统会：

1. **显示指纹**: `首次连接到 CL-01S-SERVER-001，指纹: a1b2c3d4`
2. **询问确认**: 通过带外渠道（电话、面对面）确认该指纹
3. **用户操作**:
   - 输入 `yes` 确认 → 指纹保存到 `config/trusted_fingerprints.json`
   - 输入 `no` 拒绝 → 连接断开

**注意**: 当前演示版本自动接受指纹（`auto-accept for demo`），**生产环境必须改为手动确认**。

### 3.3 后续连接验证

已信任的节点再次连接时，系统自动验证指纹是否匹配：

- ✅ **匹配**: 连接继续
- ❌ **不匹配**: 显示警告 `Fingerprint mismatch!`，可能表示 MITM 攻击或节点重装

---

## 4. 配置文件详解

### 4.1 `config/network.yaml`

```yaml
network:
  server:
    host: "0.0.0.0"
    port: 12448
  
  encryption:
    mode: "required"
    require_fingerprint_verification: true
    allow_fallback: false
  
  trusted_fingerprints_file: "config/trusted_fingerprints.json"
```

### 4.2 `config/trusted_fingerprints.json`

自动生成，格式：
```json
{
  "CL-01S-SERVER-001": "a1b2c3d4",
  "CL-01S-CLIENT-B": "e5f6g7h8"
}
```

**手动编辑**: 可以预先添加已知节点的指纹，实现无交互部署。

---

## 5. 常见问题

### Q1: 首次连接时如何获得指纹？

**答**: 通过安全渠道（例如：电话告知、面对面扫描二维码）获取服务器指纹。在 CLI 模式下，程序会显示指纹并等待确认。

### Q2: 指纹变更怎么办？

**答**: 如果节点重装或密钥轮换，指纹会变化。此时应：
1. 检查是否是合法变更
2. 更新 `trusted_fingerprints.json` 中的记录
3. 或者删除该条目，重新验证

### Q3: 如何暂时跳过验证？

**答**: 在代码中将 `require_fingerprint_verification` 设为 `false`（不推荐），或使用 `--no-verify` 参数（如果实现）。

### Q4: 生产环境如何实现交互式确认？

**答**: 在 `ClawMeshClient` 的 handshake 处理中，添加：
```python
if expected_fp and ack["fingerprint"] != expected_fp:
    logger.error("Fingerprint mismatch!")
    # 断开连接或提示用户
    await websocket.close()
    return
```
并增加 CLI/GUI 提示输入 `yes/no`。

---

## 6. 安全最佳实践

1. ✅ **强制加密**: `encryption.mode: required`
2. ✅ **启用指纹验证**: `require_fingerprint_verification: true`
3. ✅ **预分发指纹**: 在生产部署前通过安全渠道收集所有节点指纹
4. ✅ **定期轮换密钥**: 每月或每季度重新生成 node_id 和密钥对
5. ❌ **不要禁用验证**: 除非在完全受控的测试环境
6. ❌ **不要共享私钥**: 每个节点使用临时密钥（ephemeral），不持久化

---

## 7. 故障排除

| 症状 | 可能原因 | 解决方案 |
|------|----------|----------|
| `Invalid peer public key` | 公钥格式不匹配（应使用 X962 UncompressedPoint） | 确保双方使用相同的 `serialization.Encoding.X962` |
| `Fingerprint mismatch` | 节点重装或 MITM | 通过带外渠道验证新指纹 |
| 连接被拒绝 | 两端加密模式不匹配（如 client 要求 required，server 不支持） | 统一配置 `encryption.mode` |
| 解密失败 `InvalidTag` | 密钥不匹配或密文被篡改 | 重新 handshake，验证公钥来源 |

---

## 8. 迁移路径

### 从 Phase 1/2（明文）迁移到 Phase 3（加密）

1. **备份**: 导出当前的 `config/known_nodes.json`
2. **升级**: 拉取 Phase 3 代码
3. **配置**: 设置 `encryption.mode: required`
4. **验证**: 运行 `secure_multi_node_demo.py` 测试
5. **上线**: 逐个节点升级，使用指纹验证确保信任链

**注意**: 旧节点（未加密）仍可连接，只要 `encryption.mode: optional` 且 `allow_fallback: true`。

---

## 9. 参考资源

- **设计文档**: `projects/OpenClaw-Network/design_phase3.md`
- **API 文档**: `projects/OpenClaw-Network/adapter/crypto.py`
- **演示脚本**: `projects/OpenClaw-Network/examples/secure_multi_node_demo.py`
- **测试套件**: `projects/OpenClaw-Network/tests/test_phase3_*.py`

---

_Document Version: 1.0 - Last Updated: 2026-03-12_
