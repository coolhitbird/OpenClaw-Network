# ClawMesh Phase 2 详细设计

**版本**: 1.0  
**日期**: 2026-03-12  
**项目**: ClawMesh (OpenClaw Network)  
**Phase**: 2 - 节点发现与连接池  
**状态**: Draft (待细化)

---

## 1. Phase 2 目标

### 核心目标
- 实现节点自动发现机制（预设列表 + UDP 广播）
- 实现连接池管理（outgoing 连接）
- 实现自动重连与连接状态监控
- 支持多节点网络（3+ 节点）

### 成功标准
- [ ] 新节点可通过 `known_nodes.json` 自动发现 bootstrap 节点
- [ ] 同一局域网内节点可通过 UDP 广播相互发现
- [ ] 连接池管理至少 10 个 outgoing 连接
- [ ] 连接断开后自动重连（退避策略）
- [ ] `examples/multi_node_demo.py` 成功展示 3+ 节点网络

---

## 2. 架构概览

### 2.1 发现协议

```
┌─────────────┐
│  本节点 A   │
└──────┬──────┘
       │
       ├── 预设列表 ──→ 已知节点 (bootstrap, peers)
       │
       └── UDP 广播 ──→ 局域网节点 (255.255.255.255:9876)
                   │
                   ↓
           响应: {node_id, ws_address}
```

### 2.2 连接池

```
┌────────────────────────────────────────┐
│          ClawMesh ConnectionPool       │
├────────────────────────────────────────┤
│  connections: Dict[node_id, Outgoing]  │
│  active: Set[node_id]                  │
│  failed: Dict[node_id, retry_count]    │
│  event_queue: asyncio.Queue            │
└────────────────────────────────────────┘
         │
         ├── get_connection(node_id) → 获取/建立连接
         ├── ensure_connected(node_id) → 保证连接活跃
         ├── broadcast(msg) → 广播到所有连接
         └── close_all() → 优雅关闭
```

---

## 3. 节点发现详细设计

### 3.1 预设列表（静态发现）

**配置文件**: `config/known_nodes.json`

```json
{
  "version": "1.0",
  "bootstrap": [
    {
      "node_id": "CL-01S-5f3a1b2c-5a3a-0000-be3400",
      "address": "ws://123.45.67.89:8765",
      "description": "Bootstrap node 1",
      "tags": ["bootstrap", " stable"]
    }
  ],
  "known_peers": [
    {
      "node_id": "CL-01B-5f3a1b2c-5a3a-0000-123456",
      "address": "ws://localhost:8766",
      "description": "Local test node",
      "tags": ["test"]
    }
  ]
}
```

**🎯 待细化**:
- [ ] 是否支持多个 bootstrap 节点？如果第一个不可用，是否轮询尝试？
- [ ] 配置文件热重载？节点列表变化时是否动态更新？
- [ ] 如何验证 `node_id` 与 `address` 的匹配性？（防止 DNS 劫持）
- [ ] 是否支持 CIDR 或 IP 范围白名单？

### 3.2 UDP 广播（动态发现）

**协议**:

```
广播请求 (port 9876, broadcast):
  {
    "type": "discovery.request",
    "node_id": "CL-01S-...",
    "timestamp": 1234567890
  }

单播响应 (from responder):
  {
    "type": "discovery.response",
    "node_id": "CL-01S-...",
    "ws_address": "ws://192.168.1.100:8765",
    "public_key": "base64...",  // Phase 3
    "timestamp": 1234567890
  }
```

**🎯 待细化**:
- [ ] UDP 广播频率？（例如：每 30 秒一次，或仅启动时）
- [ ] 响应缓存时间？多久没回应就认为节点离线？
- [ ] 如何防止广播洪水攻击？（速率限制）
- [ ] Windows 防火墙是否允许 UDP 9876？可能需要提示用户配置
- [ ] 是否支持 IPv6 广播？
- [ ] 广播超时时间？（等待响应多久）

### 3.2 UDP 广播协议（完整实现）

**协议消息格式**:

```json
// Request（广播到 255.255.255.255:9876）
{
  "type": "discovery.request",
  "node_id": "CL-01S-5f3a1b2c-5a3a-0000-be3400",
  "nonce": "a1b2c3d4e5f6...",  // 32 hex chars (16 bytes)，防重放
  "timestamp": 1743673200
}

// Response（单播回请求者）
{
  "type": "discovery.response",
  "node_id": "CL-01S-5f3a1b2c-5a3a-0000-be3400",
  "ws_address": "ws://192.168.1.100:8765",
  "nonce": "a1b2c3d4e5f6...",  // 回声相同 nonce
  "timestamp": 1743673200
}
```

**安全机制**:
- **nonce 防重放**: 每个 request 生成 16 字节随机 nonce，缓存在 `_pending_nonces`（ OrderedDict，容量 100，TTL 30s）
- 收到 response 时验证 nonce 存在且未使用，使用后立即删除
- 重复 nonce 或未知 nonce 被拒绝并记录 warning

**实现类**:
- `UDPBroadcaster`:
  - `start()` - 绑定 `0.0.0.0:9876`，启动 `UDPProtocol`
  - `broadcast_request()` - 每 30 秒发送一次 request（可配置）
  - `_send_request()` - 生成 nonce，发送 JSON
  - `handle_response()` - 验证 nonce，添加节点到 `_discovered`
  - `_cleanup_nonces()` - 定期清理过期 nonce（TTL 30s，LRU 容量 100）
  - `get_discovered(ttl=60.0)` - 获取发现节点，自动清理过期（last_seen > ttl）

**错误处理**:
- `OSError`（端口占用、权限不足）→ 记录 error，提示用户检查防火墙或更换端口
- `json.JSONDecodeError` → 记录 warning，忽略
- 其他异常 → 记录 error，继续运行

**配置参数**（`config/network.yaml`）:

```yaml
discovery:
  enabled: true
  udp_port: 9876
  broadcast_interval: 30s
  conflict_resolution: "preset_priority"
  # 安全参数
  nonce_size: 16          # nonce 字节数（16 bytes = 32 hex chars）
  nonce_cache_size: 100   # pending nonce 缓存大小
  nonce_ttl: 30s          # nonce 有效时间
  discovery_ttl: 60s      # 发现节点过期时间（last_seen 超过则移除）
```

**注意事项**:
- Windows 防火墙可能需要允许 UDP 9876 端口（入站/出站广播）
- `255.255.255.255` 广播地址可能被路由器阻止，可考虑 `192.168.1.255` 替代（未来可选）
- 减少广播频率以避免网络洪水（默认 30s 合理）

---

### 3.3 NodeRegistry 合并策略（更新）

```python
class NodeRegistry:
    def __init__(self, loader: KnownNodesLoader, discovery: UDPBroadcaster, config: DiscoveryConfig):
        self.loader = loader
        self.discovery = discovery
        self.config = config
        self._conflict_log: List[Dict] = []

    def get_all_nodes(self, include_expired: bool = False) -> List[NodeInfo]:
        """
        获取全部已知节点
        
        Args:
            include_expired: 是否包含过期的发现节点（默认过滤）
        """
        nodes = []
        preset_ids = set(self.loader.presets.keys())
        
        # 1. 添加预设节点（高优先级）
        for node in self.loader.list_presets():
            nodes.append(node)
        
        # 2. 获取发现节点（自动清理过期）
        ttl = None if include_expired else self.config.discovery_ttl
        discovered = self.discovery.get_discovered(ttl=ttl)
        
        # 3. 合并：预设优先，UDP 补充
        for node_id, node in discovered.items():
            if node_id in preset_ids:
                # 冲突：记录警告，跳过 UDP 副本
                preset_node = self.loader.presets[node_id]
                if preset_node.address != node.address:
                    self._log_conflict(node_id, preset_node.address, node.address)
                continue
            nodes.append(node)
        
        return nodes
```

**行为**:
- 预设节点永远优先（即使 UDP 提供不同地址）
- UDP 发现的节点自动添加，但 `last_seen` 超过 `discovery_ttl` 被过滤
- 冲突日志供管理员审查（可导出到 `logs/discovery_conflicts.json`）

---

### 4. 连接池设计（Phase 2 Day 3-4 待实现）

[... 原有内容保持不变 ...]

**🎯 待细化**:
- [ ] 连接 bootstrap 失败后，是否重试？（间隔：指数退避 5s, 10s, 30s, 60s...）
- [ ] "孤岛模式"下，是否允许手动添加 peer？（Phase 4 API）
- [ ] 如何合并不同来源的 peer 列表？优先级：预设 > UDP > 已连接节点

---

## 4. 连接池设计

### 4.1 OutgoingConnection 类

```python
@dataclass
class OutgoingConnection:
    node_id: str
    address: str
    websocket: Optional[websockets.WebSocketClientProtocol] = None
    last_seen: float = 0  # 上次收到消息时间
    retry_count: int = 0
    state: str = "disconnected"  # disconnected, connecting, connected, failed
    task: Optional[asyncio.Task] = None

    async def connect(self) -> bool:
        """建立 WebSocket 连接"""

    async def send(self, msg: dict) -> bool:
        """发送消息，失败时标记重试"""

    async def close(self):
        """关闭连接"""

    def should_retry(self) -> bool:
        """判断是否应该重连（基于退避策略）"""
```

**🎯 待细化**:
- [ ] `retry_count` 上限？建议 5 次后进入"永久失败"状态，需手动干预
- [ ] 退避策略：`min(60, 2 ** retry_count)` 秒，还是线性？
- [ ] `last_seen` 心跳机制：server 多久没发消息就视为离线？（建议 60s）
- [ ] 是否支持 TLS/SSL？（Phase 3 加密后需要）
- [ ] 每个连接的最大消息队列大小？（防止 OOM）

### 4.2 ConnectionPool 类（更新）

```python
class ConnectionPool:
    def __init__(self, max_size: int = 50):
        self.outgoing: Dict[str, OutgoingConnection] = {}
        self.max_size = max_size
        self.lock = asyncio.Lock()
        self.maintenance_task: Optional[asyncio.Task] = None
    
    async def get_connection(self, node_id: str) -> OutgoingConnection:
        """获取或创建连接（如果池满则处理）"""
        async with self.lock:
            if node_id in self.outgoing:
                return self.outgoing[node_id]
            
            # 检查池大小
            if len(self.outgoing) >= self.max_size:
                # 🎯 待决策：池满处理策略
                # 选项 A: 驱逐最久未使用（LRU）
                # 选项 B: 抛出 PoolFullError
                # 选项 C: 允许超过（仅警告）
                # 建议：默认 LRU 驱逐，可配置
                await self._evict_lru()
            
            # 创建新连接
            conn = OutgoingConnection(node_id, ...)
            self.outgoing[node_id] = conn
            return conn
    
    async def _evict_lru(self):
        """驱逐最久未使用的连接"""
        if not self.outgoing:
            return
        # 按 last_used 排序，移除最旧的
        oldest = min(self.outgoing.items(), key=lambda kv: kv[1].last_used)
        await self.outgoing[oldest[0]].close()
        del self.outgoing[oldest[0]]
        logger.warning(f"连接池满，驱逐最旧连接: {oldest[0]}")
```

**连接池大小现实性分析**:

| 场景 | outgoing 连接数 | 可能性 | 说明 |
|------|----------------|--------|------|
| 普通用户节点 | 5-20 | 高 | 连接到 friends/agents |
| 公开 supernode | 20-50 | 中 | 作为 hub 连接多个节点 |
| **超过 50** | >50 | 低 | 恶意扫描或极端情况 |

**结论**:
- 默认 `max_size = 50`（可配置）
- 达到 80% (40) 时记录警告
- 采用 **LRU 驱逐**而非硬拒绝（保证可用性）
- 提供配置 `connection.pool_strategy: lru|reject|overflow`

**待明确**:
- [ ] LRU 驱逐是否记录到审计日志？
- [ ] 被驱逐节点是否尝试重连？（应该会，因为还在 known_nodes 中）

### 4.3 心跳与健康检查（更新）

**双向心跳**:
- 每 30 秒发送 `node.ping`
- 10 秒内未收到 `node.pong` → 标记连接 **offline**
- 连续失败 3 次 → 关闭连接，标记节点 **offline**，触发重连逻辑

**节点状态机**:

```
online ──(ping 超时)──> offline ──(收到消息)──> online
   │                          │
   └─(主动断开)──> disconnecting ──(完成)──> offline
```

**重连策略（混合）**:

```python
class OutgoingConnection:
    async def connect_with_retry(self):
        while not self.shutdown:
            if self.state == "offline" and not self.should_retry():
                # 对方 offline，暂停重连，等待事件触发
                await self.wait_for_online_event()  # 阻塞直到收到对方消息
                continue
            
            try:
                await self.connect()
                self.state = "online"
                self.retry_count = 0
            except Exception as e:
                self.retry_count += 1
                backoff = self.compute_backoff()  # 指数退避
                logger.warning(f"连接失败，{backoff}s 后重试 (第 {self.retry_count} 次)")
                await asyncio.sleep(backoff)
    
    def should_retry(self) -> bool:
        """判断是否继续重试"""
        if self.retry_count < 5:
            return True  # 前 5 次快速重试（退避：5s, 10s, 20s, 40s, 60s）
        else:
            # 5 次后改为每小时重试一次
            last_attempt = self.last_attempt_time
            return time.time() - last_attempt > 3600
```

**状态恢复机制**:
- 当收到来自该节点的任何消息（`node.pong` 或 `message`）时，立即标记 `state = "online"` 并重置 `retry_count = 0`
- 这模拟了"对方重新 online"的检测

**🎯 待细化**:
- [ ] `wait_for_online_event` 如何实现？使用 `asyncio.Event`，收到对方消息时 `set()`
- [ ] 心跳间隔、超时是否可配置？（建议 config.yaml）
- [ ] 是否记录离线原因？（network error vs explicit close）

---

## 5. API 设计（Adapter 层）

### 5.1 NetworkAdapter 新增方法（更新）

```yaml
tools:
  - network.connect(node_id, address)         # 主动连接（异步，后台建立连接）
  - network.disconnect(node_id)               # 断开连接
  - network.send(node_id, content, type=text) # 发送（自动确保连接，如果 offline 则失败）
  - network.broadcast(content)                # 广播到所有活跃 outgoing 连接
  - network.peers() -> List[PeerInfo]         # 列出所有已知节点（包含状态）
  - network.status() -> ConnectionStatus      # 连接池统计
  - network.set_node_online(node_id)          # 手动标记节点 online（admin）
  - network.set_node_offline(node_id)         # 手动标记节点 offline
```

**决策**:
- [x] `network.send` 如果目标明确 offline，**不缓存**，立即返回失败（由上层重试逻辑处理）
- [x] `network.connect` 成功后自动加入连接池，后续 `send` 复用该连接
- [x] `network.peers()` 返回全部 known_nodes（预设 + 发现），标注 `state: online|offline|unknown`
- [x] 事件回调留到 Phase 6（Phase 2 只记录日志，不暴露 API）

**待明确**:
- [ ] 连接池满时的 `network.connect` 行为？建议：触发 LRU 驱逐后重试，如果仍满则返回 `PoolFullError`
- [ ] 是否提供 `network.wait_until_online(node_id)` 阻塞等待？（不建议，用事件订阅）

### 5.2 事件回调（建议）

```python
# events.py
class NetworkEvents:
    async def on_node_connected(self, node_id: str, address: str):
        """新节点连接成功"""

    async def on_node_disconnected(self, node_id: str, reason: str):
        """节点断开连接"""

    async def on_message_received(self, from_node_id: str, msg: Message):
        """收到消息（已在 adapter.handle_message 中处理，可扩展）"""
```

**🎯 待细化**:
- [ ] 事件是否同步处理？（应异步，避免阻塞主流程）
- [ ] 事件处理失败是否影响 core？（应 catch 异常并记录）

---

## 6. 配置与部署

### 6.1 config/network.yaml（更新）

```yaml
# ClawMesh 网络配置

discovery:
  enabled: true
  udp_port: 9876
  broadcast_interval: 30s          # 广播间隔（Phase 4 可能用到）
  conflict_resolution: "preset_priority"  # preset_priority|udp_priority|merge_latest
  bootstrap:
    - node_id: "CL-01S-..."
      address: "ws://..."
      description: "Bootstrap node"
  known_nodes: "config/known_nodes.json"

connection:
  pool:
    max_size: 50                    # 可配置，建议 10-100
    strategy: "lru"                 # lru|reject|overflow
    warn_at_percent: 80             # 达到 80% 时警告
  retry:
    initial_interval: 5s            # 首次重试等待
    backoff: "exponential"          # exponential|linear
    max_initial_retries: 5          # 前 5 次快速重试
    hourly_retries: true            # 5 次后每小时重试一次
    max_hourly_attempts: 24         # 最多 24 小时（1 天）
  heartbeat:
    interval: 30s                   # 发送 ping 间隔
    timeout: 10s                    # 等待 pong 超时
    max_missed: 3                   # 连续缺失判定 offline
  bandwidth:
    limit_kbps: 100                 # 出站带宽限制（P1 事项，默认 100KB/s）
    burst_kbps: 200                 # 突发带宽

monitor:
  enabled: true                     # P1 事项：默认开启监控
  http_port: 9090                   # REST API 端口
  metrics_interval: 30s             # 指标收集间隔

logging:
  level: "INFO"
  file: "logs/clawmesh.log"
```

**🎯 待明确**:
- [ ] 配置文件路径是否固定？建议 `config/network.yaml`，支持 `CLawMESH_CONFIG` 环境变量覆盖
- [ ] 热重载支持？监听文件修改时间，变更时重新加载（避免重启）
- [ ] 配置验证：启动时检查数值范围（`pool.max_size > 0` 等）

### 6.2 跨平台兼容性

| 平台 | UDP 广播 | 信号处理 | 备注 |
|------|----------|----------|------|
| Linux | ✅ 原生支持 | `add_signal_handler` | 无问题 |
| macOS | ✅ 原生支持 | `add_signal_handler` | 无问题 |
| Windows | ⚠️ 需防火墙允许 | 需特殊处理 | 需测试 |

**🎯 待细化**:
- [ ] Windows 防火墙是否自动添加规则？（需管理员权限）
- [ ] 是否提供 `--no-udp` 选项禁用广播？（仅预设列表）

---

## 7. 安全考虑（Phase 3 关联）

| 风险 | Phase 2 缓解 | Phase 3 强化 |
|------|--------------|--------------|
| 恶意节点广播假地址 | 无从预防（信任所有响应） | 用公钥指纹验证节点身份 |
| replay 攻击（重放旧广播） | timestamp 检查（±5 分钟） | 签名的 nonce 机制 |
| DoS 洪水 | 速率限制（每节点 1 次/分钟） | 信誉系统降权 |
| 中间人（预设列表） | 预设列表需手动验证 | ECDH 密钥交换 |

---

## 8. 性能与扩展性

### 8.1 连接数估算

| 场景 | 期望连接数 | 内存占用（估算） |
|------|------------|------------------|
| 个人使用 | 5-20 | ~5 MB |
| 小团队 | 20-50 | ~20 MB |
| 公开节点 | 50-100 | ~50 MB |

每连接开销：
- WebSocket buffers: ~8KB
- OutgoingConnection 对象: ~1KB
- 消息队列（待发送）: 按需

### 8.2 广播风暴防护

```
限制条件：
- 广播频率 ≥ 5 秒（同一节点）
- 广播目标数 > 50 时，拆分为分批发送
- 每节点发送队列深度限制 100 条（防止 OOM）
```

**🎯 待细化**:
- [ ] 是否实现队列持久化？（Phase 5）
- [ ] 高负载下是否丢弃旧消息？LIFO 还是 FIFO？
- [ ] 是否支持优先级消息？（control > chat > file）

---

## 9. 测试计划

### 9.1 单元测试

| 模块 | 测试点 |
|------|--------|
| `discovery.py` | 加载 known_nodes.json, UDP 发送/接收 |
| `connection.py` | OutgoingConnection 状态机，重连逻辑 |
| `pool.py` | ConnectionPool 并发访问，连接上限 |
| `config.py` | 配置加载与验证 |

### 9.2 集成测试

```python
# tests/test_phase2_integration.py
async def test_three_node_network():
    """3 节点网络：A(server), B(client), C(client)"""
    # B 和 C 通过发现协议连接 A
    # 验证 B→C 和 C→B 消息传递
```

### 9.3 压力测试

- [ ] 模拟 50 个节点同时连接单个 server
- [ ] 测试广播性能（10 节点 → 1 条消息 → 99% 接收率）
- [ ] 长时间运行（24h）稳定性

---

## 10. 实现顺序建议

### Day 1-2: discovery.py
1. 实现 `KnownNodesLoader` - 加载 known_nodes.json
2. 实现 `UDPBroadcaster` - 发送/接收广播
3. 编写 unit tests
4. 更新 `config/known_nodes.json` 示例

### Day 3-4: connection.py
1. 实现 `OutgoingConnection` - 单个连接管理
2. 实现 `ConnectionPool` - 池化管理
3. 实现心跳与健康检查
4. 编写 unit tests

### Day 5: multi_node_demo.py
1. 创建多节点演示（1 server + 2+ clients）
2. 演示自动发现（预设列表 + UDP）
3. 演示广播和 direct 消息

### Day 6: 集成与文档
1. 更新 `design.md`（Phase 2 章节）
2. 更新 `README.md`（配置说明）
3. 编写 Phase 2 集成测试
4. 提交并推送

---

## 11. 开放问题与决策（更新于 12:56）

### ✅ 已决策（P0 - 关键）

| # | 问题 | 决策 | 理由 |
|---|------|------|------|
| 1 | 预设 vs UDP 冲突优先级 | **预设优先，UDP 补充** | 预设为人工信任，UDP 仅作为发现补充。冲突时记录警告日志，以预设为准 |
| 2 | 重连失败后行为 | **混合策略**：前 5 次快速重试（5s/10s/20s/40s/60s），之后每小时 1 次，直到对方恢复 online | 避免网络抖动导致永久放弃，同时防止无效洪水 |
| 3 | 连接池满时处理 | **LRU 驱逐 + 软上限**：max_size=50 可配置，达到上限时驱逐最久未使用连接 | 大多数节点 outgoing <20，50 是安全上限。LRU 保证热点连接保持 |
| 4 | 连接池大小现实性分析 | 普通用户 5-20，公开 supernode 20-50，超过 50 可能性低。设置为可配置 | 提供灵活性，supernode 可调大至 100 |

### ✅ 已决策（P1 - 增强）

| # | 问题 | 决策 | 实施阶段 |
|---|------|------|----------|
| 5 | TLS 加密 | **Phase 3 再引入**（保持 Phase 2 简洁） | Phase 3 |
| 6 | 带宽限制 | **默认开启 100KB/s**（突发 200KB/s） | Phase 2（配置中已添加） |
| 7 | 监控 REST API | **默认开启**，监听 `0.0.0.0:9090`（Phase 2 末期） | Phase 2/6 边界 |

### 🟡 待明确（P2 - 后续）

| # | 问题 | 建议 | 优先级 |
|---|------|------|--------|
| 8 | OpenClaw 状态同步 | Phase 6 NetworkAdapter 提供 `set_status(online/offline)`，Phase 2 仅内部记录 | P2 |
| 9 | UDP 冲突日志 | 写入 `logs/discovery_conflicts.log`，供管理员审查 | P1（建议） |
| 10 | 强制 UDP 覆盖 | 提供 `--force-udp` 调试参数（非生产） | P2 |
| 11 | 配置热重载 | Phase 2 不实现，Phase 4+ 考虑 | P2 |
| 12 | 心跳配置灵活性 | 支持 per-node 心跳间隔（如 trusted nodes 降低频率） | P2 |
| 13 | 连接历史审计 | 记录 `ConnectionHistory` 表（node_id, last_online, total_attempts） | P1（建议） |

### 🎯 待决策（新问题）

| # | 问题 | 选项 | 默认建议 |
|---|------|------|----------|
| 14 | `network.send` 离线目标处理 | 立即失败 vs 缓存队列 | **立即失败**，由上层决定重试 |
| 15 | `network.peers()` 返回范围 | 全部 known_nodes vs 仅在线节点 | **全部**，标注状态 |
| 16 | 事件回调暴露时机 | Phase 2 内部日志 vs Phase 6 公开 API | **Phase 6**（避免 API 不稳定） |
| 17 | 连接超时设置 | 建议 5s 超时，可配置 | 5s（config） |
| 18 | NodeRegistry 冲突日志格式 | JSON 行日志 vs 简单文本 | **JSON**，便于解析 |

---

## 12. 参考资源

- **OneBot V12**: 连接管理章节
- **Node.js 库**: `libp2p` 的发现机制
- **Redis Cluster**: 节点发现与重定向
- **BitTorrent**: DHT 网络（Phase 4 参考）

---

**文档维护**: 每次设计变更更新此文件  
**最后更新**: 2026-03-12 12:00 (by 指挥官小新)
