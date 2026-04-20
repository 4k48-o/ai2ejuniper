# JuniperAI 测试用例计划

> 版本: v1.1 | 日期: 2026-04-02 | 状态: 待执行

> **本轮**：暂不扩展 webhook 相关自动化（**WH-07** 及以后、**AUTH-06** / **AUTH-14**、**DISPATCH-*** 等保持未勾选）；优先推进对话、偏好、限流等待办项。

## 实现口径对齐备注（2026-04-02）

- 当前代码已将限流依赖接入核心 API 路由（`/conversations`、`/bookings`、`/preferences`、`/webhooks`），`RATE-*` 可按真实接口行为执行。
- Agent 工具中的 `read_booking` / `list_bookings` 当前以本地数据库为主，不再依赖 supplier mock 返回格式。`TOOL-20`、`TOOL-24` 需按本地持久化语义重写断言。
- 对话层已支持从 tool 输出提取 `__BOOKING_EVENT__`，并更新本地 booking 状态（`booking.cancelled` / `booking.modified`）后分发 webhook。
- 时间语义（明天/下周等）仍主要依赖模型推理，尚无独立日期解析模块；`TIME-*` 建议拆成「模型行为 E2E」和「日期解析单元测试（待实现）」两类。
- `POST /api/v1/webhooks` 注册成功返回 **201 Created**（与 REST 语义及 **WH-01** 一致）。
- 公开 API 的 `GET /bookings` 与 `GET /bookings/{id}` 响应模型**不含** `booking_details`；该字段仅在 DB 层存在时，用例应在集成测试中查库或未来扩展 API 后再断言返回体。
- 表中「已有覆盖」为手工估算，**以 `pytest tests/` 与覆盖率报告定期对账为准**。

## 自动化覆盖说明

- 下列条目前缀 `[x]` 表示：**当前仓库 `tests/` 内已有对应用例，且 `pytest tests/` 通过**（以中间件/路由/工具层行为为准；部分与计划原文表述可能略有粒度差异）。
- 仍为 `[ ]` 的条目：无测试、或仅有 E2E/人工场景、或需真实 DB/外部服务/LLM。
- **维护约定**：新增或删除测试时，请同步更新本节勾选状态与「测试文件与用例对照」表。

### 测试文件与用例对照

| 测试文件 | 主要覆盖的计划 ID |
|----------|-------------------|
| `tests/test_api/test_auth.py` | AUTH-01～05、AUTH-07～10 |
| `tests/test_api/test_conversations.py` | CONV-01～04、CONV-05～07、CONV-08、CONV-09～16、CONV-17、CONV-18；**BOOK-10**；**PERSIST-01～08**；`_extract_booking_events` / `_apply_booking_event` |
| `tests/test_api/test_bookings.py` | AUTH-12、BOOK-01～08 |
| `tests/test_api/test_preferences.py` | PREF-01、PREF-02、PREF-04、PREF-05、PREF-06、PREF-07、PREF-08 |
| `tests/test_api/test_rate_limit.py` | RATE-01～06；核心路由挂载 `check_rate_limit` |
| `tests/test_api/test_webhooks.py` | WH-01（`POST /webhooks` → 201）、WH-05、WH-06 |
| `tests/test_security/test_webhook_ssrf.py` | WH-02～WH-04（URL 校验层） |
| `tests/test_api/test_health.py` | （健康检查，计划中未单列 case ID） |
| `tests/test_agent/test_tools.py` | TOOL-01～32 |
| `tests/test_juniper/test_mock_client.py` | **BOOK-09** / MOCK-05、MOCK-02、MOCK-03、MOCK-07、MOCK-08 |
| `tests/test_juniper/test_serializers.py` | TOOL-01 相关（`hotels_to_llm_summary` 格式化） |
| `tests/test_juniper/test_circuit_breaker.py` | （熔断器单元测试，计划中未单列） |

## 测试范围总览

| 模块 | 优先级 | 用例数 | 已有覆盖 | 状态 |
|------|--------|--------|---------|------|
| 认证与鉴权 | P0 | 15 | 8 | 部分 |
| 对话 API | P0 | 18 | 17 | 部分 |
| 预定 API | P0 | 10 | 10 | 已完成 |
| Agent 工具 | P0 | 32 | 29 | 已完成 |
| 预定持久化与幂等 | P0 | 8 | 8 | 已完成 |
| 用户偏好 API | P1 | 8 | 7 | 部分 |
| Webhook 管理 | P1 | 12 | 5 | 部分 |
| Webhook 分发与重试 | P1 | 8 | 0 | 未覆盖 |
| 限流 | P1 | 6 | 6 | 已完成 |
| Agent 对话流 (E2E) | P1 | 10 | 0 | 未覆盖 |
| 用户画像与预定策略 | P1 | 20 | 0 | 未覆盖 |
| 时间维度与日期处理 | P1 | 14 | 0 | 未覆盖 |
| 酒店筛选与推荐策略 | P1 | 16 | 0 | 未覆盖 |
| 多用户并发与隔离 | P1 | 8 | 1 | 部分 |
| 前端 API 集成 | P2 | 6 | 0 | 未覆盖 |
| Mock 数据一致性 | P2 | 8 | 0 | 未覆盖 |
| **合计** | | **199** | 见下方 `[x]` 勾选 + `pytest tests/` | |

---

## 1. 认证与鉴权 (P0)

### 1.1 JWT 认证

- [x] **AUTH-01** JWT 有效 token，返回 200 + 正确的 user_id（`test_auth.py`：`get_auth_context` 得到正确 `user_id`）
- [x] **AUTH-02** JWT 过期 token，返回 401
- [x] **AUTH-03** JWT 无效签名，返回 401
- [x] **AUTH-04** JWT 缺少 `sub` claim，返回 401（`test_auth.py`：`test_jwt_missing_sub_returns_401`）
- [x] **AUTH-05** JWT 空 token，返回 401（`test_auth.py`：`test_empty_bearer_token_returns_401`）

### 1.2 API Key 认证

- [ ] **AUTH-06** 有效 API Key：例如 `POST /api/v1/webhooks`（HTTPS URL + 合法 body）返回 **201**，且 `GET /api/v1/webhooks` 在仅 API Key 下返回 200（当前仅覆盖 **POST 201**，未覆盖 **GET**）
- [x] **AUTH-07** 无效 API Key，返回 401
- [x] **AUTH-08** API Key + `X-External-User-Id`，user_id 取 header 值
- [x] **AUTH-09** API Key 无 `X-External-User-Id`，user_id 为 `apikey:{key[:8]}`

### 1.3 无认证

- [x] **AUTH-10** 无 Authorization 和 X-API-Key header，返回 401

### 1.4 用户数据隔离

- [x] **AUTH-11** 用户 A 无法访问用户 B 的 conversation，返回 404
- [x] **AUTH-12** 用户 A 无法访问用户 B 的 booking，返回 404（`GET /bookings/{id}` 按 `User.external_id` 过滤；`test_bookings.py`：`test_get_booking_other_user_returns_404`）
- [x] **AUTH-13** 用户 A 无法修改用户 B 的 preferences，返回 403
- [ ] **AUTH-14** Webhook 端点拒绝 JWT 认证，返回 403
- [x] **AUTH-15** 对话消息端点 API Key 模式必须提供 `X-External-User-Id`，否则返回 400

---

## 2. 对话 API (P0)

### 2.1 创建对话

- [x] **CONV-01** 正常创建对话，返回 200 + conversation_id + status=active
- [x] **CONV-02** 同一 external_user_id 多次创建，复用同一 User 记录（`_get_or_create_user`：`test_get_or_create_user_reuses_same_user_for_same_external_id`）
- [x] **CONV-03** 新 external_user_id 自动创建 User 记录（`test_get_or_create_user_inserts_new_user`）
- [x] **CONV-04** 缺少 external_user_id 字段，返回 422（`CreateConversationRequest` 必填 + `test_create_conversation_missing_external_user_id_returns_422`）

### 2.2 发送消息（同步）

- [x] **CONV-05** 正常发送消息，返回 AI 回复文本
- [x] **CONV-06** 对话不存在，返回 404
- [x] **CONV-07** 对话已过期，返回 410
- [x] **CONV-08** 消息内容为空字符串，返回 422（`test_send_message_empty_content_returns_422`：`SendMessageRequest` `min_length=1`）
- [x] **CONV-09** 消息内容超过 5000 字符，返回 422（`SendMessageRequest` `max_length=5000` + `test_send_message_content_over_5000_chars_returns_422`）
- [x] **CONV-10** 消息发送后，user 和 assistant 消息均持久化到 DB（`test_send_message_persists_user_and_assistant_messages` 断言 `Message`/`MessageRole`）
- [x] **CONV-11** 消息发送后，conversation.expires_at 被刷新（`test_send_message_refreshes_conversation_expires_at`，真实 `is_expired` 桩对象）

### 2.3 发送消息（SSE 流式）

- [x] **CONV-12** 正常流式消息，收到 status → token → done 事件序列（mock `astream_events` + `test_stream_message_emits_status_token_done_sequence`）
- [x] **CONV-13** 流式消息中 tool 调用，收到 `calling_tool` status 事件（`on_tool_start` → `test_stream_message_emits_calling_tool_on_tool_start`）
- [x] **CONV-14** Agent 异常，收到 error 事件（`test_stream_message_agent_failure_emits_error_event`；无 `done`）
- [x] **CONV-15** 流式消息完成后，消息正确持久化（`test_stream_message_persists_user_and_assistant_after_done` + `flush`）

### 2.4 获取对话

- [x] **CONV-16** 获取存在的对话，返回正确状态
- [x] **CONV-17** 获取已过期的对话，status 更新为 expired（`test_get_conversation_expired_marks_status_expired`）
- [x] **CONV-18** 获取不存在的对话，返回 404

---

## 3. 预定 API (P0)

### 3.1 预定列表

- [x] **BOOK-01** 用户有预定记录，返回按 created_at DESC 排序的列表（`test_list_bookings_ordered_by_created_at_desc`：SQL 含 `ORDER BY bookings.created_at DESC`，响应顺序与 mock 行序一致）
- [x] **BOOK-02** 用户无预定记录，返回空列表（`test_list_bookings_empty_for_user`）
- [x] **BOOK-03** 返回字段完整（id, juniper_booking_id, status, hotel_name, check_in, check_out, total_price, currency, created_at）（`test_list_bookings_response_has_all_fields`）
- [x] **BOOK-04** 只返回当前用户的预定（不泄露其他用户数据）（`test_list_bookings_query_scoped_to_authenticated_user`：SQL 含 `JOIN users` + `users.external_id`）

### 3.2 预定详情

- [x] **BOOK-05** 查询存在的预定，返回完整详情（`test_get_booking_by_id_returns_full_detail`）
- [x] **BOOK-06** 查询不存在的预定 ID，返回 404（`test_get_booking_unknown_id_returns_404`）
- [x] **BOOK-07** 查询其他用户的预定 ID，返回 404（不是 403，防止枚举）（与 **AUTH-12** / **MULTI-04** 同测：`test_get_booking_other_user_returns_404`）

### 3.3 预定状态

- [x] **BOOK-08** 预定 status 包含：confirmed / cancelled / modified（当前用例断言列表中出现 `cancelled`；`confirmed`/`modified` 未在同文件单独断言）
- [x] **BOOK-09** 预定字段 juniper_booking_id 格式为 `JNP-XXXXXXXX`（Mock 下单：`test_mock_client.py` 中 `test_hotel_booking_id_matches_jnp_format`；`test_hotel_booking_flow` 同步断言）
- [x] **BOOK-10** 数据库 `bookings.booking_details`（JSONB）在成功持久化后非空且含关键字段（**不**要求当前公开 REST 响应体包含该字段，除非产品扩展 `BookingResponse`）（`test_conversations.py`：`test_persist_booking_stores_booking_details`）

---

## 4. Agent 工具 (P0)

### 4.1 search_hotels

- [x] **TOOL-01** 正常搜索，返回格式化的酒店列表（含 rate_plan_code）
- [x] **TOOL-02** SOAPTimeoutError，返回服务不可用提示
- [x] **TOOL-03** RoomUnavailableError，返回房间不可用提示
- [x] **TOOL-04** NoResultsError，返回无结果提示
- [x] **TOOL-05** 未知异常，向上抛出（不吞掉）

### 4.2 check_availability

- [x] **TOOL-06** 有效 rate_plan_code，返回 available + price（`test_tools.py`：`test_check_availability_valid_rate_plan_returns_price`）
- [x] **TOOL-07** 无效 rate_plan_code，抛 RoomUnavailableError → 返回错误提示（`test_check_availability_invalid_code_room_unavailable_message`）
- [x] **TOOL-08** SOAPTimeoutError 处理（`test_check_availability_soap_timeout`）

### 4.3 get_booking_rules

- [x] **TOOL-09** 有效 rate_plan_code，返回 cancellation_policy + price（`test_tools.py`：`test_get_booking_rules_valid_rate_plan_returns_policy_and_price`）
- [x] **TOOL-10** 无效 rate_plan_code，抛 RoomUnavailableError → 返回错误提示（`test_get_booking_rules_invalid_code_room_unavailable_message`）

### 4.4 book_hotel

- [x] **TOOL-11** 正常预定，返回确认信息 + `__BOOKING_DATA__` 嵌入数据
- [x] **TOOL-12** 验证 `__BOOKING_DATA__` JSON 结构完整（含 __booking__, booking_id, hotel_name, check_in, check_out, total_price, currency, status, rate_plan_code, guest_name, guest_email）（当前断言含 `__BOOKING_DATA__` 块与关键展示字段；未逐项 JSON 解析校验）
- [x] **TOOL-13** check_in 和 check_out 正确透传到 mock client（`test_book_hotel_passes_check_in_and_check_out_to_client` 断言 `hotel_booking` kwargs）
- [x] **TOOL-14** RoomUnavailableError 处理
- [x] **TOOL-15** PriceChangedError 处理，返回新旧价格
- [x] **TOOL-16** SOAPTimeoutError 处理
- [x] **TOOL-17** BookingPendingError 处理（`test_book_hotel_booking_pending`）
- [x] **TOOL-18** 未知异常向上抛出

### 4.5 read_booking

- [x] **TOOL-19** 存在的 booking_id，返回预定详情（`test_read_booking_returns_details_when_found`，mock `async_session` + 行命中）
- [x] **TOOL-20** 不存在的 booking_id，在当前本地 DB 语义下返回「未找到或无权限」文案（不要求 supplier mock 的 status=not_found）（`test_read_booking_not_found_returns_local_message`）
- [x] **TOOL-21** ~~SOAPTimeoutError~~ → 改为 **DB 查询异常向上抛出**（`test_read_booking_db_error_propagates`；工具无 SOAP 路径）

### 4.6 list_bookings

- [x] **TOOL-22** 有预定时，返回格式化列表（`test_list_bookings_formats_multiple_rows`）
- [x] **TOOL-23** 无预定时，返回 "No bookings found"（`test_list_bookings_empty_returns_message` → 与实现一致：`No bookings found. The user has no booking history.`）
- [x] **TOOL-24** 真实模式下仍应从本地 DB 返回预定列表（不依赖 supplier list_bookings）（`test_list_bookings_uses_local_db_query_not_supplier` 断言 SQL 含 `bookings.user_id` + `ORDER BY bookings.created_at DESC`）
- [x] **TOOL-25** ~~SOAPTimeoutError~~ → **DB 异常向上抛出**（`test_list_bookings_db_error_propagates`）

### 4.7 cancel_booking

- [x] **TOOL-26** 正常取消，返回 status=cancelled（含 `__BOOKING_EVENT__` / `booking.cancelled`）
- [x] **TOOL-27** 不存在的 booking_id，仍返回 cancelled（mock 行为）（`test_cancel_booking_unknown_id_mock_still_cancelled` + 真实 `MockJuniperClient`）
- [x] **TOOL-28** SOAPTimeoutError 处理（`test_cancel_booking_soap_timeout`）

### 4.8 modify_booking

- [x] **TOOL-29** 正常修改日期，返回更新后的详情（含 `__BOOKING_EVENT__` / `booking.modified`）
- [x] **TOOL-30** 不存在的 booking_id，返回 status=not_found（`test_modify_booking_unknown_id_returns_not_found` + `MockJuniperClient`）
- [x] **TOOL-31** 只传 new_check_in 不传 new_check_out，验证部分更新（`test_modify_booking_check_in_only_preserves_check_out`：先 `hotel_booking` 再仅改 `check_in`）
- [x] **TOOL-32** SOAPTimeoutError 处理（`test_modify_booking_soap_timeout`）

---

## 5. 预定持久化与幂等 (P0)

### 5.1 预定数据提取

- [x] **PERSIST-01** Agent 回复中包含 `__BOOKING_DATA__...json...__END_BOOKING_DATA__`，正确解析并持久化（`test_send_message_persists_when_agent_emits_booking_data_block`：`patch` `_persist_booking` 断言 kwargs）
- [x] **PERSIST-02** Agent 回复中无 booking 数据标记，不创建预定记录（`test_send_message_skips_persist_without_booking_markers`）
- [x] **PERSIST-03** 多条 tool 消息中包含多个 booking 数据，全部提取（`test_send_message_extracts_multiple_booking_blocks_from_tool_messages`：两条 `ToolMessage` → `_persist_booking` ×2）

### 5.2 幂等性

- [x] **PERSIST-04** 同一 conversation_id + juniper_booking_id 重复提交，只创建一条记录（`test_persist_booking_duplicate_same_conversation_and_juniper_id_skips_insert`）
- [x] **PERSIST-05** idempotency_key 格式为 `{conversation_id}:{juniper_booking_id}`（`test_persist_booking_idempotency_key_format`）
- [x] **PERSIST-06** 重复提交时日志记录 "Duplicate booking detected"（`test_persist_booking_duplicate_logs_skipping`）

### 5.3 Webhook 触发

- [x] **PERSIST-07** 预定持久化成功后，触发 `booking.confirmed` webhook（`test_persist_booking_dispatches_booking_confirmed_webhook`：`patch` `dispatch_event` 断言 `event_type` / `booking_id` / `booking_details`）
- [x] **PERSIST-08** Webhook 分发失败不影响预定响应（异常被捕获）（`test_persist_booking_dispatch_failure_does_not_raise`：`dispatch_event` 抛错 + `logger.error` + 不向外抛）

> **注**：**PERSIST-01～08** 均已通过 `test_conversations.py` 覆盖（含 `_persist_booking` 对 `dispatch_event` 的调用与失败分支）。

---

## 6. 用户偏好 API (P1)

### 6.1 获取偏好

- [x] **PREF-01** 获取自己的偏好，返回 200
- [x] **PREF-02** 获取其他用户的偏好，返回 403
- [x] **PREF-04** 用户无偏好设置，返回空 preferences 对象（`test_get_preferences_empty_when_none_or_empty_dict`：`user.preferences` 为 `None` 或 `{}`）

### 6.2 更新偏好

- [x] **PREF-05** 更新自己的偏好，返回 200 + 更新后的偏好
- [x] **PREF-06** 偏好合并逻辑：新值覆盖旧值，未传字段保留原值（`test_put_preferences_merge_preserves_unsent_fields`）
- [x] **PREF-07** 更新其他用户的偏好，返回 403
- [x] **PREF-08** 所有可选字段：star_rating, location_preference, board_type, smoking, floor_preference, budget_range（`test_put_preferences_all_optional_fields`）

---

## 7. Webhook 管理 (P1)

### 7.1 注册 Webhook

- [x] **WH-01** 有效 HTTPS URL + 有效事件类型 + secret >= 16 字符，返回 201
- [x] **WH-02** HTTP URL（非 HTTPS），返回 400
- [x] **WH-03** URL 指向 localhost/127.0.0.1/::1，返回 400 (SSRF 防护)
- [x] **WH-04** URL 指向私有 IP (10.x, 172.16.x, 192.168.x)，返回 400
- [x] **WH-05** 无效事件类型（非 booking.confirmed/cancelled/modified），返回 400（`test_register_webhook_invalid_event_returns_400`）
- [x] **WH-06** secret 长度 < 16 字符，返回 400（`test_register_webhook_short_secret_returns_400`）

### 7.2 列出 Webhook

- [ ] **WH-07** 返回所有注册的 webhook，按 created_at DESC 排序
- [ ] **WH-08** 无注册 webhook 时，返回空列表

### 7.3 删除 Webhook

- [ ] **WH-09** 删除存在的 webhook，返回 `{status: "deleted"}`
- [ ] **WH-10** 删除不存在的 webhook，返回 404

### 7.4 权限

- [ ] **WH-11** JWT 认证调用 webhook 端点，返回 403
- [ ] **WH-12** API Key 认证调用 webhook 端点，正常工作

---

## 8. Webhook 分发与重试 (P1)

### 8.1 分发

- [ ] **DISPATCH-01** 有匹配事件订阅的 webhook，收到 POST 请求
- [ ] **DISPATCH-02** 请求包含 `X-Webhook-Signature: sha256=<hmac>` 签名头
- [ ] **DISPATCH-03** 请求包含 `X-Event-Type` 头
- [ ] **DISPATCH-04** 无匹配事件的 webhook，不触发分发

### 8.2 重试

- [ ] **DISPATCH-05** 首次失败后，按 [30s, 60s, 120s] 间隔重试
- [ ] **DISPATCH-06** 重试成功，failure_count 重置为 0
- [ ] **DISPATCH-07** 连续 3 次失败，webhook 被停用 (active=False)
- [ ] **DISPATCH-08** 请求超时（10s），视为失败

---

## 9. 限流 (P1)

- [x] **RATE-01** JWT 用户在限额内请求正常通过
- [x] **RATE-02** JWT 用户超出限额（默认 60/min），返回 429 + Retry-After 头（当前用例断言 429 与文案；**未**断言 `Retry-After` 头，见 RATE-06）
- [x] **RATE-03** API Key 用户使用更高限额（默认 300/min）
- [x] **RATE-04** 窗口过期后，限额重置
- [x] **RATE-05** 不同用户限额独立计算（`test_rate_limits_are_independent_per_user`）
- [x] **RATE-06** 429 响应包含 `Retry-After` 头（秒数）（`test_requests_exceeding_limit_return_429` 中断言 `Retry-After` 为合法整数秒）

---

## 10. Agent 对话流 E2E (P1)

> 端到端测试：通过 API 发送用户消息，验证完整的 Agent 对话流程。依赖真实 LLM 时断言宜宽松（或改用固定 mock LLM / 记录 tool_calls），否则 CI 易抖动；可单独标为「夜间 / 手动回归」。

### 10.1 搜索流程

- [ ] **E2E-01** 用户发送 "帮我找巴塞罗那的酒店，明天入住后天退房" → Agent 调用 search_hotels → 返回酒店列表
- [ ] **E2E-02** 用户发送 "五星酒店" → Agent 过滤并只展示五星酒店
- [ ] **E2E-03** 相对日期解析：明天、后天、大后天、下周 → 正确转换为绝对日期

### 10.2 预定流程

- [ ] **E2E-04** 用户选择酒店编号 → Agent 调用 check_availability + get_booking_rules → 展示价格和政策
- [ ] **E2E-05** 用户确认 + 提供姓名邮箱 → Agent 调用 book_hotel → 返回预定确认
- [ ] **E2E-06** 预定确认中日期正确（不使用默认值）
- [ ] **E2E-07** 预定完成后，DB 中 Booking 记录正确创建

### 10.3 预定管理流程

- [ ] **E2E-08** 用户说 "查看我的预定" → Agent 调用 list_bookings → 返回预定列表
- [ ] **E2E-09** 用户说 "取消预定 JNP-XXXXXXXX" → Agent 调用 cancel_booking → 确认取消
- [ ] **E2E-10** 用户说 "修改预定日期" → Agent 调用 modify_booking → 确认修改

---

## 11. 前端 API 集成 (P2)

- [ ] **FE-01** 前端创建对话 → 后端返回 conversation_id
- [ ] **FE-02** 前端发送消息 → 后端返回 AI 回复
- [ ] **FE-03** 前端重置对话 → 新建 conversation
- [ ] **FE-04** 后端不可用时 → 前端展示错误提示
- [ ] **FE-05** Vite 代理正确转发 `/api` 请求到后端
- [ ] **FE-06** 消息时间戳正确显示

---

## 12. Mock 数据一致性 (P2)

> 本节断言针对 **`juniper/mock_client.py` 中 `MockJuniperClient`** 的行为；与 Agent 工具 `read_booking` / `list_bookings`（读本地 DB）无直接对应关系，勿混测。

- [ ] **MOCK-01** 5 家 mock 酒店数据完整（hotel_code, name, category, address, city, rate_plan_code, total_price, currency, board_type, room_type, cancellation_policy）
- [x] **MOCK-02** 搜索 "Barcelona" 返回 5 家酒店（`test_mock_client`：`hotel_avail` Barcelona 条数与字段）
- [x] **MOCK-03** 搜索未知城市，返回全部 5 家（fallback）
- [ ] **MOCK-04** hotel_check_avail 对 5 个有效 rate_plan_code 均返回 available=True（当前仅覆盖单个有效 code）
- [x] **MOCK-05** hotel_booking 生成的 booking_id 格式为 `JNP-{8位大写字母数字}`（与 **BOOK-09** 同测：`test_hotel_booking_id_matches_jnp_format`）
- [ ] **MOCK-06** list_bookings 返回 MOCK_BOOKINGS 中所有记录
- [x] **MOCK-07** `MockJuniperClient.cancel_booking` 后，**同一 mock** 上 `read_booking` 得到 `status=cancelled`
- [x] **MOCK-08** `MockJuniperClient.modify_booking` 后，**同一 mock** 上 `read_booking` 日期已更新

---

## 13. 用户画像与预定策略 (P1)

> 不同类型用户有不同的预定需求和决策路径，Agent 应根据用户偏好和对话上下文提供差异化服务。本节以 **LLM 行为**为主，适合 eval / 抽检或与 mock LLM 结合；不宜全部作为硬编码字符串的阻塞 CI 断言。

### 13.1 商务出差用户

- [ ] **PERSONA-01** 用户说 "我出差去巴塞罗那，需要一间商务酒店" → Agent 搜索并优先推荐 4-5 星酒店
- [ ] **PERSONA-02** 用户设置偏好 `star_rating: "4 stars"`, `board_type: "Bed & Breakfast"` → 搜索结果优先展示匹配项
- [ ] **PERSONA-03** 用户说 "公司报销上限每晚 250 欧" → Agent 只推荐 ≤250 EUR 的酒店（NH 180€, Eurostars 220€）
- [ ] **PERSONA-04** 快速预定路径：商务用户提供完整信息（目的地+日期+姓名+邮箱）→ 3 轮内完成预定

### 13.2 家庭旅游用户

- [ ] **PERSONA-05** 用户说 "带两个孩子去巴塞罗那度假" → Agent 询问儿童数量和年龄，search_hotels 传入 children 参数
- [ ] **PERSONA-06** 用户偏好 `board_type: "Full Board"` → Agent 优先推荐 Mandarin Oriental（全膳 FB）
- [ ] **PERSONA-07** 用户关注取消政策 "可以免费取消吗" → Agent 展示各酒店取消政策对比
- [ ] **PERSONA-08** 用户说 "预算有限，3000 欧以内住 5 晚" → Agent 推荐 Continental（95€/晚）或 NH（180€/晚）

### 13.3 背包客 / 预算用户

- [ ] **PERSONA-09** 用户说 "找最便宜的酒店" → Agent 推荐 Hotel Continental Barcelona（95€/晚，3 星）
- [ ] **PERSONA-10** 用户设置偏好 `budget_range: "€50-100/night"` → 搜索结果中只有 Continental 匹配
- [ ] **PERSONA-11** 用户说 "不需要早餐，只要房间" → Agent 推荐 Room Only 类型（Eurostars，RO）

### 13.4 高端客户

- [ ] **PERSONA-12** 用户说 "最好的五星酒店，不在乎价格" → Agent 推荐 Mandarin Oriental（520€/晚）
- [ ] **PERSONA-13** 用户设置偏好 `star_rating: "5 stars"`, `board_type: "Full Board"` → 直接匹配 Mandarin Oriental
- [ ] **PERSONA-14** 用户说 "帮我定最贵的那个" → Agent 识别 Mandarin Oriental 并进入预定流程

### 13.5 多次预定用户

- [ ] **PERSONA-15** 同一用户在一个对话中连续预定两家不同酒店 → 两条 Booking 记录正确创建
- [ ] **PERSONA-16** 用户完成预定后说 "再帮我找一家便宜点的" → Agent 重新搜索，不影响已有预定
- [ ] **PERSONA-17** 用户预定后立即查询 "我的预定记录" → list_bookings 返回刚创建的预定

### 13.6 犹豫型用户

- [ ] **PERSONA-18** 用户反复切换酒店选择（先选1号再选3号再回到1号）→ Agent 正确跟踪最新选择
- [ ] **PERSONA-19** 用户在确认预定前说 "我再想想" → Agent 不执行预定，保留上下文
- [ ] **PERSONA-20** 用户在提供姓名后说 "算了不订了" → Agent 取消流程，回到 idle 状态

---

## 14. 时间维度与日期处理 (P1)

> Agent 需要正确处理各种日期格式和相对时间表达，并对无效日期做出合理反应。

### 14.1 相对日期解析

- [ ] **TIME-01** "明天入住后天退房"（E2E）→ Agent 最终调用工具时传入合法 YYYY-MM-DD，且 check_out > check_in
- [ ] **TIME-02** "大后天入住，住3晚"（E2E）→ Agent 最终调用工具时传入合法 YYYY-MM-DD，且 stay_nights=3
- [ ] **TIME-03** "下周一入住，下周五退房"（E2E）→ Agent 最终调用工具时传入合法 YYYY-MM-DD，并满足时间顺序
- [ ] **TIME-04** "这个周末"（E2E）→ Agent 能补全具体日期后再调用工具（不接受空日期）
- [ ] **TIME-05** "下个月15号到18号"（E2E）→ Agent 最终调用工具时传入合法 YYYY-MM-DD

### 14.2 绝对日期格式

- [ ] **TIME-06** ISO 格式 "2026-04-15 到 2026-04-18"（工具层）→ `validate_dates` 通过并可执行搜索/预定
- [ ] **TIME-07** 中文格式 "2026年4月15日到18日"（E2E）→ Agent 转换为 YYYY-MM-DD 后再调用工具
- [ ] **TIME-08** 斜杠格式 "4/15 到 4/18"（E2E）→ Agent 转换为 YYYY-MM-DD 后再调用工具
- [ ] **TIME-09** 混合格式 "明天到 2026-04-10"（E2E）→ 若存在矛盾，Agent 追问确认，不直接下单

### 14.3 无效日期处理

- [ ] **TIME-10** 过去日期 "昨天入住"（工具层）→ `validate_dates` 返回 in the past 错误
- [ ] **TIME-11** 退房早于入住 "4月18日入住4月15日退房"（工具层）→ `validate_dates` 返回顺序错误
- [ ] **TIME-12** 入住和退房同一天（工具层）→ `validate_dates` 判定 `check_out <= check_in`，返回「退房必须晚于入住」类错误（与实现一致，不要求单独文案「至少住一晚」）
- [ ] **TIME-13** 只提供入住不提供退房 → Agent 追问退房日期
- [ ] **TIME-14** 只提供退房不提供入住 → Agent 追问入住日期

---

## 15. 酒店筛选与推荐策略 (P1)

> 验证 Agent 对酒店搜索结果的筛选、排序和推荐逻辑。实现上部分能力依赖 `search_hotels` 参数（如 `star_rating`）及模型是否传入；断言优先检查 **工具入参** 或 **mock supplier 返回值**，而非仅检查自然语言全文。

### 15.1 按星级筛选

- [ ] **FILTER-01** "五星酒店" → 只展示 Eurostars(5★), Arts(5★), Mandarin(5★)
- [ ] **FILTER-02** "四星或以上" → 展示 NH(4★), Eurostars(5★), Arts(5★), Mandarin(5★)
- [ ] **FILTER-03** "三星酒店" → 只展示 Continental(3★)
- [ ] **FILTER-04** 不指定星级 → 展示全部 5 家

### 15.2 按价格筛选

- [ ] **FILTER-05** "200 欧以内" → 展示 Continental(95€), NH(180€)
- [ ] **FILTER-06** "200-400 欧之间" → 展示 Eurostars(220€), Arts(350€)
- [ ] **FILTER-07** "最便宜的" → 首推 Continental(95€)
- [ ] **FILTER-08** "最贵的" → 首推 Mandarin(520€)

### 15.3 按餐食类型筛选

- [ ] **FILTER-09** "含早餐" → 展示 NH(BB), Continental(BB)
- [ ] **FILTER-10** "全膳/包三餐" → 展示 Mandarin(FB)
- [ ] **FILTER-11** "半膳" → 展示 Arts(HB)
- [ ] **FILTER-12** "不含餐/只要房间" → 展示 Eurostars(RO)

### 15.4 偏好驱动推荐

- [ ] **FILTER-13** 用户偏好 `star_rating: "5 stars"` 已保存 → 搜索时 Agent 提及并优先展示五星酒店
- [ ] **FILTER-14** 用户偏好 `budget_range: "€100-200/night"` → Agent 搜索后标注哪些在预算范围内
- [ ] **FILTER-15** 用户偏好与当前请求冲突（偏好五星但说"找便宜的"）→ Agent 以当前请求为准
- [ ] **FILTER-16** 用户无偏好设置 → Agent 展示全部结果，不做预筛选

---

## 16. 多用户并发与隔离 (P1)

> 验证多用户同时使用系统时的数据隔离和并发安全。

### 16.1 数据隔离

- [ ] **MULTI-01** 用户 A 和用户 B 同时搜索酒店 → 各自独立的对话和结果
- [ ] **MULTI-02** 用户 A 预定酒店后，用户 B 调用 list_bookings → B 看不到 A 的预定
- [ ] **MULTI-03** 用户 A 的 conversation_id 被用户 B 使用 → 返回 404
- [x] **MULTI-04** 用户 A 的 booking_id 被用户 B 查询 → 返回 404（与 **AUTH-12** 同测：`test_get_booking_other_user_returns_404`）

### 16.2 并发预定

- [ ] **MULTI-05** 用户 A 和用户 B 同时预定同一家酒店（同 rate_plan_code）→ 各自获得独立的 booking_id
- [ ] **MULTI-06** 同一用户在两个不同对话中同时预定 → 两条独立的预定记录（不同 idempotency_key）
- [ ] **MULTI-07** 同一 `conversation_id` 下，仅当**再次出现相同 `juniper_booking_id`** 的 `__BOOKING_DATA__` 解析时不重复插入；若每次下单生成新的 `juniper_booking_id`，则会出现多条记录（属预期，除非产品引入 client 侧幂等键）
- [ ] **MULTI-08** 高并发场景：10 个用户同时发起预定 → 所有请求正确处理，无数据串扰

---

## 执行说明

### 测试环境

- Python 3.12 + pytest + pytest-asyncio
- PostgreSQL（Docker：`localhost:5433`）
- Mock 模式（`JUNIPER_USE_MOCK=true`）
- 测试 API Key：`test-api-key-1`

### 执行命令

> **注意**：请在 shell 中**单独**执行下列命令。不要把中文说明或 `→` 等符号与命令写在同一行，否则 pytest 会把多余参数当成路径而报错（例如 `ERROR: file or directory not found: →`）。

```bash
# 运行全部测试
python -m pytest tests/ -v

# 按模块运行
python -m pytest tests/test_api/ -v          # API 测试
python -m pytest tests/test_agent/ -v        # Agent 工具测试
python -m pytest tests/test_juniper/ -v      # Mock 客户端测试
python -m pytest tests/test_security/ -v     # 安全测试

# 按标记运行（待添加 marker）
python -m pytest -m "p0" -v                  # 仅 P0 用例
python -m pytest -m "e2e" -v                 # 端到端测试
```

### 优先级定义

| 优先级 | 含义 | 阻断发布 |
|--------|------|---------|
| P0 | 核心功能，必须通过 | 是 |
| P1 | 重要功能，应该通过 | 视情况 |
| P2 | 辅助功能，建议通过 | 否 |
