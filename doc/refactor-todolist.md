# Juniper 集成层重构 TodoList

> 创建日期: 2026-04-03
> 目标: 让项目的 Juniper 集成层与真实 SOAP API 规范完全对齐

---

## 问题严重度分布

- CRITICAL: 1 个 (mock 内存存储)
- HIGH: 12 个 (缺静态数据、目的地用文本、BookingCode 过期、修改流程错误等)
- MEDIUM: 3 个 (熔断器未接入、幂等处理、取消费查询)

---

## Phase 1: 静态数据层（Week 1）

> 所有后续工作的前提。建立本地缓存，让搜索用 zone code 而不是文本。

### 1.1 新增数据库模型

- [x] `zones` 表 — 目的地缓存（id, jpdcode, code, name, area_type, searchable, parent_jpdcode）
- [x] `hotels` 表 — 酒店缓存（id, jp_code, name, zone_jpdcode, category_type, address, lat, lon）
- [x] `hotel_content_cache` 表 — 酒店详情缓存（jp_code, name, images, descriptions, features, check_in_time, check_out_time）
- [x] `currencies` 表 — 货币列表（code, name）
- [x] `countries` 表 — 国家列表（code, name）
- [x] `board_types` 表 — 餐食类型映射（code, name），如 AD=含早, MP=半膳
- [x] `hotel_categories` 表 — 星级映射（type, name），如 5est=五星
- [x] 创建 Alembic 迁移文件
- [x] 所有缓存表加 `synced_at` 时间戳字段，用于判断是否需要更新

**改动文件:** `juniper_ai/app/db/models.py`, 新增迁移

### 1.2 新增静态数据同步服务

- [x] 新建 `juniper_ai/app/juniper/static_data.py`
  - [x] `sync_zones()` — 调 ZoneList(ProductType=HOT)，写入 zones 表
  - [x] `sync_hotels()` — 调 HotelPortfolio（分页，每页 500），写入 hotels 表
  - [x] `sync_catalogue()` — 调 GenericDataCatalogue(CURRENCY/COUNTRIES) + HotelCatalogueData
  - [x] `get_zone_code(destination_text)` — 文本模糊匹配 zones 表 → 返回 zone code
  - [x] `get_hotel_by_jpcode(jp_code)` — 查本地缓存获取酒店信息
- [x] 新建 `juniper_ai/app/tasks/sync_static_data.py`
  - [x] 定时同步任务（建议每 15 天，符合 Juniper 认证要求）
  - [x] 首次启动时自动执行全量同步
  - [ ] 支持增量更新（HotelPortfolio 的 ModificationDate 参数）
- [x] `juniper_ai/app/config.py` 新增配置项
  - [x] `static_data_sync_interval_days: int = 15`
  - [x] `hotel_portfolio_page_size: int = 500`

### 1.3 修改 supplier 接口

- [x] `juniper_ai/app/juniper/supplier.py` ��增抽象方法:
  - [x] `zone_list(product_type: str = "HOT") -> list[dict]`
  - [x] `hotel_portfolio(page_token: str | None = None) -> dict`
  - [x] `hotel_content(hotel_codes: list[str]) -> list[dict]`
  - [x] `generic_data_catalogue(catalogue_type: str) -> list[dict]`
  - [x] `hotel_catalogue_data() -> dict`
- [x] `hotel_avail()` 签名修改: `destination: str` → `zone_code: str`
- [x] `juniper_ai/app/juniper/client.py` 实现新增方法的 SOAP 调用
- [x] `juniper_ai/app/juniper/mock_client.py` 实现新增方法的 mock ���本

### 1.4 测试验证

- [x] 单元测试: zone code ��本模糊匹配
- [x] 单元��试: 静态��据同步写入 DB
- [x] ���成测试: 从文本 "Barcelona" → zone code → hotel_avail ���用

---

## Phase 2: 核心预订流程修正（Week 2）

> 让 Availability → Valuation → Booking 流程与真实 API 完全对齐。

### 2.1 搜索工具改造

- [x] `juniper_ai/app/agent/tools/search_hotels.py` 修改:
  - [x] 用 destination 文本查 zones 表 → 得到 zone_code (Phase 1 完成)
  - [x] 模糊匹配失败时返回候选列表让用户选择 (Phase 1 完成)
  - [x] 传入 `country_of_residence` 参数
  - [x] 结果中包含 JPCode 和 zone 信息

### 2.2 BookingRules 增加 BookingCode 跟踪

- [x] `juniper_ai/app/juniper/serializers.py` 修改:
  - [x] `serialize_booking_rules()` 提取 `BookingCode` 值
  - [x] 提取 `BookingCode/@ExpirationDate` 过期时间
- [x] `juniper_ai/app/agent/tools/booking_rules.py` 修改:
  - [x] 返回值包含 `booking_code` 和 `expires_at`
  - [x] 在工具输出中标注过期时间，提示用户尽快确认
- [x] `juniper_ai/app/db/models.py` Booking 模型新增字段:
  - [x] `booking_code: String` — BookingRules 返回的 BookingCode
  - [x] `booking_code_expires_at: DateTime` — BookingCode 过期时间
  - [x] `country_of_residence: String(2)` — 国籍代码
  - [x] `rate_plan_code: String` — 使用的 RatePlanCode
  - [x] `external_booking_reference: String` — 超时恢复用
- [x] 新增 Alembic 迁移

### 2.3 预订确认增加校验

- [x] `juniper_ai/app/agent/tools/book_hotel.py` 修改:
  - [x] 检查 BookingCode 是否过期，过期则提示用户重新调 BookingRules
  - [x] 传入 CountryOfResidence
  - [x] 构建完整 Pax 对象（first_name, surname 拆分）
  - [x] 设置 ExternalBookingReference 用于超时恢复
  - [x] 在 `__BOOKING_DATA__` 中包含 rate_plan_code 和 country_of_residence

### 2.4 真实 SOAP Client 修正

- [x] `juniper_ai/app/juniper/client.py` 修改:
  - [x] `hotel_avail()`: `"DestinationZone": zone_code` (Phase 1 完成)
  - [x] `hotel_avail()`: 构建完整 Pax（IdPax, Age）(Phase 1 完成)
  - [x] `hotel_avail()`: 添加 `CountryOfResidence` 参数 (Phase 1 完成)
  - [x] `hotel_booking_rules()`: 通过 serializer 提取 BookingCode + ExpirationDate
  - [x] `hotel_booking()`: 添加 CountryOfResidence
  - [x] `hotel_booking()`: 构建完整 Pax + Holder（IdPax, Name, Surname, Nationality）
  - [x] `hotel_booking()`: 使用 BookingCode 优先于 RatePlanCode
  - [x] `hotel_booking()`: 添加 ExternalBookingReference 参数
  - [x] 所有请求添加 HTTP 头: `Accept-Encoding: gzip`, `Content-Type: text/xml;charset=UTF-8`

### 2.5 Mock Client 更新

- [x] `hotel_booking_rules()` 返回 booking_code + expires_at
- [x] `hotel_booking()` 传递 country_of_residence + external_booking_reference
- [ ] 完全切换为 DB 存储（MOCK_BOOKINGS 保留为测试兼容，预订已通过 conversation handler 持久化到 DB）

### 2.6 测试验证

- [x] 更新 search_hotels 测试适配 zone_code + get_zone_code mock
- [x] 新增测试: BookingCode 过期 → 返回错误提示
- [x] 新增测试: BookingCode 未过期 → 正常预订 + country_of_residence 在 booking_data 中
- [x] 新增测试: BookingCode + ExternalBookingReference 传递到 client
- [x] 新增测试: booking_rules 返回 BookingCode 和过期时间
- [x] 全部 150 测试通过

---

## Phase 3: 修改/取消流程完善（Week 3）

> 实现 Juniper 要求的两步修改流程，补齐取消费用查询。

### 3.1 两步修改流程

- [ ] `juniper_ai/app/juniper/supplier.py` 新增方法:
  - [ ] `hotel_modify(booking_id, **modifications) -> dict` — Step 1: 获取修改方案 + ModifyCode
  - [ ] `hotel_confirm_modify(modify_code) -> dict` — Step 2: 确认修改
- [ ] `juniper_ai/app/juniper/client.py` 实现:
  - [ ] `hotel_modify()` — 调 HotelModify SOAP 操作
  - [ ] `hotel_confirm_modify()` — 调 HotelConfirmModify SOAP 操作
  - [ ] 删除当前错误的 `modify_booking()` 实现（调的是不存在的 HotelBookingModification）
- [ ] `juniper_ai/app/juniper/mock_client.py` 实现 mock 版本
- [ ] `juniper_ai/app/agent/tools/modify_booking.py` 重写:
  - [ ] Step 1: 调 `hotel_modify()` → 返回可选方案给用户
  - [ ] 在工具输出中展示修改方案（新价格、新取消政策等）
- [ ] 新建 `juniper_ai/app/agent/tools/confirm_modify.py`:
  - [ ] Step 2: 用户确认后调 `hotel_confirm_modify(modify_code)`
  - [ ] 更新本地 bookings 表
  - [ ] 嵌入 `__BOOKING_EVENT__` 标记触发 webhook
- [ ] `juniper_ai/app/agent/graph.py` — 注册新工具 `confirm_modify`

### 3.2 取消费用查询

- [ ] 新建 `juniper_ai/app/agent/tools/cancel_estimate.py`:
  - [ ] 调 `cancel_booking(OnlyCancellationFees=true)` — 仅查费用不实际取消
  - [ ] 返回取消费用金额和货币
- [ ] `juniper_ai/app/juniper/supplier.py` 修改:
  - [ ] `cancel_booking()` 新增 `only_fees: bool = False` 参数
- [ ] `juniper_ai/app/juniper/client.py` 修改:
  - [ ] 支持 `OnlyCancellationFees="true"` 参数
  - [ ] 解析 CancelInfo 响应（BookingCancelCost, BookingCancelCostCurrency）
- [ ] `juniper_ai/app/agent/tools/cancel_booking.py` 修改:
  - [ ] 取消前先自动调 cancel_estimate 展示费用
  - [ ] 正确处理 Warning 代码（warnCancelledAndCancellationCostRetrieved 等）
- [ ] `juniper_ai/app/agent/graph.py` — 注册新工具 `cancel_estimate`
- [ ] 更新 system prompt — 指导 agent 取消前先查费用

### 3.3 测试验证

- [ ] 新增测试: 两步修改流程（modify → confirm）
- [ ] 新增测试: 取消费用查询（OnlyCancellationFees=true）
- [ ] 新增测试: 取消 Warning 代码处理
- [ ] 更新现有 modify_booking 测试

---

## Phase 4: 健壮性增强（Week 4）

> 熔断器接入、幂等处理、错误恢复。

### 4.1 接入熔断器

- [ ] `juniper_ai/app/juniper/client.py` 修改:
  - [ ] 导入 `CircuitBreaker`（当前文件已存在但从未被使用）
  - [ ] 创建 `juniper_breaker` 实例
  - [ ] `_call_with_retry()` 开头调 `juniper_breaker.check()`
  - [ ] 成功时调 `juniper_breaker.record_success()`
  - [ ] 失败时调 `juniper_breaker.record_failure()`
  - [ ] 熔断时返回友好错误信息
- [ ] 暴露熔断器状态到 `/metrics` 端点
- [ ] 熔断器状态变化时记录日志

### 4.2 预订幂等处理

- [ ] `juniper_ai/app/agent/tools/book_hotel.py` 修改:
  - [ ] 预订前生成 `ExternalBookingReference`（UUID）
  - [ ] 先写入 Booking 表（status=pending）
  - [ ] 调 HotelBooking(ExternalBookingReference=ref)
  - [ ] 成功 → 更新 status=confirmed + 写入 juniper_booking_id
  - [ ] 超时 → 等待 180 秒后调 BookingList(ExternalBookingReference=ref) 恢复
  - [ ] 重试 → 检查 idempotency_key 避免重复提交
- [ ] `juniper_ai/app/juniper/client.py` 修改:
  - [ ] `hotel_booking()` 接受 `external_reference` 参数
  - [ ] 新增 `booking_list(external_reference)` 方法用于超时恢复
- [ ] 利用已有的 `BookingPendingError` 异常（当前定义了但从未使用）

### 4.3 超时与错误恢复

- [ ] Agent 调用添加 `asyncio.wait_for()` 超时包装
- [ ] Booking 超时后的恢复流程（BookingList 查询）
- [ ] 所有 SOAP 调用添加请求 ID 用于日志追踪
- [ ] Warning 代码统一处理（warnPriceChanged, warnStatusChanged 等）

### 4.4 测试验证

- [ ] 新增测试: 熔断器状态转换（closed → open → half-open → closed）
- [ ] 新增测试: 预订幂等（重复提交同一 idempotency_key）
- [ ] 新增测试: 预订超时恢复（BookingList 查询）
- [ ] 全量回归测试: 所有现有测试通过

---

## 文件变动汇总

### 新增文件

| 文件 | 说明 | Phase |
|------|------|-------|
| `juniper_ai/app/juniper/static_data.py` | 静态数据 SOAP 调用 + 本地缓存 | 1 |
| `juniper_ai/app/tasks/sync_static_data.py` | 定时同步任务 | 1 |
| `juniper_ai/app/agent/tools/confirm_modify.py` | 确认修改工具（两步修改 Step 2） | 3 |
| `juniper_ai/app/agent/tools/cancel_estimate.py` | 取消费用查询工具 | 3 |
| Alembic 迁移: 静态数据表 | 7 张新表 | 1 |
| Alembic 迁移: Booking 新字段 | booking_code, expires_at, country 等 | 2 |

### 重写文件

| 文件 | 说明 | Phase |
|------|------|-------|
| `juniper_ai/app/juniper/client.py` | 对齐真实 API 规范 | 2 |
| `juniper_ai/app/juniper/mock_client.py` | 改为查数据库 | 2 |
| `juniper_ai/app/agent/tools/modify_booking.py` | 两步修改流程 | 3 |

### 修改文件

| 文件 | 说明 | Phase |
|------|------|-------|
| `juniper_ai/app/juniper/supplier.py` | 新增 6 个方法，改 hotel_avail 签名 | 1 |
| `juniper_ai/app/juniper/serializers.py` | 提取 BookingCode / ExpirationDate | 2 |
| `juniper_ai/app/db/models.py` | 新增 7 个模型 + Booking 新字段 | 1+2 |
| `juniper_ai/app/agent/tools/search_hotels.py` | zone code 查找 + CountryOfResidence | 2 |
| `juniper_ai/app/agent/tools/book_hotel.py` | BookingCode 过期 + Pax + 幂等 | 2+4 |
| `juniper_ai/app/agent/tools/booking_rules.py` | 返回 BookingCode 过期时间 | 2 |
| `juniper_ai/app/agent/tools/cancel_booking.py` | Warning 处理 + 费用查询联动 | 3 |
| `juniper_ai/app/agent/graph.py` | 注册 confirm_modify + cancel_estimate | 3 |
| `juniper_ai/app/agent/prompts/system.py` | 更新预订流程指引 | 2 |
| `juniper_ai/app/config.py` | 新增静态数据同步配置 | 1 |
| `juniper_ai/app/juniper/exceptions.py` | 新增静态数据相关异常（如需要） | 1 |

### 测试文件

| 文件 | 说明 | Phase |
|------|------|-------|
| `tests/test_juniper/test_mock_client.py` | 适配新的 DB 模式 | 2 |
| `tests/test_juniper/test_static_data.py` | 新增: 静态数据同步测试 | 1 |
| `tests/test_agent/test_tools.py` | 更新 + 新增场景 | 2+3+4 |
| `tests/test_juniper/test_circuit_breaker.py` | 新增: 集成测试（当前只有单元测试） | 4 |

---

## 完成标准

### Phase 1 完成标准
- [ ] `python -c "from juniper_ai.app.juniper.static_data import get_zone_code; ..."` 能通过文本找到 zone code
- [ ] zones/hotels/currencies 表有数据
- [ ] 所有新增测试通过

### Phase 2 完成标准
- [ ] curl 完整预订流程跑通（search → check → rules → book）
- [ ] BookingCode 过期时 agent 自动重新获取
- [ ] Mock client 重启后预订数据不丢失
- [ ] 所有现有 + 新增测试通过

### Phase 3 完成标准
- [ ] 修改预订走两步流程（modify → 展示方案 → confirm）
- [ ] 取消前自动查询并展示取消费用
- [ ] 所有测试通过

### Phase 4 完成标准
- [ ] 熔断器正常工作（连续失败后自动断开，恢复后自动重连）
- [ ] 预订超时后能通过 BookingList 恢复
- [ ] 重复提交被幂等检查拦截
- [ ] 全量 133+ 测试通过
