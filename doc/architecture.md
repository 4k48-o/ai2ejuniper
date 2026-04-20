# JuniperAI 系统架构图

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Frontend (imToolTest)                          │
│                     React + TypeScript + Vite                           │
│                                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │UserSelect│  │ChatWindow│  │HotelCard │  │BookingCard│  │ InputBar │ │
│  └────┬─────┘  └────┬─────┘  └──────────┘  └──────────┘  └──────────┘ │
│       │              │                                                   │
│       └──────┬───────┘                                                   │
│              │  api/client.ts                                            │
│              │  Headers: X-API-Key + X-External-User-Id                  │
└──────────────┼───────────────────────────────────────────────────────────┘
               │  Vite Proxy (:5173 → :8000)
               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        FastAPI Backend (:8000)                           │
│                                                                          │
│  ┌─────────────────────── Middleware 层 ─────────────────────────────┐   │
│  │                                                                   │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────┐   │   │
│  │  │    CORS     │───▶│  Auth 认证  │───▶│  Rate Limit 限流    │   │   │
│  │  │ allow: [*]  │    │ JWT/API Key │    │ JWT:60/min          │   │   │
│  │  └─────────────┘    └─────────────┘    │ API Key:300/min     │   │   │
│  │                                         └─────────────────────┘   │   │
│  └───────────────────────────────────────────────────────────────────┘   │
│                              │                                           │
│  ┌───────────────────────── API Routes ──────────────────────────────┐   │
│  │                                                                   │   │
│  │  /api/v1/health              GET    健康检查                      │   │
│  │  /api/v1/conversations       POST   创建会话                      │   │
│  │  /api/v1/conversations/{id}  GET    查询会话                      │   │
│  │  /conversations/{id}/messages      POST   发送消息(同步)          │   │
│  │  /conversations/{id}/messages/stream POST  发送消息(SSE流式)      │   │
│  │  /api/v1/bookings            GET    预订列表                      │   │
│  │  /api/v1/bookings/{id}       GET    预订详情                      │   │
│  │  /api/v1/users/{id}/preferences GET/PUT 用户偏好                  │   │
│  │  /api/v1/webhooks            POST/GET/DELETE  Webhook管理         │   │
│  │  /metrics                    GET    Prometheus指标                 │   │
│  │                                                                   │   │
│  └───────────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────────┘
```

## 核心对话流程 (请求 → 响应)

```
用户发送消息
     │
     ▼
┌──────────────────────┐
│  1. Auth 认证         │  JWT Bearer Token 或 X-API-Key
│     ↓                │  → AuthContext(user_id, auth_type)
│  2. Rate Limit 检查   │  滑动窗口限流
│     ↓                │
│  3. 加载会话          │  SELECT Conversation JOIN User
│     (用户隔离校验)     │  WHERE User.external_id = auth.user_id
│     ↓                │
│  4. 检查会话过期       │  expires_at < now() → 410 Gone
│     ↓                │
│  5. 保存用户消息       │  INSERT INTO messages (role=user)
│     ↓                │
│  6. 加载历史消息       │  SELECT 最近 N 条消息
│     ↓                │
│  7. 调用 Agent Graph  │  LangGraph 状态机
└────────┬─────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────┐
│                   LangGraph Agent Graph                   │
│                                                           │
│   ┌──────────┐     should_continue()     ┌──────────┐   │
│   │          │──── 有 tool_calls ──────▶│          │   │
│   │  Agent   │                           │  Tools   │   │
│   │  Node    │◀────── 返回结果 ──────────│  Node    │   │
│   │          │                           │          │   │
│   │ (LLM调用)│──── 无 tool_calls ──▶ END │ (工具执行)│   │
│   └──────────┘                           └──────────┘   │
│        │                                      │          │
│        ▼                                      ▼          │
│   ┌──────────┐                     ┌─────────────────┐  │
│   │ Anthropic│                     │    8 个工具      │  │
│   │  Claude  │                     │                 │  │
│   │   或     │                     │ search_hotels   │  │
│   │ OpenAI   │                     │ check_avail     │  │
│   │  GPT     │                     │ booking_rules   │  │
│   └──────────┘                     │ book_hotel      │  │
│                                    │ list_bookings   │  │
│                                    │ read_booking    │  │
│                                    │ cancel_booking  │  │
│                                    │ modify_booking  │  │
│                                    └─────────────────┘  │
└──────────────────────────────────────────────────────────┘
         │
         ▼
┌──────────────────────┐
│  8. 提取预订数据       │  正则匹配 __BOOKING_DATA__{json}__
│     ↓                │
│  9. 持久化预订         │  幂等检查 + INSERT INTO bookings
│     ↓                │
│  10. 提取预订事件      │  正则匹配 __BOOKING_EVENT__{json}__
│      ↓               │
│  11. 更新预订状态      │  UPDATE bookings SET status=...
│      ↓               │
│  12. 触发 Webhook     │  HMAC签名 + 重试(30s,60s,120s)
│      ↓               │
│  13. 保存助手消息      │  INSERT INTO messages (role=assistant)
│      ↓               │
│  14. 事务提交          │  session.commit() (原子性)
└──────────────────────┘
         │
         ▼
    返回响应给前端
```

## 工具与外部系统交互

```
┌─────────────────────── Agent Tools ─────────────────────────┐
│                                                              │
│  ┌─────────────────┐     ┌──────────────────────────────┐   │
│  │ _user_context.py│     │ _booking_display.py          │   │
│  │                 │     │                              │   │
│  │ get_current_    │     │ guest_name_email_from_       │   │
│  │   user_id()     │     │   details()                  │   │
│  │ get_current_    │     └──────────────────────────────┘   │
│  │   user_uuid()   │                                        │
│  └────────┬────────┘                                        │
│           │ ensure_config() 从 LangGraph runtime 获取       │
│           │                                                  │
│  ┌────────┴──────────────────────────────────────────────┐  │
│  │              工具分两类                                │  │
│  │                                                       │  │
│  │  查询型 (查本地数据库)        操作型 (调外部API)        │  │
│  │  ┌───────────────┐          ┌───────────────────┐    │  │
│  │  │ list_bookings │─┐       │ search_hotels     │─┐  │  │
│  │  │ read_booking  │ │       │ check_availability│ │  │  │
│  │  └───────────────┘ │       │ get_booking_rules │ │  │  │
│  │        │           │       │ book_hotel        │ │  │  │
│  │        ▼           │       │ cancel_booking    │ │  │  │
│  │   ┌─────────┐     │       │ modify_booking    │ │  │  │
│  │   │PostgreSQL│     │       └───────────────────┘ │  │  │
│  │   │(async    │     │              │              │  │  │
│  │   │ session) │     │              ▼              │  │  │
│  │   └─────────┘     │     ┌──────────────────┐   │  │  │
│  │                    │     │  Supplier Client  │   │  │  │
│  │   用户隔离:        │     │                  │   │  │  │
│  │   WHERE user_id=   │     │  Mock (开发模式)  │   │  │  │
│  │     current_uuid   │     │  Real (生产模式)  │   │  │  │
│  │                    │     └────────┬─────────┘   │  │  │
│  └────────────────────┘              │              │  │  │
│                                      ▼              │  │  │
│                          ┌──────────────────────┐   │  │  │
│                          │   Circuit Breaker    │   │  │  │
│                          │   5次失败/60s → 熔断  │   │  │  │
│                          │   30s后半开 → 恢复    │   │  │  │
│                          └──────────┬───────────┘   │  │  │
└─────────────────────────────────────┼───────────────┘  │  │
                                      │                       │
                                      ▼                       │
                           ┌──────────────────────┐           │
                           │  Juniper SOAP API    │           │
                           │  (酒店供应商)         │           │
                           │                      │           │
                           │  HotelAvail          │           │
                           │  HotelCheckAvail     │           │
                           │  HotelBookingRules   │           │
                           │  HotelBooking        │           │
                           │  CancelBooking       │           │
                           │  ModifyBooking       │           │
                           │  ReadBooking         │           │
                           └──────────────────────┘           │
```

## 数据库模型关系

```
┌─────────────────────┐
│       users          │
├─────────────────────┤
│ id: UUID (PK)       │
│ external_id: String  │◀──── 唯一, 对应 auth.user_id
│ preferences: JSONB   │
│ created_at: DateTime │
│ updated_at: DateTime │
└────────┬────────────┘
         │
         │ 1:N
         ▼
┌─────────────────────────┐        ┌─────────────────────────────┐
│     conversations        │        │       bookings               │
├─────────────────────────┤        ├─────────────────────────────┤
│ id: UUID (PK)           │        │ id: UUID (PK)               │
│ user_id: UUID (FK)      │───┐    │ user_id: UUID (FK → users)  │
│ status: Enum            │   │    │ conversation_id: UUID (FK)  │◀─┐
│   active/completed/     │   │    │ juniper_booking_id: String  │  │
│   expired               │   │    │ idempotency_key: String (UQ)│  │
│ state: JSONB            │   │    │ status: Enum                │  │
│ language: String        │   │    │   pending/confirmed/        │  │
│ created_at: DateTime    │   │    │   cancelled/modified        │  │
│ updated_at: DateTime    │   │    │ hotel_name: String          │  │
│ expires_at: DateTime    │   │    │ check_in: String            │  │
└────────┬────────────────┘   │    │ check_out: String           │  │
         │                    │    │ total_price: String         │  │
         │ 1:N               │    │ currency: String            │  │
         ▼                    │    │ booking_details: JSONB      │  │
┌─────────────────────┐      │    │ created_at: DateTime        │  │
│      messages        │      │    │ updated_at: DateTime        │  │
├─────────────────────┤      │    └─────────────────────────────┘  │
│ id: UUID (PK)       │      │                                     │
│ conversation_id: UUID│──────┼─────────────────────────────────────┘
│   (FK, INDEXED)      │      │         1:N
│ role: Enum           │      │
│   user/assistant/    │      │
│   system/tool        │      │
│ content: Text        │      │    ┌─────────────────────────────┐
│ tool_calls: JSONB    │      │    │  webhook_subscriptions      │
│ created_at: DateTime │      │    ├─────────────────────────────┤
└─────────────────────┘      │    │ id: UUID (PK)               │
                              │    │ url: String(2048)           │
                              │    │ events: Array[String]       │
                              │    │ secret: String(255)         │
                              │    │ active: Boolean             │
                              │    │ failure_count: Integer      │
                              │    │ created_at: DateTime        │
                              │    └─────────────────────────────┘
                              │         (独立表, 无 FK 关联)
```

## 用户数据隔离机制

```
┌──────────── 隔离层 ─────────────────────────────────────────────┐
│                                                                  │
│  第1层: API 认证                                                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ X-External-User-Id: "user-bob" → auth.user_id = "user-bob"│   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  第2层: 路由层 (SQL WHERE)                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ SELECT ... JOIN users WHERE users.external_id = "user-bob" │   │
│  │ → Bob 只能看到自己的会话、预订、偏好                         │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  第3层: Agent 工具 (LangGraph config)                            │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ config = {"configurable": {"user_id": "44cb83b5-..."}}    │   │
│  │ → ensure_config() → get_current_user_uuid()               │   │
│  │ → SELECT ... WHERE bookings.user_id = UUID               │   │
│  └──────────────────────────────────────────────────────────┘   │
│                           │                                      │
│  第4层: Mock Client (开发模式)                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │ booking["user_id"] != current_user_id                     │   │
│  │ → raise BookingOwnershipError                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

## SSE 流式响应时序

```
客户端                          服务端                         LLM
  │                               │                             │
  │  POST /messages/stream        │                             │
  │──────────────────────────────▶│                             │
  │                               │  agent_graph.astream_events │
  │                               │────────────────────────────▶│
  │  event: status                │                             │
  │  data: {"status":"thinking"}  │                             │
  │◀──────────────────────────────│                             │
  │                               │         on_tool_start       │
  │  event: status                │◀────────────────────────────│
  │  data: {"calling_tool":       │                             │
  │         "search_hotels"}      │                             │
  │◀──────────────────────────────│                             │
  │                               │         on_tool_end         │
  │                               │◀────────────────────────────│
  │                               │                             │
  │                               │    on_chat_model_stream     │
  │  event: token                 │◀────────────────────────────│
  │  data: {"text":"Here"}        │                             │
  │◀──────────────────────────────│                             │
  │                               │                             │
  │  event: token                 │    on_chat_model_stream     │
  │  data: {"text":" are"}        │◀────────────────────────────│
  │◀──────────────────────────────│                             │
  │                               │                             │
  │  ...更多 tokens...            │        ...更多 chunks...     │
  │                               │                             │
  │  event: done                  │     on_chat_model_end       │
  │  data: {"text":"完整回复"}     │◀────────────────────────────│
  │◀──────────────────────────────│                             │
  │                               │                             │
  │                               │── 持久化预订数据 ──▶ DB      │
  │                               │── 保存助手消息 ──▶ DB        │
  │                               │── 触发 Webhook ──▶ 外部     │
  │                               │                             │
```

## 基础设施部署

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                        │
│                                                          │
│  ┌──────────────────┐     ┌──────────────────────────┐  │
│  │   app (FastAPI)   │     │   db (PostgreSQL 16)     │  │
│  │                   │     │                          │  │
│  │  Port: 8000       │────▶│  Port: 5433:5432         │  │
│  │  Host: 0.0.0.0    │     │  Database: juniper_ai    │  │
│  │                   │     │  User: postgres           │  │
│  │  uvicorn          │     │  Volume: pgdata           │  │
│  │  --reload (dev)   │     │  Healthcheck: pg_isready  │  │
│  └──────────────────┘     └──────────────────────────┘  │
│           │                                              │
│           │ depends_on: db (service_healthy)              │
│                                                          │
└─────────────────────────────────────────────────────────┘
           │
     ┌─────┴──────┐
     │ Vite (:5173)│  开发前端, proxy /api → :8000
     └────────────┘

外部依赖:
  ├── Anthropic API (Claude LLM)
  ├── OpenAI API (GPT LLM, 备选)
  └── Juniper SOAP API (酒店供应商, 生产模式)
```
