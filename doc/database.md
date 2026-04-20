# JuniperAI 数据库文档

**数据库:** PostgreSQL 18
**驱动:** asyncpg (异步)
**ORM:** SQLAlchemy 2.0+ (Async)
**迁移:** Alembic

---

## 1. ER 关系图

```
  ┌──────────────┐       ┌─────────────────┐       ┌──────────────┐
  │    users     │       │  conversations  │       │   messages   │
  ├──────────────┤       ├─────────────────┤       ├──────────────┤
  │ id (PK)      │◄──┐   │ id (PK)         │ ◄──┐  │ id (PK)      │
  │ external_id  │   └── │ user_id (FK)    │    └──│ conversation │
  │ preferences  │       │ status          │       │   _id (FK)   │
  │ created_at   │       │ state           │       │ role         │
  │ updated_at   │       │ language        │       │ content      │
  └──────┬───────┘       │ created_at      │       │ tool_calls   │
         │               │ updated_at      │       │ created_at   │
         │               │ expires_at      │       └──────────────┘
         │               └────────┬────────┘
         │                        │
         │               ┌────────▼────────┐
         │               │    bookings     │
         └──────────────►├─────────────────┤
                         │ id (PK)         │
                         │ user_id (FK)    │
                         │ conversation    │
                         │   _id (FK)      │
                         │ juniper_booking │
                         │   _id           │
                         │ idempotency_key │
                         │ status          │
                         │ hotel_name      │
                         │ check_in/out    │
                         │ total_price     │
                         │ currency        │
                         │ booking_details │
                         │ created_at      │
                         │ updated_at      │
                         └─────────────────┘

  ┌──────────────────────┐
  │ webhook_subscriptions│
  ├──────────────────────┤
  │ id (PK)              │  (独立表，无 FK)
  │ url                  │
  │ events               │
  │ secret               │
  │ active               │
  │ failure_count        │
  │ created_at           │
  └──────────────────────┘
```

---

## 2. 表结构详细定义

### 2.1 users — 用户表

存储通过 IM 平台接入的终端用户信息。

| 列名 | 类型 | 约束 | 默认值 | 说明 |
|------|------|------|--------|------|
| id | UUID | PK | uuid4() | 内部用户 ID |
| external_id | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | - | 外部平台用户标识 |
| preferences | JSONB | - | {} | 用户偏好（星级、位置、餐食等） |
| created_at | TIMESTAMP WITH TZ | NOT NULL | now() | 创建时间 |
| updated_at | TIMESTAMP WITH TZ | NOT NULL | now() | 更新时间（自动触发器） |

**索引:**
- `ix_users_external_id` (external_id) — UNIQUE

**preferences JSONB 结构示例:**

```json
{
  "star_rating": "4 stars",
  "location_preference": "central",
  "board_type": "Bed & Breakfast",
  "smoking": "non-smoking",
  "floor_preference": "high floor",
  "budget_range": "€150-250/night"
}
```

**关系:**
- 1:N → conversations
- 1:N → bookings

---

### 2.2 conversations — 对话表

管理 Agent 对话会话的生命周期。

| 列名 | 类型 | 约束 | 默认值 | 说明 |
|------|------|------|--------|------|
| id | UUID | PK | uuid4() | 对话 ID |
| user_id | UUID | FK → users.id, INDEX | - | 所属用户 |
| status | ENUM(ConversationStatus) | NOT NULL | 'active' | 对话状态 |
| state | JSONB | - | {} | Agent 状态快照 |
| language | VARCHAR(10) | - | 'en' | 对话语言 |
| created_at | TIMESTAMP WITH TZ | NOT NULL | now() | 创建时间 |
| updated_at | TIMESTAMP WITH TZ | NOT NULL | now() | 更新时间 |
| expires_at | TIMESTAMP WITH TZ | NOT NULL | now() + 24h | 过期时间 |

**索引:**
- `ix_conversations_user_id` (user_id)

**ConversationStatus 枚举:**

| 值 | 说明 |
|----|------|
| active | 对话进行中 |
| completed | 对话已完成 |
| expired | 对话已过期（超过 TTL） |

**过期机制:**
- `expires_at` 在创建时设为 `now() + conversation_ttl_hours`（默认 24 小时）
- 每次用户发送消息时刷新 `expires_at`
- 访问已过期对话返回 410 Gone，状态更新为 expired

**关系:**
- N:1 → users
- 1:N → messages
- 1:N → bookings

---

### 2.3 messages — 消息表

存储对话中的所有消息（用户、助手、系统、工具）。

| 列名 | 类型 | 约束 | 默认值 | 说明 |
|------|------|------|--------|------|
| id | UUID | PK | uuid4() | 消息 ID |
| conversation_id | UUID | FK → conversations.id, INDEX | - | 所属对话 |
| role | ENUM(MessageRole) | NOT NULL | - | 消息角色 |
| content | TEXT | NOT NULL | - | 消息内容 |
| tool_calls | JSONB | NULLABLE | null | 工具调用记录 |
| created_at | TIMESTAMP WITH TZ | NOT NULL | now() | 创建时间 |

**索引:**
- `ix_messages_conversation_id` (conversation_id)

**MessageRole 枚举:**

| 值 | 说明 |
|----|------|
| user | 用户发送的消息 |
| assistant | AI 助手回复 |
| system | 系统消息（如系统提示词） |
| tool | 工具执行结果 |

**tool_calls JSONB 结构示例:**

```json
[
  {
    "name": "search_hotels",
    "args": {
      "destination": "Barcelona",
      "check_in": "2026-04-15",
      "check_out": "2026-04-18"
    },
    "id": "call_abc123"
  }
]
```

**排序:** 按 `created_at` 升序，保证消息时间线正确。

---

### 2.4 bookings — 预订表

存储通过 Agent 创建的酒店预订记录。

| 列名 | 类型 | 约束 | 默认值 | 说明 |
|------|------|------|--------|------|
| id | UUID | PK | uuid4() | 内部预订 ID |
| user_id | UUID | FK → users.id, INDEX | - | 预订用户 |
| conversation_id | UUID | FK → conversations.id | - | 关联的对话 |
| juniper_booking_id | VARCHAR(255) | NULLABLE | null | Juniper 系统的预订 ID（如 JNP-A1B2C3D4） |
| idempotency_key | VARCHAR(255) | UNIQUE, INDEX | - | 幂等键（防重复预订） |
| status | ENUM(BookingStatus) | NOT NULL | 'pending' | 预订状态 |
| hotel_name | VARCHAR(500) | NULLABLE | null | 酒店名称 |
| check_in | VARCHAR(10) | NULLABLE | null | 入住日期 (YYYY-MM-DD) |
| check_out | VARCHAR(10) | NULLABLE | null | 退房日期 (YYYY-MM-DD) |
| total_price | VARCHAR(50) | NULLABLE | null | 总价 |
| currency | VARCHAR(10) | NULLABLE | null | 币种（EUR, USD 等） |
| booking_details | JSONB | NULLABLE | null | 完整预订详情 |
| created_at | TIMESTAMP WITH TZ | NOT NULL | now() | 创建时间 |
| updated_at | TIMESTAMP WITH TZ | NOT NULL | now() | 更新时间 |

**索引:**
- `ix_bookings_user_id` (user_id)
- `ix_bookings_idempotency_key` (idempotency_key) — UNIQUE

**BookingStatus 枚举:**

| 值 | 说明 |
|----|------|
| pending | 预订处理中 |
| confirmed | 预订已确认 |
| cancelled | 预订已取消 |
| modified | 预订已修改 |

**幂等键生成规则:**
- 格式: `{conversation_id}:{juniper_booking_id}`
- 保证同一对话中不会重复写入同一笔 Juniper 预订

**booking_details JSONB 结构示例:**

```json
{
  "booking_id": "JNP-A1B2C3D4",
  "status": "confirmed",
  "hotel_name": "NH Collection Barcelona",
  "check_in": "2026-04-15",
  "check_out": "2026-04-18",
  "total_price": "180.00",
  "currency": "EUR",
  "rate_plan_code": "RPC_001_DBL_BB",
  "guest_name": "Zhang San",
  "guest_email": "zhangsan@example.com"
}
```

**关系:**
- N:1 → users
- N:1 → conversations

---

### 2.5 webhook_subscriptions — Webhook 订阅表

管理 IM 平台方注册的 Webhook 回调。

| 列名 | 类型 | 约束 | 默认值 | 说明 |
|------|------|------|--------|------|
| id | UUID | PK | uuid4() | 订阅 ID |
| url | VARCHAR(2048) | NOT NULL | - | 回调 URL（HTTPS） |
| events | VARCHAR[] (ARRAY) | NOT NULL | [] | 订阅的事件类型列表 |
| secret | VARCHAR(255) | NOT NULL | - | HMAC-SHA256 签名密钥 |
| active | BOOLEAN | NOT NULL | true | 是否激活 |
| failure_count | INTEGER | NOT NULL | 0 | 连续失败次数 |
| created_at | TIMESTAMP WITH TZ | NOT NULL | now() | 创建时间 |

**自动停用机制:**
- `failure_count` 达到 3 时，`active` 自动设为 false
- 投递成功时 `failure_count` 重置为 0

**events 数组可选值:**
- `booking.confirmed`
- `booking.cancelled`
- `booking.modified`

---

## 3. 数据库迁移

### 迁移文件

| 版本 | 文件 | 说明 |
|------|------|------|
| 6be8710c5d03 | initial_tables | 创建全部 5 张表 + 枚举 + 索引 + 触发器 |

### 运行迁移

```bash
# 升级到最新
alembic upgrade head

# 查看当前版本
alembic current

# 查看迁移历史
alembic history

# 创建新迁移
alembic revision --autogenerate -m "描述"

# 回滚一步
alembic downgrade -1
```

### 数据库触发器

`updated_at` 字段通过数据库触发器自动更新：

```sql
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';
```

应用于 `users`、`conversations`、`bookings` 表。

---

## 4. 连接配置

### 连接串格式

```
postgresql+asyncpg://<user>:<password>@<host>:<port>/<database>
```

### 默认配置

| 环境 | 连接串 |
|------|--------|
| 开发 (本地) | postgresql+asyncpg://postgres:postgres@localhost:5433/juniper_ai |
| 开发 (Docker) | postgresql+asyncpg://postgres:postgres@db:5432/juniper_ai |

### 连接池配置

| 参数 | 值 | 说明 |
|------|-----|------|
| pool_size | 10 | 连接池大小 |
| echo | True (dev) | 开发模式打印 SQL |
| expire_on_commit | False | 提交后不过期对象 |

### Docker 数据库服务

```yaml
# docker-compose.yml
db:
  image: postgres:18
  ports:
    - "5433:5432"
  environment:
    POSTGRES_DB: juniper_ai
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
  volumes:
    - pgdata:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U postgres"]
    interval: 5s
    timeout: 5s
    retries: 5
```

---

## 5. 数据流向图

```
  用户发消息
      │
      ▼
  ┌─────────┐
  │messages  │  INSERT (role=user)
  └────┬─────┘
       │
       ▼ Agent 处理
       │
  ┌────┴─────┐
  │messages  │  INSERT (role=assistant)
  └────┬─────┘
       │ (如果有预订)
       ▼
  ┌─────────┐     ┌──────────────────────┐
  │bookings │────►│webhook_subscriptions │
  │ INSERT  │     │ 查询 active 订阅     │
  └─────────┘     │ 投递事件             │
                  └──────────────────────┘
```

---

## 6. 查询模式

### 常用查询

**按用户查询对话:**
```sql
SELECT * FROM conversations
WHERE user_id = (SELECT id FROM users WHERE external_id = :ext_id)
ORDER BY created_at DESC;
```

**按用户查询预订:**
```sql
SELECT b.* FROM bookings b
JOIN users u ON b.user_id = u.id
WHERE u.external_id = :ext_id
ORDER BY b.created_at DESC;
```

**加载对话消息历史:**
```sql
SELECT * FROM messages
WHERE conversation_id = :conv_id
ORDER BY created_at ASC;
```

**查询活跃 webhook 订阅:**
```sql
SELECT * FROM webhook_subscriptions
WHERE active = true AND :event_type = ANY(events);
```

### 索引覆盖

| 查询模式 | 使用的索引 |
|---------|-----------|
| users WHERE external_id = ? | ix_users_external_id |
| conversations WHERE user_id = ? | ix_conversations_user_id |
| messages WHERE conversation_id = ? | ix_messages_conversation_id |
| bookings WHERE user_id = ? | ix_bookings_user_id |
| bookings WHERE idempotency_key = ? | ix_bookings_idempotency_key |

---

## 7. 初始化脚本

### 手动初始化（不使用 Alembic）

```bash
./scripts/init_db.sh --docker
```

该脚本执行 `scripts/init_db.sql`，创建所有表、枚举、索引和触发器。

### 使用 Alembic 初始化（推荐）

```bash
alembic upgrade head
```

两种方式效果相同。推荐使用 Alembic，因为后续 schema 变更可以通过迁移管理。
