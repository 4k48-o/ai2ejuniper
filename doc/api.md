# JuniperAI API 接口文档

**Base URL:** `http://localhost:8000/api/v1`
**版本:** 0.1.0

---

## 认证方式

所有接口（除 `/health` 和 `/metrics`）都需要认证。支持两种方式：

### JWT Bearer Token

```
Authorization: Bearer <jwt_token>
```

JWT Payload 要求：
- `sub`: 用户的 external_id（必须）
- 算法: HS256

### API Key + 终端用户标识

```
X-API-Key: <api_key>
X-External-User-Id: <end_user_id>
```

- `X-API-Key`: 由系统管理员分配的 API Key
- `X-External-User-Id`: IM 平台方标识其终端用户的 ID（对话和预订相关接口必须提供）

---

## 速率限制

| 认证方式 | 限制 | 窗口 |
|---------|------|------|
| JWT 用户 | 60 次 | 1 分钟 |
| API Key | 300 次 | 1 分钟 |

超限返回 `429 Too Many Requests`，包含 `Retry-After` header。

---

## 1. 健康检查

### GET /api/v1/health

无需认证。

**响应 200:**

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "environment": "development"
}
```

---

## 2. 对话管理

### POST /api/v1/conversations

创建新的对话会话。

**请求体:**

```json
{
  "external_user_id": "user-12345"
}
```

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| external_user_id | string | 是 | 外部平台的用户标识 |

**响应 200:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "active",
  "language": "en",
  "created_at": "2026-04-01T10:00:00Z"
}
```

**说明:**
- 对话默认有效期 24 小时（可配置）
- 如果 external_user_id 对应的用户不存在，会自动创建

---

### POST /api/v1/conversations/{conversation_id}/messages

发送消息并获取 Agent 同步响应。

**路径参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| conversation_id | UUID | 对话 ID |

**请求体:**

```json
{
  "content": "我想在巴塞罗那找一家四星级酒店，4月15日入住，4月18日退房"
}
```

| 字段 | 类型 | 必须 | 约束 | 说明 |
|------|------|------|------|------|
| content | string | 是 | 1-5000 字符 | 用户消息内容 |

**响应 200:**

```json
{
  "text": "我为您找到了以下巴塞罗那的酒店...",
  "data": null,
  "status": "idle"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| text | string | Agent 回复文本 |
| data | object/null | 结构化数据（如搜索结果） |
| status | string | 当前状态: idle/searching/selecting/confirming/booking/completed/managing |

**错误:**

| 状态码 | 说明 |
|--------|------|
| 400 | API Key 认证缺少 X-External-User-Id |
| 404 | 对话不存在或不属于当前用户 |
| 410 | 对话已过期 |

---

### POST /api/v1/conversations/{conversation_id}/messages/stream

发送消息并获取 SSE 流式响应。

**请求体:** 同 `/messages`

**响应:** `text/event-stream`

SSE 事件格式：

```
event: status
data: {"status": "thinking"}

event: status
data: {"status": "calling_tool", "tool": "search_hotels"}

event: token
data: {"text": "我为您"}

event: token
data: {"text": "找到了"}

event: done
data: {"text": "我为您找到了以下巴塞罗那的酒店..."}

event: error
data: {"error": "服务暂时不可用"}
```

| 事件类型 | 说明 |
|---------|------|
| status | Agent 状态变化（thinking, calling_tool） |
| token | 文本流式输出片段 |
| done | 完整响应 |
| error | 错误信息 |

---

### GET /api/v1/conversations/{conversation_id}

获取对话状态。

**响应 200:**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "660e8400-e29b-41d4-a716-446655440001",
  "status": "active",
  "language": "zh",
  "created_at": "2026-04-01T10:00:00Z"
}
```

| status 值 | 说明 |
|-----------|------|
| active | 对话进行中 |
| completed | 对话已完成 |
| expired | 对话已过期 |

---

## 3. 预订查询

### GET /api/v1/bookings

查询当前用户的所有预订。

**响应 200:**

```json
[
  {
    "id": "770e8400-e29b-41d4-a716-446655440002",
    "juniper_booking_id": "JNP-A1B2C3D4",
    "status": "confirmed",
    "hotel_name": "NH Collection Barcelona Gran Hotel Calderón",
    "check_in": "2026-04-15",
    "check_out": "2026-04-18",
    "total_price": "180.00",
    "currency": "EUR",
    "created_at": "2026-04-01T10:05:00Z"
  }
]
```

---

### GET /api/v1/bookings/{booking_id}

查询单个预订详情。

**路径参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| booking_id | UUID | 预订 ID |

**响应 200:** 同上单个对象

**错误:**

| 状态码 | 说明 |
|--------|------|
| 404 | 预订不存在或不属于当前用户 |

---

## 4. 用户偏好

### GET /api/v1/users/{user_external_id}/preferences

获取用户偏好设置。

**路径参数:**

| 参数 | 类型 | 说明 |
|------|------|------|
| user_external_id | string | 用户外部 ID（必须与认证用户匹配） |

**响应 200:**

```json
{
  "user_id": "660e8400-e29b-41d4-a716-446655440001",
  "preferences": {
    "star_rating": "4 stars",
    "board_type": "Bed & Breakfast",
    "budget_range": "€150-250/night"
  }
}
```

**错误:**

| 状态码 | 说明 |
|--------|------|
| 403 | 无权访问其他用户的偏好 |
| 404 | 用户不存在 |

---

### PUT /api/v1/users/{user_external_id}/preferences

更新用户偏好（增量合并，不会覆盖未指定字段）。

**请求体:**

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

| 字段 | 类型 | 必须 | 说明 |
|------|------|------|------|
| star_rating | string | 否 | 星级偏好，如 "4 stars" |
| location_preference | string | 否 | 位置偏好，如 "central" |
| board_type | string | 否 | 餐食类型，如 "Bed & Breakfast" |
| smoking | string | 否 | 吸烟偏好，如 "non-smoking" |
| floor_preference | string | 否 | 楼层偏好，如 "high floor" |
| budget_range | string | 否 | 预算范围，如 "€150-250/night" |

**响应 200:** 同 GET

---

## 5. Webhook 管理

**注意：** Webhook 管理接口仅限 API Key 认证。

### POST /api/v1/webhooks

注册 Webhook 订阅。

**请求体:**

```json
{
  "url": "https://your-platform.com/webhooks/juniper",
  "events": ["booking.confirmed", "booking.cancelled"],
  "secret": "your-webhook-secret-min-16-chars"
}
```

| 字段 | 类型 | 必须 | 约束 | 说明 |
|------|------|------|------|------|
| url | string | 是 | HTTPS | 回调 URL |
| events | string[] | 是 | 见下表 | 订阅的事件类型 |
| secret | string | 是 | >=16 字符 | HMAC-SHA256 签名密钥 |

**可订阅事件：**

| 事件 | 说明 |
|------|------|
| booking.confirmed | 预订成功创建 |
| booking.cancelled | 预订被取消 |
| booking.modified | 预订日期被修改 |

**响应 200:**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "url": "https://your-platform.com/webhooks/juniper",
  "events": ["booking.confirmed", "booking.cancelled"],
  "active": true,
  "created_at": "2026-04-01T10:00:00Z"
}
```

**安全要求：**
- URL 必须使用 HTTPS
- 不允许 localhost、127.0.0.1、私有 IP 地址
- secret 最少 16 个字符

---

### GET /api/v1/webhooks

列出所有 Webhook 订阅。

**响应 200:** WebhookResponse 数组

---

### DELETE /api/v1/webhooks/{webhook_id}

删除 Webhook 订阅。

**响应 200:**

```json
{
  "status": "deleted"
}
```

---

### Webhook 投递格式

当事件触发时，系统向注册 URL 发送 POST 请求：

**Headers:**

```
Content-Type: application/json
X-Webhook-Signature: <hmac-sha256-hex>
X-Event-Type: booking.confirmed
```

**Body:**

```json
{
  "event_type": "booking.confirmed",
  "booking_id": "770e8400-e29b-41d4-a716-446655440002",
  "timestamp": "2026-04-01T10:05:00Z",
  "data": {
    "hotel_name": "NH Collection Barcelona",
    "check_in": "2026-04-15",
    "check_out": "2026-04-18",
    "total_price": "180.00",
    "currency": "EUR"
  }
}
```

**签名验证（接收方）：**

```python
import hmac, hashlib

expected = hmac.new(
    secret.encode(),
    request.body,
    hashlib.sha256
).hexdigest()

assert request.headers["X-Webhook-Signature"] == expected
```

**重试策略：**
- 非 2xx 响应或连接失败时重试
- 重试间隔：30s, 60s, 120s
- 连续 3 次失败后自动停用该订阅

---

## 6. 监控指标

### GET /metrics

无需认证。返回 Prometheus 文本格式的指标数据。

**响应 200:** `text/plain; version=0.0.4`

```
# HELP juniperai_requests_total Total HTTP requests
# TYPE juniperai_requests_total counter
juniperai_requests_total{method="POST",endpoint="/conversations",status="200"} 42

# HELP juniperai_booking_total Total bookings
# TYPE juniperai_booking_total counter
juniperai_booking_total{status="confirmed"} 10
juniperai_booking_total{status="cancelled"} 2
```

---

## 7. 错误响应格式

所有错误统一返回 JSON：

```json
{
  "detail": "错误描述信息"
}
```

| 状态码 | 说明 |
|--------|------|
| 400 | 请求参数无效 |
| 401 | 认证失败（无 token 或 token 无效） |
| 403 | 权限不足（如访问他人数据） |
| 404 | 资源不存在 |
| 410 | 对话已过期 |
| 429 | 请求频率超限 |
| 500 | 服务器内部错误 |

---

## 8. 典型集成流程

### IM 平台方集成示例

```
1. 获取 API Key 和配置 webhook
   POST /api/v1/webhooks
   Headers: X-API-Key: <your_key>

2. 用户发起酒店搜索时，创建对话
   POST /api/v1/conversations
   Headers: X-API-Key: <key>, X-External-User-Id: <im_user_id>
   Body: {"external_user_id": "<im_user_id>"}

3. 转发用户消息给 Agent
   POST /api/v1/conversations/{id}/messages/stream
   Headers: X-API-Key: <key>, X-External-User-Id: <im_user_id>
   Body: {"content": "用户消息"}

4. 解析 SSE 事件流，实时展示给用户

5. 预订成功后，通过 webhook 接收确认通知

6. 用户查询预订时
   GET /api/v1/bookings
   Headers: X-API-Key: <key>, X-External-User-Id: <im_user_id>
```
