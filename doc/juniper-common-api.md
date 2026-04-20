# Juniper Common API 参考文档

> 来源: https://api-edocs.ejuniper.com/en/api/genericworkflow
> 整理日期: 2026-04-03

## 目录

- [预订流程概览](#预订流程概览)
- [通用类型](#通用类型)
- [通用事务（Common Transactions）](#通用事务)
  - [GenericDataCatalogue](#genericdatacatalogue)
  - [ZoneList](#zonelist)
  - [CityList](#citylist)
  - [BookingList](#bookinglist)
  - [ReadBooking](#readbooking)
  - [CancelBooking](#cancelbooking)
  - [MeetingPointList](#meetingpointlist)
  - [FinalCustomerRead / FinalCustomerSave](#finalcustomerread--finalcustomersave)
  - [ShoppingBasketRead / ShoppingBasketSave](#shoppingbasketread--shoppingbasketsave)
  - [AgencyRead / CustomerRead / SupplierList](#agencyread--customerread--supplierlist)
- [与本项目的对照](#与本项目的对照)

---

## 预订流程概览

Juniper API 的预订流程分为 4 个步骤（+ 可选支付）：

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐    ┌──────────────┐
│ Step 1      │    │ Step 2       │    │ Step 3      │    │ Step 4       │
│ Static Data │───▶│ Availability │───▶│ Valuation   │───▶│ Booking      │
│             │    │              │    │             │    │              │
│ 静态数据获取  │    │ 可用性搜索    │    │ 估价确认     │    │ 预订确认     │
└─────────────┘    └──────────────┘    └─────────────┘    └──────┬───────┘
                                                                 │
                                                          ┌──────▼───────┐
                                                          │ Payment      │
                                                          │ (可选，取决于 │
                                                          │  账户类型)    │
                                                          └──────────────┘
```

### Step 1: Static Data（静态数据）

在执行预订流程之前，需要先获取基础数据：

- **国家代码**: 通过 `GenericDataCatalogue` 获取
- **目的地代码**: 通过 `ZoneList` 获取
- **酒店代码**: 通过各产品 API 的 Portfolio 接口获取
- **货币列表**: 通过 `GenericDataCatalogue` 获取

这些数据应**缓存到本地数据库**，每周更新。

### Step 2: Availability（可用性搜索）

搜索指定目的地、日期的可用酒店。响应中包含 **RatePlanCode**，这是一个唯一标识特定组合的编码，后续请求中会用到。

> 注意: RatePlanCode 可能非常长，存储时需要注意字段长度。

### Step 3: Valuation（估价确认）

选定组合后，需要验证其仍然有效：

- **CheckAvail**（可选）: 确认组合仍然可用，价格未变。如果有变化会返回新的 RatePlanCode。
- **BookingRules**（必须）: 确认组合可用，返回取消政策、必填字段等信息，以及 **BookingCode**。

> **BookingCode 有过期时间**（通过 `ExpirationDate` 属性标识）。如果在 BookingRules 和预订确认之间过期，需要重新调用 BookingRules。

### Step 4: Booking（预订确认）

使用 BookingRules 返回的 BookingCode，加上旅客信息，发送预订确认请求。响应返回 **@Locator**（预订编号），可用于后续的 ReadBooking 和 CancelBooking。

### Payment（支付，可选）

取决于账户配置：
- **信用/预付账户**: 预订直接确认，无需通过 API 支付
- **销售点账户**: 预订返回 QUO（报价）状态，需要通过 API 完成信用卡支付，支付成功后变为 PAG（已确认已支付）

---

## 通用类型

### 数据格式

| 格式 | 类型 | 说明 | 示例 |
|------|------|------|------|
| `[Text]` | String | 任意字符或数字 | `"Hello"` |
| `n[0..9]` | Integer | 整数 | `1`, `60`, `41050` |
| `n[0..9], 2[0..9]` | Double | 带小数的数字 | `1.00`, `100.02` |
| `true / false` | Boolean | 布尔值 | `true` |
| `yyyy-MM-ddThh:mm:ss` | DateTime | 日期时间 | `2026-04-03T10:30:00` |
| `hh:mm:ss` | Time | 时间 | `14:30:00` |
| `yyyy-MM-dd` | Date | 日期 | `2026-04-03` |

### 通用类型列表

- **Login** — 认证信息（Email + Password）
- **Errors** — 错误对象（Code + Text）
- **Warnings** — 警告对象（Code + Text）
- **Paxes** — 旅客信息
- **Prices** — 价格信息（含税、佣金、折扣明细）
- **CancellationPolicy** — 取消政策
- **Images** — 图片（BIG / THB / PAN）
- **Descriptions** — 描述（SHT / LNG / ROO 等）
- **AdditionalRequiredFields** — 预订时的额外必填字段

### Login

所有请求都需要包含认证信息：

| 属性 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `@Email` | 是 | String | Juniper 提供的邮箱 |
| `@Password` | 是 | String | Juniper 提供的密码 |

### Paxes（旅客信息）

| 属性 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `Pax/@IdPax` | 是 | Integer | 旅客 ID，从 1 开始递增 |
| `Pax/@Gender` | 否 | String | 性别: M(男) / F(女) |
| `Pax/Title` | 否 | String | 称谓: MR/MRS/MISS/MSTR |
| `Pax/Name` | 否 | String | 名 |
| `Pax/Surname` | 否 | String | 姓 |
| `Pax/Age` | 否 | Integer | 年龄（>18 为成人，空默认30岁） |
| `Pax/Email` | 否 | String | 邮箱 |
| `Pax/Document` | 否 | String | 证件号码 |
| `Pax/Document/@Type` | 否 | String | 证件类型: PAS/NIF/NIE/DNI/CIF/CPF |
| `Pax/BornDate` | 否 | Date | 出生日期 (yyyy-MM-dd) |
| `Pax/Nationality` | 否 | String | 国籍 (ISO-3166-1) |
| `Pax/PhoneNumbers/PhoneNumber` | 否 | String | 电话号码 |

```xml
<Pax IdPax="1" Gender="M">
  <Title>MR</Title>
  <Name>Test Name</Name>
  <Surname>Test Surname</Surname>
  <Age>30</Age>
  <Email>Noreply@ejuniper.com</Email>
  <Document Type="DNI" Country="ES">123456789</Document>
  <BornDate>1999-10-05</BornDate>
  <Nationality>ES</Nationality>
</Pax>
```

### Prices（价格对象）

| 属性 | 说明 |
|------|------|
| `Price/@Type` | S(销售价) / C(成本价) |
| `Price/@Currency` | 货币代码 |
| `TotalFixAmounts/@Gross` | 总价（含税、佣金、手续费），用于预订流程 |
| `TotalFixAmounts/@Nett` | 净价（不含佣金），用于支付 |
| `TotalFixAmounts/Service/@Amount` | 服务基础价 |
| `TotalFixAmounts/ServiceTaxes/@Amount` | 税额 |
| `TotalFixAmounts/Commissions/@Amount` | 佣金 |
| `TotalFixAmounts/HandlingFees/@Amount` | 手续费 |

### CancellationPolicy（取消政策）

| 属性 | 说明 |
|------|------|
| `@CurrencyCode` | 货币代码 |
| `FirstDayCostCancellation` | 开始产生取消费用的日期 |
| `PolicyRules/Rule/@DateFrom` | 规则生效起始日期 |
| `PolicyRules/Rule/@DateTo` | 规则生效结束日期 |
| `PolicyRules/Rule/@Type` | V(入住前) / R(确认后) / S(No Show) |
| `PolicyRules/Rule/@FixedPrice` | 固定取消费 |
| `PolicyRules/Rule/@PercentPrice` | 按比例取消费 |
| `PolicyRules/Rule/@Nights` | 罚款夜数 |

> 注意: 取消政策中的时间不保证是目的地时区，使用的是 Juniper 客户系统时区（可通过响应的 TimeStamp 确认）。

---

## 通用事务

### GenericDataCatalogue

获取通用数据目录（货币、国家、语言列表）。应缓存到本地数据库，每周更新。

#### 请求

| 属性 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `@Version` | 是 | String | API 版本 |
| `@Language` | 是 | String | 语言代码 |
| `{Login}` | 是 | - | 认证信息 |
| `GenericDataCatalogueRequest/@Type` | 是 | String | 目录类型: LANGUAGES / COUNTRIES / CURRENCY |

```xml
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns="http://www.juniper.es/webservice/2007/">
  <soapenv:Header/>
  <soapenv:Body>
    <GenericDataCatalogue>
      <GenericDataCatalogueRQ Version="1.1" Language="es">
        <Login Password="pass" Email="user@mydomain.com"/>
        <GenericDataCatalogueRequest Type="CURRENCY"/>
      </GenericDataCatalogueRQ>
    </GenericDataCatalogue>
  </soapenv:Body>
</soapenv:Envelope>
```

#### 响应

| 属性 | 说明 |
|------|------|
| `@Url` | API 端点 URL |
| `@TimeStamp` | 响应时间 (UTC) |
| `CatalogueItem/@Code` | 项目代码（如 EUR, USD） |
| `ItemContent/@Language` | 语言代码 |
| `ItemContent/Name` | 名称 |

```xml
<GenericDataCatalogue>
  <CatalogueItem Code="EUR">
    <ItemContentList>
      <ItemContent Language="EN"><Name>Euro</Name></ItemContent>
    </ItemContentList>
  </CatalogueItem>
  <CatalogueItem Code="USD">
    <ItemContentList>
      <ItemContent Language="EN"><Name>American Dollar</Name></ItemContent>
    </ItemContentList>
  </CatalogueItem>
</GenericDataCatalogue>
```

---

### ZoneList

获取指定产品的所有可用目的地代码。这些代码用于后续的可用性搜索。

**使用方式：**
- 指定 `@ProductType`: 返回该产品的可搜索目的地
- 不指定: 返回系统内所有目的地

应缓存到本地数据库。

#### 请求

| 属性 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `@Version` | 是 | String | API 版本 |
| `@Language` | 是 | String | 语言代码 |
| `{Login}` | 是 | - | 认证信息 |
| `ZoneListRequest/@ProductType` | 否 | String | 产品类型: HOT/CAR/TKT/TRF/FLH/INS/CRU/PCK |
| `ZoneListRequest/@ShowIATA` | 否 | Boolean | 是否返回 IATA 代码 |
| `ZoneListRequest/@MaxLevel` | 否 | Integer | 限制目的地层级深度 |

```xml
<ZoneList>
  <ZoneListRQ Version="1.1" Language="en">
    <Login Password="pass" Email="user@mydomain.com"/>
    <ZoneListRequest ProductType="HOT"/>
  </ZoneListRQ>
</ZoneList>
```

#### 响应

| 属性 | 说明 |
|------|------|
| `Zone/@JPDCode` | 共享目的地标识符（JPDXXXXXX 或 CUDXXXXXX） |
| `Zone/@ParentJPDCode` | 父级目的地代码 |
| `Zone/@AreaType` | 类型: CTY(城市)/REG(区域)/PAS(国家)/ARP(机场)等 |
| `Zone/@Searchable` | 是否可用于搜索 |
| `Zone/@Code` | 目的地代码 |
| `Zone/Name` | 目的地名称 |

```xml
<ZoneList>
  <Zone JPDCode="JPD054557" AreaType="CTY" Searchable="true" Code="15011">
    <Name>Palma de Mallorca</Name>
  </Zone>
  <Zone JPDCode="JPD036705" AreaType="REG" Searchable="true" Code="1953">
    <Name>Majorca</Name>
  </Zone>
  <Zone JPDCode="JPD034804" AreaType="PAS" Searchable="true" Code="118">
    <Name>Spain</Name>
  </Zone>
</ZoneList>
```

---

### CityList

获取所有可用城市代码（ZoneList 第 3 级目的地的简化版）。同时返回所属区域和国家。

> 注意: CityList 是 ZoneList 的重组版本，适合目的地结构类似的系统。完整目的地识别仍需使用 ZoneList。

#### 请求

```xml
<CityList>
  <CityListRQ Version="1.1" Language="en">
    <Login Password="pass" Email="user@mydomain.com"/>
  </CityListRQ>
</CityList>
```

#### 响应

```xml
<CityList>
  <City Id="1">
    <Name>Can Pastilla</Name>
    <Country Id="122"><Name>Spain</Name></Country>
    <Region Id="1964"><Name>Majorca</Name></Region>
  </City>
</CityList>
```

---

### BookingList

按日期范围批量查询已确认的预订。用于预订对账。

> 只返回 PAG 状态（已确认已支付）的预订。

#### 请求

| 属性 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `{Login}` | 是 | - | 认证信息 |
| `StartingBookingDate/@From, @To` | 否 | Date | 入住日期范围 |
| `EndingBookingDate/@From, @To` | 否 | Date | 退房日期范围 |
| `CancellationBookingDate/@From, @To` | 否 | Date | 取消日期范围 |
| `ModificationBookingDate/@From, @To` | 否 | Date | 修改日期范围 |
| `BookingDate/@From, @To` | 否 | Date | 创建日期范围 |
| `ExpirationBookingDate/@From, @To` | 否 | Date | 过期日期范围 |
| `ExternalBookingReference` | 否 | String | 外部预订参考号 |

> 至少需要一个日期过滤条件。

```xml
<BookingList>
  <BookingListRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <BookingListRequest>
      <StartingBookingDate From="2024-04-01" To="2024-04-30"/>
    </BookingListRequest>
  </BookingListRQ>
</BookingList>
```

#### 响应

```xml
<Reservations>
  <Reservation Locator="DN6X21">
    <BookingDate>2018-12-20</BookingDate>
  </Reservation>
  <Reservation Locator="5TGVOE">
    <BookingDate>2018-12-23</BookingDate>
  </Reservation>
</Reservations>
```

---

### ReadBooking

通过预订编号（@Locator）查询预订详情。

#### 请求

| 属性 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `{Login}` | 是 | - | 认证信息 |
| `ReadRequest/@ReservationLocator` | 是 | String | 预订编号 |
| `AdvancedOptions/ShowBreakdownPrice` | 否 | Boolean | 是否显示价格明细 |

```xml
<ReadBooking>
  <ReadRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <ReadRequest ReservationLocator="CSY243"/>
  </ReadRQ>
</ReadBooking>
```

#### 响应关键字段

| 属性 | 说明 |
|------|------|
| `Reservation/@Locator` | 预订编号 |
| `Reservation/@Status` | 预订状态 |
| `Reservation/@ReservationDate` | 预订日期 |
| `Reservation/Holder/RelPax/@IdPax` | 预订持有人的旅客 ID |
| `Reservation/{Paxes}` | 旅客信息 |
| `Reservation/Items` | 预订明细（酒店、机票等） |

**预订状态值：**

| 状态码 | 说明 |
|--------|------|
| `PAG` | 已确认已支付 |
| `CON` | 已确认 |
| `CAN` / `CAC` | 已取消 |
| `PRE` / `PDI` | 待确认（On Request） |
| `QUO` | 报价（需通过 API 支付） |
| `TAR` | 待信用卡支付 |

---

### CancelBooking

取消整个预订或其中一个服务项。也可用于查询取消费用（不实际取消）。

#### 请求

| 属性 | 必填 | 类型 | 说明 |
|------|------|------|------|
| `{Login}` | 是 | - | 认证信息 |
| `CancelRequest/@ReservationLocator` | 是 | String | 预订编号 |
| `CancelRequest/@ItemId` | 否 | Integer | 服务项 ID（不填则取消整个预订） |
| `CancelRequest/@OnlyCancellationFees` | 否 | Boolean | 仅查询取消费用，不实际取消 |
| `AdvancedOptions/ShowCancelBreakdown` | 否 | Boolean | 显示取消费用明细 |

```xml
<!-- 取消整个预订 -->
<CancelBooking>
  <CancelRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <CancelRequest ReservationLocator="WZS1N6"/>
  </CancelRQ>
</CancelBooking>

<!-- 仅查询取消费用 -->
<CancelBooking>
  <CancelRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <CancelRequest ReservationLocator="WZS1N6" OnlyCancellationFees="true"/>
  </CancelRQ>
</CancelBooking>
```

#### 响应

响应中的 **Warnings** 非常重要：

| Warning Code | 说明 |
|---|---|
| `warnCancellationCostRetrieved` | 取消费用已获取（未取消） |
| `warnCancellationNotCalculated` | 取消费用无法计算（未取消） |
| `warnCancelledAndCancellationCostRetrieved` | 已取消，取消费用已获取 |
| `warnCancelledAndCancellationNotCalculated` | 已取消，但取消费用无法计算（需联系供应商确认） |

**CancelInfo 对象：**

| 属性 | 说明 |
|------|------|
| `BookingCodeState` | 预订最终状态 |
| `BookingCancelCost` | 取消费用金额 |
| `BookingCancelCostCurrency` | 取消费用货币 |

---

### MeetingPointList

获取集合点列表。主要用于接送（Transfer）产品，酒店产品一般不需要。

---

### FinalCustomerRead / FinalCustomerSave

读取/保存最终客户信息。用于客户信息管理。

---

### ShoppingBasketRead / ShoppingBasketSave

购物车功能。读取/保存购物车内容。可选功能。

---

### AgencyRead / CustomerRead / SupplierList

管理后台功能：
- **AgencyRead**: 读取代理商信息
- **CustomerRead**: 读取客户信息
- **SupplierList**: 获取供应商列表

---

## 重要注意事项

### HTTP 请求要求

1. **必须支持压缩响应**: 请求头需包含 `Accept-Encoding: gzip`
2. **推荐设置 Content-Type**: `Content-Type: text/xml;charset=UTF-8`
3. **SOAP 命名空间**: `http://www.juniper.es/webservice/2007/`

### BookingCode 过期机制

BookingRules 返回的 BookingCode 包含 `ExpirationDate` 属性：

```xml
<BookingCode ExpirationDate="2019-10-03T10:04:26.8377656+02:00">
  ya79dM4dS6R6EywV4XhfEvwItLN5sfa4...
</BookingCode>
```

如果在调用 Booking 之前 BookingCode 过期，需要重新调用 BookingRules 获取新的 BookingCode。

### ExternalBookingReference

预订时可以传入自己系统的参考号。在预订超时等异常情况下，可以通过 BookingList + ExternalBookingReference 来查找预订。

> 如果要用此功能查找超时预订，需要在发送预订请求后等待至少 **180 秒**（Juniper 预订确认超时时间），再通过 BookingList 查询。

---

## 与本项目的对照

| Juniper Common API | 我们的实现 | 状态 | 优先级 |
|---|---|---|---|
| GenericDataCatalogue | - | **缺失** | 高（基础数据） |
| ZoneList | - | **缺失** | 高（搜索必需） |
| CityList | - | **缺失** | 中（ZoneList 的简化替代） |
| HotelAvail | `supplier.hotel_avail()` | 已实现 | - |
| CheckAvail | `supplier.hotel_check_avail()` | 已实现 | - |
| BookingRules | `supplier.hotel_booking_rules()` | 已实现 | - |
| HotelBooking | `supplier.hotel_booking()` | 已实现 | - |
| ReadBooking | `read_booking` tool (查本地 DB) | 已实现 | - |
| CancelBooking | `supplier.cancel_booking()` | 已实现 | - |
| BookingList | - | **缺失** | 中（对账用） |
| MeetingPointList | - | 不需要 | - |
| FinalCustomerRead/Save | - | **缺失** | 低 |
| ShoppingBasketRead/Save | - | 不需要 | - |
| AgencyRead/CustomerRead/SupplierList | - | 不需要 | - |

### 需要补齐的工作

1. **ZoneList + 本地缓存**: 搜索酒店时需要真实的目的地代码，而非文本匹配
2. **GenericDataCatalogue**: 获取货币和国家代码列表，作为基础数据
3. **BookingCode 过期处理**: BookingRules 返回的 BookingCode 有过期时间，需要在 agent 流程中处理
4. **HTTP 头优化**: 添加 `Accept-Encoding: gzip` 和 `Content-Type: text/xml;charset=UTF-8`
5. **BookingList**: 用于与供应商侧对账
