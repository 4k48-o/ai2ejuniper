# JuniperAI 开发文档

## 1. 项目概述

JuniperAI 是一个 AI 对话式酒店预订智能体，通过白标 API 嵌入上游 IM 平台，让用户在聊天中完成酒店搜索、比价、预订、修改和取消的全流程。

**定位：** B2B API 服务，面向 IM 平台方提供即插即用的 AI 酒店预订能力。

## 2. 技术栈

| 组件 | 技术 | 版本 | 用途 |
|------|------|------|------|
| Web 框架 | FastAPI | 0.115+ | 异步 REST API |
| Agent 编排 | LangGraph | 0.2+ | 对话式 Agent 状态机 |
| LLM 抽象 | LangChain | - | Anthropic/OpenAI 双 provider |
| SOAP 客户端 | zeep | 4.3+ | Juniper 酒店 API 对接 |
| ORM | SQLAlchemy | 2.0+ | 异步数据库操作 |
| 数据库驱动 | asyncpg | - | PostgreSQL 异步驱动 |
| 数据库迁移 | Alembic | - | Schema 版本管理 |
| 数据库 | PostgreSQL | 18 | 数据持久化 |
| 容器 | Docker + docker-compose | - | 开发和部署环境 |
| 运行时 | Python | 3.11+ | 运行环境 |

## 3. 项目结构

```
JuniperAI/
├── juniper_ai/                    # 主包
│   └── app/
│       ├── main.py                # FastAPI 应用入口
│       ├── config.py              # 配置管理 (pydantic-settings)
│       ├── metrics.py             # Prometheus 指标采集
│       ├── agent/                 # LangGraph Agent
│       │   ├── graph.py           # Agent 工作流定义
│       │   ├── prompts/
│       │   │   └── system.py      # 动态系统提示词构建
│       │   └── tools/             # 7 个 Agent 工具
│       │       ├── search_hotels.py
│       │       ├── check_availability.py
│       │       ├── booking_rules.py
│       │       ├── book_hotel.py
│       │       ├── read_booking.py
│       │       ├── cancel_booking.py
│       │       └── modify_booking.py
│       ├── api/                   # FastAPI 路由层
│       │   ├── routes/
│       │   │   ├── health.py      # 健康检查
│       │   │   ├── conversations.py  # 对话 + Agent 交互（核心）
│       │   │   ├── bookings.py    # 预订查询
│       │   │   ├── preferences.py # 用户偏好管理
│       │   │   ├── webhooks.py    # Webhook 订阅管理
│       │   │   └── metrics.py     # Prometheus 指标端点
│       │   ├── schemas/
│       │   │   ├── requests.py    # 请求模型
│       │   │   └── responses.py   # 响应模型
│       │   └── middleware/
│       │       ├── auth.py        # JWT + API Key 认证
│       │       └── rate_limit.py  # 速率限制
│       ├── db/                    # 数据库层
│       │   ├── session.py         # 异步 SQLAlchemy 配置
│       │   ├── models.py          # ORM 模型定义
│       │   └── migrations/        # Alembic 迁移
│       ├── juniper/               # Juniper SOAP 集成
│       │   ├── supplier.py        # HotelSupplier 抽象接口
│       │   ├── client.py          # 真实 SOAP 客户端
│       │   ├── mock_client.py     # Mock 客户端（开发用）
│       │   ├── serializers.py     # SOAP 响应解析
│       │   ├── exceptions.py      # Juniper 异常定义
│       │   └── circuit_breaker.py # 熔断器
│       ├── llm/                   # LLM Provider 抽象
│       │   ├── client.py          # AnthropicClient / OpenAIClient
│       │   └── exceptions.py      # LLM 异常定义
│       ├── webhooks/
│       │   └── dispatcher.py      # HMAC 签名 + 重试投递
│       └── security/              # 安全工具
├── tests/                         # 测试套件
│   ├── test_api/                  # API 路由测试
│   ├── test_agent/                # Agent 工具测试
│   ├── test_juniper/              # Juniper 客户端测试
│   └── test_security/             # 安全测试
├── scripts/                       # 工具脚本
│   ├── init_db.sh                 # 数据库初始化
│   └── init_db.sql                # 初始 Schema SQL
├── doc/                           # 项目文档
├── Dockerfile                     # 容器镜像
├── docker-compose.yml             # 多服务编排
├── pyproject.toml                 # 包定义和依赖
├── alembic.ini                    # 迁移配置
└── TODOS.md                       # 待办事项
```

## 4. 系统架构

```
  ┌─────────────────────┐
  │    IM Platform       │  (上游合作方)
  └──────────┬──────────┘
             │ HTTP + X-External-User-Id
  ┌──────────▼──────────┐
  │     FastAPI App      │
  │  ┌────────────────┐  │
  │  │ Auth Middleware │  │  JWT / API Key
  │  │ Rate Limiter   │  │  滑动窗口限流
  │  └────────────────┘  │
  │  ┌────────────────┐  │
  │  │  API Routes     │  │  REST / SSE
  │  │  /conversations │──┼──► LangGraph Agent
  │  │  /bookings      │  │
  │  │  /preferences   │  │
  │  │  /webhooks      │  │
  │  │  /metrics       │  │  Prometheus
  │  │  /health        │  │
  │  └────────────────┘  │
  └──────────┬──────────┘
       ┌─────┼─────┐
       │     │     │
  ┌────▼──┐ ┌▼───┐ ┌▼──────────┐
  │Agent  │ │ DB │ │ Webhook   │
  │Graph  │ │    │ │ Dispatcher│
  │       │ │PG18│ │ HMAC+重试  │
  │7 tools│ │    │ └───────────┘
  └───┬───┘ └────┘
      │
  ┌───▼──────────────┐
  │ HotelSupplier    │  抽象接口
  │ ┌──────────────┐ │
  │ │JuniperClient │ │  zeep SOAP
  │ │MockClient    │ │  开发用
  │ └──────────────┘ │
  └──────────────────┘
```

## 5. Agent 工作流

```
  用户消息
      │
      ▼
  ┌────────┐     ┌──────────┐
  │ Agent  │────►│  Tools   │
  │ Node   │◄────│  Node    │
  │ (LLM)  │     │ (7 tools)│
  └────┬───┘     └──────────┘
       │ (无 tool_calls 时)
       ▼
      END

  recursion_limit = 25（防止无限循环）
```

**7 个 Agent 工具：**

| 工具 | 功能 | Juniper API |
|------|------|-------------|
| search_hotels | 搜索酒店 | HotelAvail |
| check_availability | 检查房型可用性 | HotelCheckAvail |
| get_booking_rules | 获取取消政策 | HotelBookingRules |
| book_hotel | 创建预订 | HotelBooking |
| read_booking | 查询预订状态 | ReadBooking |
| cancel_booking | 取消预订 | CancelBooking |
| modify_booking | 修改预订日期 | ModifyBooking |

## 6. 环境配置

### 6.1 环境变量

复制 `.env.example` 为 `.env` 并修改：

```bash
cp .env.example .env
```

关键配置项：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| DATABASE_URL | postgresql+asyncpg://... | 数据库连接串 |
| JUNIPER_USE_MOCK | true | 是否使用 Mock 客户端 |
| JUNIPER_API_URL | https://juniper-uat... | Juniper API 地址 |
| JUNIPER_EMAIL | - | Juniper 凭据 |
| JUNIPER_PASSWORD | - | Juniper 凭据 |
| LLM_PROVIDER | anthropic | LLM 提供商 (anthropic/openai) |
| LLM_MODEL | claude-sonnet-4-20250514 | 模型名称 |
| ANTHROPIC_API_KEY | - | Anthropic API Key |
| JWT_SECRET_KEY | dev-secret-key... | JWT 签名密钥（生产必须更换） |
| API_KEYS | test-api-key | API Key 列表，逗号分隔 |
| RATE_LIMIT_USER | 60 | 每用户每分钟请求上限 |
| RATE_LIMIT_API_KEY | 300 | 每 API Key 每分钟请求上限 |
| CONVERSATION_TTL_HOURS | 24 | 对话过期时间（小时） |
| MAX_MESSAGE_HISTORY | 20 | Agent 上下文消息数上限 |

### 6.2 Docker 启动

```bash
# 启动数据库和应用
docker-compose up -d

# 查看日志
docker-compose logs -f app

# 初始化数据库（首次）
./scripts/init_db.sh --docker

# 运行迁移
alembic upgrade head
```

### 6.3 本地开发

```bash
# 安装依赖
pip install -e ".[dev]"

# 启动 PostgreSQL（使用 Docker）
docker-compose up -d db

# 运行迁移
alembic upgrade head

# 启动应用
uvicorn juniper_ai.app.main:app --reload --port 8000
```

### 6.4 运行测试

```bash
# 全部测试
python -m pytest tests/ -v

# 按模块
python -m pytest tests/test_api/ -v
python -m pytest tests/test_agent/ -v
python -m pytest tests/test_juniper/ -v

# 带覆盖率
python -m pytest tests/ --cov=juniper_ai --cov-report=term-missing
```

## 7. 认证机制

### 7.1 JWT Bearer Token（终端用户）

```
Authorization: Bearer <jwt_token>
```

JWT 使用 HS256 算法，`sub` claim 映射到 `external_user_id`。

### 7.2 API Key（IM 平台方 B2B 调用）

```
X-API-Key: <api_key>
X-External-User-Id: <end_user_id>  # 必须，标识终端用户
```

API Key 认证时必须提供 `X-External-User-Id` header，用于标识 IM 平台代理的终端用户。这确保了用户数据隔离。

## 8. 错误处理

### 8.1 Juniper API 异常层级

```
JuniperError (base)
├── SOAPTimeoutError        → 重试 2 次，backoff [1s, 3s]
├── JuniperFaultError       → 记录错误，返回描述
├── RoomUnavailableError    → 提示搜索替代方案
├── PriceChangedError       → 显示新旧价格，要求确认
├── BookingPendingError     → 提示等待
└── NoResultsError          → 提示修改搜索条件
```

### 8.2 LLM 异常层级

```
LLMError (base)
├── LLMTimeoutError         → "服务暂时不可用"
├── LLMQuotaError           → "服务暂时不可用"
├── LLMRefusalError         → 返回拒绝原因
└── LLMParseError           → 记录异常，通用错误
```

### 8.3 熔断器

Juniper API 熔断器配置：
- **触发条件：** 60 秒内 5 次连续失败
- **开路状态：** 快速拒绝，返回 "预订系统维护中"
- **半开探测：** 30 秒后允许一个探测请求
- **恢复：** 探测成功则关闭熔断器

## 9. 可观测性

### 9.1 Prometheus 指标

`GET /metrics` 端点输出以下指标：

| 指标名 | 类型 | 说明 |
|--------|------|------|
| juniperai_requests_total | Counter | HTTP 请求总数 (method, endpoint, status) |
| juniperai_booking_total | Counter | 预订总数 (status) |
| juniperai_juniper_api_latency_seconds | Histogram | Juniper API 延迟 |
| juniperai_juniper_api_errors_total | Counter | Juniper API 错误数 (error_type) |
| juniperai_active_conversations | Gauge | 活跃对话数 |

### 9.2 日志

使用 Python 标准 logging，JSON 格式。每个 Agent 工具调用都有结构化日志记录参数和结果。

## 10. Webhook 事件系统

### 10.1 支持的事件

| 事件 | 触发时机 |
|------|---------|
| booking.confirmed | 预订成功创建 |
| booking.cancelled | 预订被取消 |
| booking.modified | 预订被修改 |

### 10.2 安全机制

- HMAC-SHA256 签名（X-Webhook-Signature header）
- HTTPS 强制
- SSRF 防护（阻止私有 IP 和 localhost）
- 重试机制：最多 3 次，backoff [30s, 60s, 120s]
- 连续 3 次失败自动停用

## 11. 发布计划

### v1（当前）
- 搜索、可用性检查、预订规则查询、预订创建（4 工具）
- 通过 ENABLED_TOOLS 环境变量控制

### v2
- 加入查询、取消、修改预订（7 工具全开）
- v1 稳定运行 2 周后启用

### 未来
- 多供应商支持（HotelSupplier 抽象接口已就位）
- 多 IM 平台定制化（Agent Graph 工厂模式）
- 搜索结果缓存
- 支付集成
