# Juniper Hotel API 完整参考文档

> 来源: https://api-edocs.ejuniper.com/en/api/jp/hotel-api
> 整理日期: 2026-04-03；Part 1 补充与 Part 5 对照更新：2026-04-20

## 目录

- [Part 1: 集成流程 & 静态数据接口](#part-1-集成流程--静态数据接口)
  - [集成资源（官方工具与示例）](#集成资源官方工具与示例)
  - [酒店通用类型（Hotel Generic Types）](#酒店通用类型-hotel-generic-types)
- [Part 2: 可用性搜索接口](#part-2-可用性搜索接口)
- [Part 3: 预订流程接口](#part-3-预订流程接口)
- [Part 4: FAQ & 认证流程](#part-4-faq--认证流程)
- [Part 5: 与本项目的对照](#part-5-与本项目的对照)

---

# Part 1: 集成流程 & 静态数据接口

## 酒店集成流程概览

Juniper 酒店预订集成流程分为四个步骤：

```
Static Data → Availability → Valuation → Booking
(静态数据)    (可用性搜索)   (验价确认)   (预订确认)
```

**推荐的静态数据获取流程：**

```
HotelCatalogueData → ZoneList → HotelPortfolio → HotelContent
(分类映射)           (目的地)    (酒店列表)       (酒店详情)
```

> 静态数据应缓存到本地数据库，至少每 15 天更新一次。

## 集成资源（官方工具与示例）

以下资源在 [Juniper Hotel API 官方文档](https://api-edocs.ejuniper.com/en/api/jp/hotel-api) 的 **Hotel Integration Resources** 中提供，便于联调与对照 XML（Juniper 不提供实现层面的编码支持，示例仅供参考）。

| 资源 | 说明 | 入口 |
|------|------|------|
| **SoapUI** | 含完整 PULL 流程的测试套件；另有 HotelPortfolio 专项套件 | [SoapUI](https://api-edocs.ejuniper.com/en/api/jp/hotel-api#soapui) |
| **Postman** | 覆盖完整预订流程的示例集合 | [Postman](https://api-edocs.ejuniper.com/en/api/jp/hotel-api#postman) |
| **Code samples** | Node.js / Java / C# / Ruby 等示例代码 | [Code samples](https://api-edocs.ejuniper.com/en/api/jp/hotel-api#code-samples) |

---

## 酒店通用类型（Hotel Generic Types）

官方在静态数据事务之前单独定义了多事务共用的结构。本节摘录常用节点；**完整字段与嵌套规则**仍以 [官方 Hotel Generic Types](https://api-edocs.ejuniper.com/en/api/jp/hotel-api#hotel-generic-types) 为准。

### Context（`@Context`）

在支持该属性的请求上设置上下文，便于 Juniper 侧优化路由与性能。**认证要求**：虽多为可选节点，但完成 **Hotel Certification** 时通常需按场景传入（参见 Part 4）。

| 取值 | 典型场景 |
|------|----------|
| `STDDOWNLOAD` | 静态数据批量下载 |
| `BOOKINGFLOWDOWNLOAD` | 预订流程中补充拉取酒店信息 |
| `CACHEROBOT` | 缓存机器人 |
| `CACHEMETASEARCH` | 元搜索 |
| `FULLAVAIL` | 按目的地覆盖的完整可用性（多酒店） |
| `SINGLEAVAIL` | 单一产品的完整结果列表 |
| `VALUATION` | 验价（如 HotelBookingRules） |
| `BOOKING` | 确认预订（HotelBooking） |
| `PAYMENT` | 自有支付流程中的请求 |
| `CANCEL` | 取消流程 |

各事务推荐取值见本文 Part 2 / Part 3 各节参数表；与上表不一致时以官方为准。

### ContentProviders

供应商提供的媒体与扩展展示信息容器，常见子节点包括：

- `ContentProvider/@Code`、`@ExternalCode`
- `Images`（与通用工作流中的 Images 结构一致）
- `MultimediaContents/MultimediaContent/FileName`（多媒体 URL）
- `HotelCategory`（内容侧住宿评级等）

酒店详情（**HotelContent**）或可用性中的酒店信息节点可能出现该结构，用于图片/多媒体来源标识。

### AdditionalElements（附加元素）

表示组合上的**补充费 / 促销**，分为已计入总价与可选加购等场景。顶层结构：

- `HotelSupplements`：补充费列表；子项常为 `HotelSupplement` 或 `OfferSupplement`（节点名因类型而异，字段共用一套模式）。
- `HotelOffers`：促销 / 优惠列表。

`AdditionalElement` 一类节点常见属性（节选，完整见官网表格）：

| 属性 | 含义（节选） |
|------|----------------|
| `@Code` | 内部代码（直签合同中更完整） |
| `@Class` | `SUPPLEMENT` / `PROMO` |
| `@Type` | `M` 必选、`O` 可选、`R` 限制说明性 |
| `@Category` | 金额类 / 百分比 / PayStay 等；与 **HotelCatalogueData** 中类型表对应 |
| `@DirectPayment` | `true` 表示到店支付，**不计入**组合总价 |
| `@Optional` | 是否可选（多针对 supplement） |
| `@RatePlanCode` | 可选补充项需用此码在后续 **HotelBookingRules** 中追加 |
| `@Begin` / `@End` | 生效日期（`yyyy-MM-dd`） |
| `FreeNights` | PayStay 类促销的免晚说明 |
| `SupplementRelPaxesDist` | 可选补充指定到某位乘客时再询价 |
| `PickUpPoints` | 接驳点列表；多选一时常要求在 **HotelBookingRules** 阶段先选定 |

**HotelBookingRules** 响应中的 **Extended information**（取消规则细例、可选补充费流程、Preferences 等）见 [官方 Extended information](https://api-edocs.ejuniper.com/en/api/jp/hotel-api#extended-information)。

**Warnings 总表**（各事务共用码）：见 [Juniper Warnings FAQ](https://api-edocs.ejuniper.com/api/faq/warnings)。

---

## 静态数据接口

### HotelList（酒店列表 — 已弃用）

按目的地代码获取酒店列表。新连接建议使用 `HotelPortfolio` 代替。

### HotelCatalogueData（目录数据）

**用途：** 获取分类映射数据（酒店星级、房间类别、餐食类型、附加费类型等）。

| 响应节点 | 说明 |
|----------|------|
| `HotelCategoryList` | 酒店星级（如 `5est`=五星） |
| `BoardList` | 餐食类型（`SA`=仅住宿, `AD`=含早, `MP`=半膳, `PC`=全膳, `TI`=全包） |
| `RoomCategoryList` | 房间类别 |
| `OfferSupplementTypeList` | 优惠/附加费类型 |

```xml
<HotelCatalogueData>
  <HotelCatalogueDataRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
  </HotelCatalogueDataRQ>
</HotelCatalogueData>
```

### HotelContent（酒店详情）

**用途：** 通过酒店代码（JPCode）获取详细信息（名称、地址、坐标、图片、描述、设施、房间等）。每次最多 25 个酒店。

| 响应字段 | 说明 |
|----------|------|
| `HotelName` | 酒店名称 |
| `HotelCategory/@Type` | 星级类型码 |
| `Address/Latitude, Longitude` | 经纬度 |
| `Images/Image` | 图片列表 |
| `Descriptions/Description` | 描述（SHT=短, LNG=长） |
| `Features/Feature` | 设施列表 |
| `TimeInformation/CheckTime` | 入住/退房时间 |

```xml
<HotelContent>
  <HotelContentRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <HotelContentList>
      <Hotel Code="JP046300"/>
    </HotelContentList>
  </HotelContentRQ>
</HotelContent>
```

### HotelPortfolio（酒店组合列表 — 推荐）

**用途：** 获取供应商下所有可用酒店代码（JPCode），支持分页（每页最多 500 条）和增量更新。

**分页机制：**
1. 首次请求设 `@RecordsPerPage`，不设 `@Token`
2. 响应返回 `@NextToken` → 作为下次请求的 `@Token`
3. 无 `@NextToken` → 最后一页

```xml
<HotelPortfolio>
  <HotelPortfolioRQ Version="1.1" Language="en" RecordsPerPage="500">
    <Login Email="user@mydomain.com" Password="pass"/>
  </HotelPortfolioRQ>
</HotelPortfolio>
```

响应包含: `Hotel/@JPCode`, `Hotel/Name`, `Hotel/Zone/@JPDCode`, `Hotel/Address`, `Latitude/Longitude`, `HotelCategory/@Type`

### AccommodationPortfolio（非酒店住宿列表）

与 HotelPortfolio 类似，返回非酒店类住宿代码。分页机制相同。

### RoomList（房间列表）

获取所有可用的 Juniper 房间代码（JRCode）。需供应商启用 room mapping module。分页机制与 HotelPortfolio 相同。

---

# Part 2: 可用性搜索接口


> 从 Juniper SOAP API 原始文档中提取，涵盖酒店可用性搜索、日历查询、未来费率查询和可用性验证四个事务。

---

## 1. HotelAvail — 酒店可用性搜索

**用途：** 根据指定的搜索条件（日期、入住人数、酒店代码等），从 Juniper 供应商获取所有匹配的可用房型组合及价格。是预订流程的第一步。

### 1.1 请求参数

#### 基础参数

| 节点/属性 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `@Version` | Y | String | Web Service 版本 |
| `@Context` | N | String | 请求上下文键，优化性能。推荐值：`CACHEROBOT`, `CACHEMETASEARCH`, `FULLAVAIL`, `SINGLEAVAIL` |
| `@Language` | Y | String | 返回语言代码 |
| `{Login}` | Y | - | 登录凭证（Email + Password） |
| `{Paxes}` | Y | - | 旅客列表。每个 `Pax` 需 `@IdPax`，儿童需指定 `Age`（未指定默认30岁成人） |

#### 搜索条件 (SearchSegmentsHotels)

| 节点/属性 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `SearchSegmentHotels/@Start` | Y | Date | 入住日期 `yyyy-MM-dd` |
| `SearchSegmentHotels/@End` | Y | Date | 退房日期 `yyyy-MM-dd` |
| `HotelCodes/HotelCode` | Y | String | 酒店代码，最多500个，建议同一目的地 |
| `CountryOfResidence` | Y | String | 预订持有人国籍（ISO-3166-1 二字码），需全流程一致 |
| `HotelName` | N | String | 按酒店名称过滤 |
| `PackageContracts` | N | String | 套餐合同类型：`Hotel`(默认), `Package`, `OnlyPackage` |
| `HotelCategories/HotelCategory@Type` | N | String | 按酒店星级/类别过滤 |
| `PropertyTypes/PropertyType@Type` | N | String | 物业类型：`HTL`(酒店), `VLL`(别墅) |
| `Boards/Board@Type` | N | String | 餐食计划类型过滤 |
| `PromoCodes/Promocode` | N | String | 促销代码 |
| `PaymentType` | N | String | 付款类型：`ExcludePaymentInDestination`(默认), `OnlyPaymentInDestination`, `All` |
| `Suppliers/Supplier` | N | String | 供应商过滤（受限功能） |

#### 房间分配 (RelPaxesDist)

| 节点/属性 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `RelPaxDist` | Y | - | 每个节点代表一间房 |
| `RelPax/@IdPax` | Y | Integer | 旅客标识，对应 `Paxes` 中的 `Pax@IdPax` |
| `Room/@CategoryType` | N | String | 房间类别类型 |

#### 高级选项 (AdvancedOptions)

| 节点/属性 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `UseCurrency` | String | 供应商默认 | 货币代码，全流程需一致 |
| `ShowBreakdownPrice` | Boolean | false | 显示完整价格明细 |
| `ShowHotelInfo` | Boolean | false | 显示酒店额外信息（名称/描述/图片等） |
| `ShowOnlyAvailable` | Boolean | false | 仅显示有房的结果 |
| `ShowAllCombinations` | Boolean | false | 显示所有可能的房间组合 |
| `ShowAllChildrenCombinations` | Boolean | false | 将儿童按成人处理显示更多组合（较慢） |
| `ShowCancellationPolicies` | Boolean | false | 显示取消政策（仅直签酒店） |
| `ShowOnlyBestPriceCombination` | Boolean | false | 仅返回每酒店最低价组合（多酒店搜索时有效） |
| `MaxCombinations` | Numeric | - | 仅返回最便宜的 N 个组合 |
| `ShowDynamicInventory` | Boolean | false | 显示是否来自动态库存 |
| `HideRatePlanCode` | Boolean | false | 隐藏 RatePlanCode（非预订流程时减小响应体积） |
| `TimeOut` | Integer | 供应商配置 | 超时（毫秒），最大8000 |
| `ShowAvailabilityBreakdown` | Boolean | false | 显示每日可用性明细 |
| `MinimumPrice` | Numeric | - | 返回最接近指定最低价的费率 |

### 1.2 响应参数

#### 顶层

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `@Url` | String | 端点 URL |
| `@TimeStamp` | DateTime | 响应时间 |
| `@IntCode` | String | 内部控制码 |
| `{Errors}` | - | 错误信息 |
| `{Warnings}` | - | 警告信息 |

#### HotelResult — 酒店结果

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `@Code` | String | 酒店代码 |
| `@JPCode` | String | Juniper 全局唯一酒店代码 |
| `@DestinationZone` | String | 目的地代码 |
| `@JPDCode` | String | 跨供应商共享目的地标识 |
| `@BestDeal` | Boolean | 是否为最优惠交易 |
| `@Type` | String | 类型：`HOTEL` / `ACCOMMODATION` |

#### HotelInfo（需启用 ShowHotelInfo）

| 节点 | 类型 | 说明 |
|---|---|---|
| `Name` | String | 酒店名称 |
| `Description` | String | 酒店描述 |
| `Images/Image` | String | 图片 URL 列表 |
| `HotelCategory@Type` | String | 酒店星级类别 |
| `PropertyType@Type` | String | 物业类型 |
| `Address` | String | 地址 |
| `Latitude` / `Longitude` | String | 经纬度 |
| `CheckTime@CheckIn/@CheckOut` | String | 入住/退房时间 |

#### HotelOption — 房型组合

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `@RatePlanCode` | String | **关键字段**：组合标识码，后续预订流程必需。缺失表示需要再做单酒店查询 |
| `@Status` | String | `OK`=可预订, `RQ`=需确认 |
| `@NonRefundable` | Boolean | 是否不可退 |
| `@PaymentDestination` | Boolean | 是否到店付款 |
| `@PackageContract` | Boolean | 是否套餐合同 |
| `@DynamicInventory` | Boolean | 是否动态库存 |
| `Board` | String | 餐食名称 |
| `Board/@Type` | String | 餐食类型代码（如 `SA`=仅住宿, `AD`=含早, `MP`=半膳） |

#### Prices — 价格

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `Price/@Type` | String | 价格类型（`S`=销售价） |
| `Price/@Currency` | String | 货币代码 |
| `TotalFixAmounts/@Gross` | Decimal | 总价（含税） |
| `TotalFixAmounts/@Nett` | Decimal | 净价 |
| `Service/@Amount` | Decimal | 服务费金额 |
| `ServiceTaxes/@Amount` | Decimal | 税额 |
| `ServiceTaxes/@Included` | Boolean | 税是否已包含在服务费中 |

#### HotelRoom — 房间

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `@Units` | Integer | 房间数量 |
| `@Source` | String | 房间标识（如 "1", "2"） |
| `@AvailRooms` | Integer | 剩余可用房间数 |
| `@JRCode` | String | Juniper 房间代码 |
| `Name` | String | 房型名称 |
| `RoomCategory/@Type` | String | 房间类别类型 |
| `RoomOccupancy/@Occupancy` | Integer | 总入住人数 |
| `RoomOccupancy/@Adults` | Integer | 成人数 |
| `RoomOccupancy/@Children` | Integer | 儿童数 |

#### AdditionalElements — 附加元素（优惠/补充费）

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `HotelOffer/@Code` | String | 优惠代码 |
| `HotelOffer/Name` | String | 优惠名称 |
| `HotelOffer/Description` | String | 优惠描述 |

### 1.3 请求示例

```xml
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns="http://www.juniper.es/webservice/2007/">
  <soapenv:Header/>
  <soapenv:Body>
    <HotelAvail>
      <HotelAvailRQ Version="1.1" Language="en">
        <Login Email="user@mydomain.com" Password="pass"/>
        <Paxes>
          <Pax IdPax="1"/>
          <Pax IdPax="2"/>
          <Pax IdPax="3"><Age>8</Age></Pax>
        </Paxes>
        <HotelRequest>
          <SearchSegmentsHotels>
            <SearchSegmentHotels Start="2019-11-20" End="2019-11-22"/>
            <CountryOfResidence>ES</CountryOfResidence>
            <HotelCodes>
              <HotelCode>JP046300</HotelCode>
            </HotelCodes>
          </SearchSegmentsHotels>
          <RelPaxesDist>
            <RelPaxDist>
              <RelPaxes><RelPax IdPax="1"/></RelPaxes>
            </RelPaxDist>
            <RelPaxDist>
              <RelPaxes>
                <RelPax IdPax="2"/>
                <RelPax IdPax="3"/>
              </RelPaxes>
            </RelPaxDist>
          </RelPaxesDist>
        </HotelRequest>
        <AdvancedOptions>
          <ShowHotelInfo>false</ShowHotelInfo>
          <ShowOnlyBestPriceCombination>true</ShowOnlyBestPriceCombination>
          <TimeOut>8000</TimeOut>
        </AdvancedOptions>
      </HotelAvailRQ>
    </HotelAvail>
  </soapenv:Body>
</soapenv:Envelope>
```

### 1.4 响应示例

```xml
<AvailabilityRS Url="http://xml-uat.bookingengine.es"
                TimeStamp="2019-10-02T16:59:02+02:00" IntCode="...">
  <Results>
    <HotelResult Code="JP150074" JPCode="JP150074" JPDCode="JPD086188"
                 BestDeal="false" DestinationZone="48782">
      <HotelOptions>
        <HotelOption RatePlanCode="bseM9QA..." Status="OK"
                     NonRefundable="false" PackageContract="false">
          <Board Type="AD">BED AND BREAKFAST</Board>
          <Prices>
            <Price Type="S" Currency="EUR">
              <TotalFixAmounts Gross="218.64" Nett="218.64">
                <Service Amount="218.64"/>
              </TotalFixAmounts>
            </Price>
          </Prices>
          <HotelRooms>
            <HotelRoom Units="1" Source="1">
              <Name>DOUBLE SINGLE USE STANDARD</Name>
              <RoomCategory Type="DUS.ST"/>
            </HotelRoom>
            <HotelRoom Units="1" Source="2">
              <Name>Double or Twin STANDARD</Name>
              <RoomCategory Type="DBT.ST"/>
            </HotelRoom>
          </HotelRooms>
        </HotelOption>
      </HotelOptions>
    </HotelResult>
  </Results>
</AvailabilityRS>
```

---

## 2. HotelAvailCalendar — 酒店日历可用性

**用途：** 获取指定酒店在某个日期范围内的日历式可用性。按入住夜数拆分日期区间，每个区间返回一个可用结果。适用于日历价格展示场景。

### 2.1 请求参数

| 节点/属性 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `@Version` | Y | String | Web Service 版本 |
| `@Language` | Y | String | 返回语言 |
| `{Login}` | Y | - | 登录凭证 |
| `{Paxes}` | Y | - | 旅客信息 |
| `SearchSegmentHotels/@Start` | Y | Date | 日期范围开始日 |
| `SearchSegmentHotels/@End` | Y | Date | 日期范围结束日（注意：不是住宿结束日） |
| `Nights` | Y | Integer | 每段住宿的夜数 |
| `HotelCodes/HotelCode` | Y | String | 酒店代码（**限1个**） |
| `CountryOfResidence` | Y | String | 国籍 ISO-3166-1 |
| `Boards/Board@Type` | N | String | 餐食过滤（限1个，**未实现**） |
| `RelPaxesDist` | Y | - | 房间分配（通常最多3间） |
| `RoomCategories/RoomCategory@Type` | N | String | 房间类别过滤 |

**AdvancedOptions：** 支持 `ShowBreakdownPrice`, `ShowHotelInfo`, `ShowOnlyAvailable`, `ShowAllCombinations`, `ShowAllChildrenCombinations`, `UseCurrency`（同 HotelAvail）。

### 2.2 响应参数

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `HotelCalendarResult/@Start` | Date | 此区间入住日 |
| `HotelCalendarResult/@End` | Date | 此区间退房日 |
| `HotelResult/@Code` | String | 酒店代码 |
| `HotelOption/@RatePlanCode` | String | 组合标识码（缺失则需额外单酒店查询） |
| `HotelOption/@Status` | String | `OK` / `RQ` |
| `HotelOption/@NonRefundable` | Boolean | 不可退标记 |
| `Board/@Type` | String | 餐食类型 |
| `{Prices}` | - | 价格（结构同 HotelAvail） |
| `HotelRoom` | - | 房间信息（结构同 HotelAvail） |

### 2.3 请求示例

```xml
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns="http://www.juniper.es/webservice/2007/">
  <soapenv:Header/>
  <soapenv:Body>
    <HotelAvailCalendar>
      <HotelAvailCalendarRQ Version="1.1" Language="en">
        <Login Email="user@mydomain.com" Password="pass"/>
        <Paxes>
          <Pax IdPax="1"/>
          <Pax IdPax="2"/>
        </Paxes>
        <HotelCalendarRequest>
          <SearchSegmentsHotels>
            <SearchSegmentHotels Start="2019-11-02" End="2019-11-03"/>
            <Nights>2</Nights>
            <HotelCodes><HotelCode>JP046300</HotelCode></HotelCodes>
            <CountryOfResidence>ES</CountryOfResidence>
          </SearchSegmentsHotels>
          <RelPaxesDist>
            <RelPaxDist>
              <RelPaxes>
                <RelPax IdPax="1"/>
                <RelPax IdPax="2"/>
              </RelPaxes>
            </RelPaxDist>
          </RelPaxesDist>
        </HotelCalendarRequest>
      </HotelAvailCalendarRQ>
    </HotelAvailCalendar>
  </soapenv:Body>
</soapenv:Envelope>
```

### 2.4 响应示例

```xml
<AvailabilityRS Url="http://xml-uat.bookingengine.es" TimeStamp="..." IntCode="...">
  <Results>
    <HotelCalendarResult Start="2019-11-02" End="2019-11-04">
      <HotelResults>
        <HotelResult Code="JP046300" JPCode="JP046300" JPDCode="JPD086855">
          <HotelOptions>
            <HotelOption RatePlanCode="ya79dM4..." Status="OK" NonRefundable="true">
              <Board Type="SA">Room Only</Board>
              <Prices>
                <Price Type="S" Currency="EUR">
                  <TotalFixAmounts Gross="223.56" Nett="223.56">
                    <Service Amount="203.24"/>
                    <ServiceTaxes Included="false" Amount="20.32"/>
                  </TotalFixAmounts>
                </Price>
              </Prices>
              <HotelRooms>
                <HotelRoom Units="1" Source="1" AvailRooms="88">
                  <Name>Non refundable room</Name>
                  <RoomCategory Type="2">Category 2</RoomCategory>
                  <RoomOccupancy Occupancy="2" Adults="2" Children="0"/>
                </HotelRoom>
              </HotelRooms>
            </HotelOption>
          </HotelOptions>
        </HotelResult>
      </HotelResults>
    </HotelCalendarResult>
    <!-- 每个日期区间一个 HotelCalendarResult -->
  </Results>
</AvailabilityRS>
```

---

## 3. HotelFutureRates — 未来费率查询

**用途：** 检索未来日期范围内的酒店费率，可绕过大部分必填过滤条件。功能类似 HotelAvailCalendar，但更灵活：可不指定酒店代码（默认搜索10个热门目的地），不指定入住分配（默认搜索8种常见分配）。**此服务默认未激活，仅适用于直签酒店。**

### 3.1 请求参数

| 节点/属性 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `@Version` | Y | String | Web Service 版本 |
| `@Language` | Y | String | 返回语言 |
| `{Login}` | Y | - | 登录凭证 |
| `{Paxes}` | N | - | 旅客信息（不填则使用8种默认分配） |
| `SearchSegmentHotels/@Start` | Y | Date | Nights>0 时为日期范围起始；Nights=0 时为入住日 |
| `SearchSegmentHotels/@End` | Y | Date | Nights>0 时为日期范围结束；Nights=0 时为退房日 |
| `SearchSegmentHotels/@DestinationZone` | N | Integer | 目的地代码（不填默认10个热门目的地） |
| `Nights` | Y | Integer | 每段住宿夜数（0=按 Start/End 做普通查询） |
| `HotelCodes/HotelCode` | N | String | 酒店代码（不填则按整个目的地搜索） |
| `CountryOfResidence` | Y | String | 国籍 |
| `Boards/Board@Type` | N | String | 餐食过滤（限1个） |
| `RelPaxesDist` | N | - | 房间分配（不填默认：1AD, 2AD, 3AD, 4AD, 1AD+1CH, 1AD+2CH, 2AD+2CH, 3AD+2CH） |

**AdvancedOptions：** 支持 `ShowBreakdownPrice`, `ShowHotelInfo`, `ShowOnlyAvailable`, `ShowAllCombinations`, `UseCurrency`。

### 3.2 响应参数

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `HotelFutureRatesResult/ResultInfo/Start` | Date | 入住日 |
| `HotelFutureRatesResult/ResultInfo/End` | Date | 退房日 |
| `ResultInfo/DestinationZone` | Integer | 目的地代码 |
| `ResultInfo/HotelCode` | String | 酒店代码 |
| `ResultInfo/{Paxes}` | - | 对应的旅客分配（每个结果只有一个分配/一间房） |
| `HotelResult` | - | 酒店结果（结构同 HotelAvail） |
| `HotelOption/@RatePlanCode` | String | 组合标识码 |
| `WarningDetails/Dates` | - | 过载时建议的日期拆分 |
| `WarningDetails/DestinationZones` | - | 过载时建议的目的地拆分 |
| `WarningDetails/Distributions` | - | 过载时建议的分配拆分 |

### 3.3 请求示例

```xml
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns="http://www.juniper.es/webservice/2007/">
  <soapenv:Header/>
  <soapenv:Body>
    <HotelFutureRates>
      <HotelFutureRatesRQ Version="1.1" Language="en">
        <Login Email="user@mydomain.com" Password="pass"/>
        <Paxes>
          <Pax IdPax="1"><Age>45</Age></Pax>
          <Pax IdPax="2"><Age>3</Age></Pax>
          <Pax IdPax="3"><Age>54</Age></Pax>
        </Paxes>
        <HotelFutureRatesRequest>
          <SearchSegmentsHotelFutureRates>
            <SearchSegmentHotels Start="2019-11-02" End="2019-11-03"/>
            <Nights>7</Nights>
            <CountryOfResidence>ES</CountryOfResidence>
            <HotelCodes><HotelCode>JP046300</HotelCode></HotelCodes>
          </SearchSegmentsHotelFutureRates>
          <RelPaxesDist>
            <RelPaxDist>
              <RelPaxes>
                <RelPax IdPax="1"/>
                <RelPax IdPax="2"/>
              </RelPaxes>
            </RelPaxDist>
            <RelPaxDist>
              <RelPaxes><RelPax IdPax="3"/></RelPaxes>
            </RelPaxDist>
          </RelPaxesDist>
        </HotelFutureRatesRequest>
      </HotelFutureRatesRQ>
    </HotelFutureRates>
  </soapenv:Body>
</soapenv:Envelope>
```

### 3.4 响应示例

```xml
<FutureRatesRS Url="http://xml-uat.bookingengine.es" TimeStamp="..." IntCode="...">
  <Results>
    <HotelFutureRatesResults>
      <HotelFutureRatesResult>
        <ResultInfo>
          <Start>2019-11-02</Start>
          <End>2019-11-09</End>
          <DestinationZone>49435</DestinationZone>
          <HotelCode>JP046300</HotelCode>
          <Paxes><Pax IdPax="1"><Age>54</Age></Pax></Paxes>
        </ResultInfo>
        <HotelResult Code="JP046300" JPCode="JP046300" JPDCode="JPD086855">
          <HotelOptions>
            <HotelOption RatePlanCode="ya79dM4..." Status="OK" NonRefundable="true">
              <Board Type="SA">Room Only</Board>
              <Prices>
                <Price Type="S" Currency="EUR">
                  <TotalFixAmounts Gross="782.47" Nett="782.47">
                    <Service Amount="711.34"/>
                    <ServiceTaxes Included="false" Amount="71.13"/>
                  </TotalFixAmounts>
                </Price>
              </Prices>
              <HotelRooms>
                <HotelRoom Units="1" Source="1" AvailRooms="88">
                  <Name>Non refundable room</Name>
                  <RoomCategory Type="2">Category 2</RoomCategory>
                  <RoomOccupancy Occupancy="1" Adults="1" Children="0"/>
                </HotelRoom>
              </HotelRooms>
            </HotelOption>
          </HotelOptions>
        </HotelResult>
      </HotelFutureRatesResult>
    </HotelFutureRatesResults>
  </Results>
</FutureRatesRS>
```

---

## 4. HotelCheckAvail — 可用性验证

**用途：** 对 HotelAvail 返回的某个组合（RatePlanCode）进行二次验证。若价格或状态发生变化，系统会通过 Warning 通知。会生成新的 RatePlanCode 用于后续流程。**建议在可用性结果缓存较久时使用；若实时查询可跳过此步直接到 HotelBookingRules。**

### 4.1 请求参数

| 节点/属性 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `@Version` | Y | String | Web Service 版本 |
| `@Context` | N | String | 请求上下文。推荐值：`SINGLEAVAIL`, `VALUATION` |
| `@Language` | Y | String | 返回语言 |
| `{Login}` | Y | - | 登录凭证 |
| `HotelOption/@RatePlanCode` | Y | String | 从 HotelAvail 响应获取的组合标识码 |
| `SearchSegmentHotels/@Start` | Y | Date | 入住日期（需与原始查询一致） |
| `SearchSegmentHotels/@End` | Y | Date | 退房日期（需与原始查询一致） |
| `HotelCodes/HotelCode` | Y | String | 酒店代码（需与原始查询一致） |
| `AdvancedOptions/ShowBreakdownPrice` | N | Boolean | 显示完整价格明细 |
| `AdvancedOptions/UseCurrency` | N | String | 货币代码（需全流程一致） |

### 4.2 响应参数

| 节点/属性 | 类型 | 说明 |
|---|---|---|
| `{Warnings}` | - | **关键**：`warnPriceChanged`=价格变化, `warnStatusChanged`=状态变化, `warnCheckNotPossible`=无法验证 |
| `HotelOption/@RatePlanCode` | String | **新的 RatePlanCode**，后续流程必须使用此值 |
| `HotelOption/@Status` | String | `OK` / `RQ` |
| `HotelOption/@PaymentDestination` | Boolean | 是否到店付款 |
| `HotelOption/@VervotechCode` | String | Vervotech 映射代码（如启用） |
| `Board/@Type` | String | 餐食类型 |
| `{Prices}` | - | 更新后的价格 |
| `HotelRoom` | - | 房间信息（含 Name, RoomCategory, RoomOccupancy） |
| `Comments/Comment@Type` | String | 变更说明。类型 `CHKAV` 表示可用性检查评论 |

### 4.3 请求示例

```xml
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
                  xmlns="http://www.juniper.es/webservice/2007/">
  <soapenv:Header/>
  <soapenv:Body>
    <HotelCheckAvail>
      <HotelCheckAvailRQ Version="1.1" Language="en">
        <Login Email="user@mydomain.com" Password="pass"/>
        <HotelCheckAvailRequest>
          <HotelOption RatePlanCode="ya79dM4dS6R6EywV4XhfEjz0JYH..."/>
          <SearchSegmentsHotels>
            <SearchSegmentHotels Start="2020-12-20" End="2020-12-25"/>
            <HotelCodes><HotelCode>JP046300</HotelCode></HotelCodes>
          </SearchSegmentsHotels>
        </HotelCheckAvailRequest>
      </HotelCheckAvailRQ>
    </HotelCheckAvail>
  </soapenv:Body>
</soapenv:Envelope>
```

### 4.4 响应示例

```xml
<CheckAvailRS Url="http://xml-uat.bookingengine.es" TimeStamp="..." IntCode="...">
  <Warnings>
    <Warning Code="warnPriceChanged"
             Text="Price changed. A new RatePlanCode has been returned."/>
  </Warnings>
  <Results>
    <HotelResult>
      <HotelOptions>
        <HotelOption RatePlanCode="ya79dM4dS6R6Eyw..." Status="OK">
          <Board Type="SA">Room Only</Board>
          <HotelRooms>
            <HotelRoom Units="1" Source="1" AvailRooms="800">
              <Name>Double</Name>
              <RoomCategory Type="2">Category 2</RoomCategory>
              <RoomOccupancy Occupancy="2" Adults="2" Children="0"/>
            </HotelRoom>
          </HotelRooms>
          <Prices>
            <Price Type="S" Currency="EUR">
              <TotalFixAmounts Gross="1116.94" Nett="1116.94">
                <Service Amount="1015.4"/>
                <ServiceTaxes Included="false" Amount="101.54"/>
              </TotalFixAmounts>
            </Price>
          </Prices>
        </HotelOption>
      </HotelOptions>
    </HotelResult>
  </Results>
</CheckAvailRS>
```

---

## 附录：预订流程概览

```
HotelAvail          搜索可用房型，获取 RatePlanCode
    |
    v
HotelCheckAvail     (可选) 验证可用性，获取更新的 RatePlanCode
    |
    v
HotelBookingRules   验价 + 获取取消政策 + BookingCode（10分钟有效）
    |
    v
HotelBooking        确认预订
```

> 注意：`CountryOfResidence`、`UseCurrency`、`PackageContracts` 等参数需在整个流程中保持一致。

---

# Part 3: 预订流程接口


> 预订流程: HotelAvail -> HotelCheckAvail(可选) -> **HotelBookingRules** -> **HotelBooking** -> ReadBooking / CancelBooking / HotelModify+HotelConfirmModify

---

## 1. HotelBookingRules - 获取预订规则

**用途**: 验价请求。根据 RatePlanCode 验证组合有效性，返回 BookingCode（用于确认预订）、取消政策、必填字段、酒店详细信息和附加费用。BookingCode 有效期通常为 10 分钟。

### 请求参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| @Version | 是 | String | Web Service 版本 |
| @Context | 否 | String | 请求上下文键，推荐值: VALUATION, BOOKING, PAYMENT |
| @Language | 是 | String | 响应语言 |
| {Login} | 是 | - | 登录凭证 (Email + Password) |
| HotelOption/@RatePlanCode | 是 | String | 从 HotelAvail 或 HotelCheckAvail 获得的编码，标识酒店房间组合 |
| SearchSegmentHotels/@Start | 是 | Date | 入住日期 (yyyy-MM-dd) |
| SearchSegmentHotels/@End | 是 | Date | 退房日期 (yyyy-MM-dd) |
| HotelCodes/HotelCode | 是 | String | 酒店代码 |
| AdvancedOptions/UseCurrency | 否 | String | 指定货币代码 |
| AdvancedOptions/ShowOnlyBasicInfo | 否 | Boolean | 是否隐藏详细静态数据以减小传输量 |
| AdvancedOptions/ShowBreakdownPrice | 否 | Boolean | 是否展示完整价格明细 |
| AdvancedOptions/PromoCode | 否 | String | 促销代码 |
| AdvancedOptions/ShowCompleteInfo | 否 | Boolean | 是否展示完整房型信息（含房间描述和图片） |

### 响应参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| @Url, @TimeStamp, @IntCode | 是 | - | 基础响应信息 |
| {Errors} | 否 | - | 错误信息 |
| {Warnings} | 否 | - | 警告信息（关注 warnPriceChanged, warnStatusChanged） |
| HotelOption/@Status | 否 | String | OK=可用, RQ=候补 |
| **BookingCode** | 是 | String | **预订确认码**，用于后续 HotelBooking 请求 |
| **BookingCode/@ExpirationDate** | 是 | DateTime | **BookingCode 过期时间**，通常为 10 分钟 |
| **{HotelRequiredFields}** | 是 | - | **必填字段结构**，与 HotelBooking 请求结构一致，仅返回的节点/属性为必填 |
| **{CancellationPolicy}** | 否 | - | **取消政策** |
| CancellationPolicy/@CurrencyCode | - | String | 取消费用货币 |
| FirstDayCostCancellation | - | Date | 开始产生取消费用的第一天 |
| Description | - | String | 取消政策文本描述 |
| PolicyRules/Rule | - | - | 取消规则明细（@From/@To=天数范围, @DateFrom/@DateTo=日期范围, @Type=V/S/R, @FixedPrice, @PercentPrice, @Nights） |
| PriceInformation/Board | 否 | String | 餐食计划 (@Type: SA=仅房, AD=含早, MP=半板等) |
| PriceInformation/HotelRooms | 否 | - | 房间列表（名称、类别、入住人数） |
| PriceInformation/{Prices} | 是 | - | 组合价格 (Gross, Nett, Service, ServiceTaxes) |
| PriceInformation/{HotelContent} | 是 | - | 酒店详细信息（名称、地址、星级、坐标等） |
| OptionalElements/Comments | 否 | - | 酒店备注（可能包含额外税费、服务警告等重要信息） |
| OptionalElements/HotelSupplements | 否 | - | 可选附加费（含 RatePlanCode，需再次发送 BookingRules 请求以添加） |

### XML 示例

```xml
<!-- 请求 -->
<HotelBookingRules>
  <HotelBookingRulesRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <HotelBookingRulesRequest>
      <HotelOption RatePlanCode="ya79dM4dS6R6EywV4XhfEv....."/>
      <SearchSegmentsHotels>
        <SearchSegmentHotels Start="2019-11-20" End="2019-11-22"/>
        <HotelCodes><HotelCode>JP046300</HotelCode></HotelCodes>
      </SearchSegmentsHotels>
    </HotelBookingRulesRequest>
  </HotelBookingRulesRQ>
</HotelBookingRules>

<!-- 响应（关键部分） -->
<HotelOption Status="OK">
  <BookingCode ExpirationDate="2019-10-03T09:46:30+02:00">ya79dM4dS6R6...</BookingCode>
  <HotelRequiredFields>
    <HotelBooking>
      <Paxes>
        <Pax IdPax="1"><Name/><Surname/><PhoneNumbers><PhoneNumber/></PhoneNumbers><Age/></Pax>
      </Paxes>
      <Holder><RelPax IdPax="1"/></Holder>
      <Elements><HotelElement><BookingCode/><RelPaxesDist/><HotelBookingInfo/></HotelElement></Elements>
    </HotelBooking>
  </HotelRequiredFields>
  <CancellationPolicy CurrencyCode="EUR">
    <FirstDayCostCancellation Hour="00:00">2019-11-13</FirstDayCostCancellation>
    <PolicyRules>
      <Rule From="0" To="3" DateFrom="2019-11-17" DateTo="2019-11-21" Type="V" PercentPrice="100"/>
      <Rule From="4" To="7" DateFrom="2019-11-13" DateTo="2019-11-17" Type="V" PercentPrice="25"/>
      <Rule From="8" DateFrom="2019-10-03" DateTo="2019-11-13" Type="V" PercentPrice="0"/>
    </PolicyRules>
  </CancellationPolicy>
</HotelOption>
```

---

## 2. HotelBooking - 创建预订

**用途**: 预订确认请求。使用 HotelBookingRules 返回的 BookingCode 确认预订，需提供旅客信息、房间分配和价格范围。支持单次请求预订多个酒店，也支持追加预订到已有 Locator。

### 请求参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| @Version | 是 | String | Web Service 版本 |
| @Language | 是 | String | 响应语言 |
| @TimeStamp | 否 | DateTime | 可选时间戳，用于验证响应时间 |
| {Login} | 是 | - | 登录凭证 |
| **{Paxes}** | 是 | - | **旅客信息数组** |
| Pax/@IdPax | 是 | Integer | 旅客标识 |
| Pax/Name, Surname | 是 | String | 姓名 |
| Pax/Age | 是 | Integer | 年龄 |
| Pax/PhoneNumbers | 按需 | - | 电话（根据 RequiredFields 决定是否必填） |
| Pax/Email | 按需 | String | 邮箱 |
| Pax/Document | 按需 | String | 证件号 (@Type: DNI/Passport 等) |
| Pax/Address, City, Country, PostalCode, Nationality | 按需 | String | 地址信息 |
| **Holder/RelPax/@IdPax** | 是 | Integer | **预订持有人**，引用 Paxes 中的旅客 ID |
| ReservationLocator | 否 | String | 已有预订号（用于追加预订） |
| ExternalBookingReference | 否 | String | 自定义参考号（最多 50 字符） |
| Comments/Comment | 否 | String | 预订备注 (@Type: RES=通用, INT=内部) |
| **HotelElement/BookingCode** | 是 | String | **从 HotelBookingRules 获得的预订码** |
| **HotelElement/RelPaxesDist** | 是 | - | **房间旅客分配**（每个 RelPaxDist 对应一间房） |
| HotelElement/CreditCard | 否 | - | 信用卡信息（目的地付款时用作担保）: @CardCode, @CvC, @CardNumber, @ExpireDate, Name, Surname |
| **HotelBookingInfo/@Start** | 是 | Date | 入住日期 |
| **HotelBookingInfo/@End** | 是 | Date | 退房日期 |
| **HotelBookingInfo/Price/PriceRange** | 是 | - | **可接受价格范围** (@Currency, @Minimum, @Maximum) |
| **HotelBookingInfo/HotelCode** | 是 | String | 酒店代码 |
| HotelBookingInfo/Status | 否 | String | 状态校验（OK/RQ），如设 OK 则变 RQ 时预订失败 |
| HotelBookingInfo/Preferences | 否 | - | 偏好设置 |
| AdvancedOptions/SendMailTo | 否 | String | 设为 "ALL" 可发送确认邮件 |

### 响应参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| **Reservation/@Locator** | 是 | String | **预订确认号**（如 TQ1TBG），需存储用于后续查询/取消 |
| **Reservation/@Status** | 是 | String | **预订状态**: PAG=已确认已付, CON=已确认, CAN/CAC=已取消, PRE/PDI=待确认(候补), QUO=报价, TAR=待信用卡付款 |
| Reservation/@PaymentDestination | 否 | Boolean | 是否由酒店通过客人信用卡收款 |
| Reservation/ExternalBookingReference | 否 | String | 自定义参考号 |
| Reservation/Holder/RelPax/@IdPax | 是 | Integer | 持有人 ID |
| Reservation/{Paxes} | 是 | - | 旅客列表（注意：系统会自动添加一个额外的 Holder 旅客） |
| Reservation/AgenciesData | 否 | - | 代理商信息 |
| **Items/HotelItem** | 是 | - | **预订项目** |
| HotelItem/@ItemId | 是 | String | 项目标识 |
| HotelItem/@Status | 是 | String | 项目状态: OK/AV=可用, RQ=候补, CA=已取消 |
| HotelItem/{Prices} | 是 | - | 价格明细 |
| HotelItem/{CancellationPolicy} | 否 | - | 取消政策 |
| HotelItem/HotelInfo | 是 | - | 酒店信息 (@Code, Name, HotelCategory, Address) |
| HotelItem/Board | 否 | String | 餐食计划 (@Type) |
| HotelItem/HotelRooms | 是 | - | 房间列表（Name, RoomCategory, RelPaxes） |
| HotelItem/ExternalInfo | 否 | - | 供应商信息（需权限）: Supplier, ExternalLocator, HotelConfirmationNumber |
| HotelItem/Comments | 否 | - | 酒店/供应商备注 (@Type: ELE=元素备注, HOT=酒店备注) |
| Payment/@Type | 否 | String | 付款方式: C=信用, B=银行, T=POS |

### XML 示例

```xml
<!-- 请求 -->
<HotelBooking>
  <HotelBookingRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <Paxes>
      <Pax IdPax="1">
        <Name>Holder Name</Name><Surname>Holder Surname</Surname>
        <PhoneNumbers><PhoneNumber>+34600555999</PhoneNumber></PhoneNumbers>
        <Email>holder@yourdomain.com</Email>
        <Document Type="DNI">43258752A</Document>
        <Age>50</Age>
      </Pax>
      <Pax IdPax="2"><Name>Name B</Name><Surname>Surname B</Surname><Age>30</Age></Pax>
      <Pax IdPax="3"><Name>Child</Name><Surname>Name</Surname><Age>8</Age></Pax>
    </Paxes>
    <Holder><RelPax IdPax="1"/></Holder>
    <ExternalBookingReference>YOUR_OWN_REFERENCE_123</ExternalBookingReference>
    <Elements>
      <HotelElement>
        <BookingCode>ya79dM4dS6R6EywV4XhfEvwI.....</BookingCode>
        <RelPaxesDist>
          <RelPaxDist><RelPaxes><RelPax IdPax="1"/></RelPaxes></RelPaxDist>
          <RelPaxDist><RelPaxes><RelPax IdPax="2"/><RelPax IdPax="3"/></RelPaxes></RelPaxDist>
        </RelPaxesDist>
        <HotelBookingInfo Start="2019-11-20" End="2019-11-22">
          <Price><PriceRange Minimum="0" Maximum="1003.57" Currency="EUR"/></Price>
          <HotelCode>JP046300</HotelCode>
        </HotelBookingInfo>
      </HotelElement>
    </Elements>
  </HotelBookingRQ>
</HotelBooking>

<!-- 响应（关键部分） -->
<Reservation Locator="TQ1TBG" Status="PAG">
  <Items>
    <HotelItem ItemId="148012" Status="OK" Start="2019-11-20" End="2019-11-22">
      <Prices><Price Type="S" Currency="EUR">
        <TotalFixAmounts Gross="1003.57" Nett="1003.57"/>
      </Price></Prices>
      <HotelInfo Code="JP046300"><Name>APARTAMENTOS ALLSUN PIL-LARI PLAYA</Name></HotelInfo>
      <Board Type="AD">Bed &amp; Breakfast</Board>
    </HotelItem>
  </Items>
</Reservation>
```

---

## 3. ReadBooking - 查询预订

**用途**: 根据预订确认号（Locator）查询预订详细信息。返回结构与 HotelBooking 响应完全一致。

### 请求参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| @Version | 是 | String | Web Service 版本 |
| @Language | 是 | String | 响应语言 |
| {Login} | 是 | - | 登录凭证 |
| ReadRequest/@ReservationLocator | 是 | String | 预订确认号 |
| AdvancedOptions/ShowBreakdownPrice | 否 | Boolean | 是否展示完整价格明细 |

### 响应参数

与 HotelBooking 响应结构完全一致（Reservation、HotelItem、Paxes、CancellationPolicy 等），请参考上方 HotelBooking 响应参数。

### XML 示例

```xml
<!-- 请求 -->
<ReadBooking>
  <ReadRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <ReadRequest ReservationLocator="TQ1TBG"/>
  </ReadRQ>
</ReadBooking>

<!-- 响应: 与 HotelBooking 响应结构一致 -->
<Reservation Locator="TQ1TBG" Status="PAG" Language="en">
  <Items>
    <HotelItem ItemId="148012" Status="OK" Start="2019-11-20" End="2019-11-22">
      <!-- 完整的价格、取消政策、酒店信息、房间信息等 -->
    </HotelItem>
  </Items>
</Reservation>
```

---

## 4. CancelBooking - 取消预订

**用途**: 取消整个预订或预订中的单个服务项。也支持仅查询取消费用而不实际取消（通过 `@OnlyCancellationFees="true"`）。

### 请求参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| @Version | 是 | String | Web Service 版本 |
| @Language | 是 | String | 响应语言 |
| {Login} | 是 | - | 登录凭证 |
| CancelRequest/@ReservationLocator | 是 | String | 预订确认号 |
| CancelRequest/@ItemId | 否 | Integer | 指定取消的服务项 ID（不填则取消整个预订） |
| **CancelRequest/@OnlyCancellationFees** | 否 | Boolean | **设为 true 仅查询取消费用，不实际取消** |
| AdvancedOptions/SendMailTo | 否 | String | 设为 "ALL" 发送确认邮件 |
| AdvancedOptions/ShowBreakdownPrice | 否 | Boolean | 是否展示完整价格明细 |
| AdvancedOptions/ShowCancelBreakdown | 否 | Boolean | 是否展示取消费用明细 |

### 响应参数

除 HotelBooking 标准响应结构外，还包含:

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| {Warnings} | 是 | - | **必须关注的取消警告**: warnCancelledAndCancellationCostRetrieved（已取消+费用已获取）, warnCancelledAndCancellationNotCalculated（已取消+费用未知）, warnCancellationCostRetrieved（仅查询费用）, warnCancellationNotCalculated（费用无法计算） |
| CancelInfo/BookingCodeState | 否 | String | 取消后预订状态 |
| CancelInfo/BookingCancelCost | 否 | Double | 取消费用金额 |
| CancelInfo/BookingCancelCostCurrency | 否 | String | 取消费用货币 |
| CancelInfo/BreakDown | 否 | - | 取消费用明细 |
| Reservation/@Status | 是 | String | 预订状态（取消后为 CAC 或 CAN） |

> **重要**: 如果收到 `warnCancelledAndCancellationNotCalculated`，不可假设取消免费，必须联系 Juniper 供应商确认。

### XML 示例

```xml
<!-- 实际取消请求 -->
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

<!-- 取消响应 -->
<Warnings>
  <Warning Code="warnCancelledAndCancellationCostRetrieved"
           Text="Cancellation cost retrieved. Reservation was cancelled."/>
  <CancelInfo>
    <BookingCodeState>CaC</BookingCodeState>
    <BookingCancelCost>0</BookingCancelCost>
    <BookingCancelCostCurrency>EUR</BookingCancelCostCurrency>
  </CancelInfo>
</Warnings>
<Reservation Locator="WZS1N6" Status="CAC">...</Reservation>
```

---

## 5. HotelModify - 修改预订（预检）

**用途**: 预检修改请求。检查预订修改是否可行，但不实际执行修改。返回可用的修改组合及 ModifyCode，供后续 HotelConfirmModify 使用。

### 可修改内容

- **预订级别**: 预订备注、代理参考号、主旅客姓名
- **酒店项目级别**: 项目备注、日期、旅客（增减）、房间（增减）、旅客姓名、餐食计划、房型

> **重要**: 并非所有预订都支持所有修改，取决于产品类型。直签合同通常支持较多修改，外部产品可能不支持。有取消费用的预订可能无法修改。

### 请求参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| @Version | 是 | String | Web Service 版本 |
| @Language | 是 | String | 响应语言 |
| {Login} | 是 | - | 登录凭证 |
| ReservationLocator | 是 | String | 预订确认号 |
| ReservationLocator/@ItemId | 是 | String | 酒店项目 ID |
| {Paxes} | 否 | - | 修改旅客信息或房间入住人数 |
| Holder/RelPax/@IdPax | 否 | Integer | 修改主旅客 |
| ExternalBookingReference | 否 | String | 修改外部参考号 |
| Comments/Comment | 否 | String | 修改备注 (@Type: RES 或 ELE) |
| SearchSementHotels/@Start | 否 | Date | 修改入住日期 |
| SearchSementHotels/@End | 否 | Date | 修改退房日期 |
| SearchSementHotels/Board/@Type | 否 | String | 修改餐食计划 |
| RelPaxesDist | 否 | - | 修改房间旅客分配 |
| RelPaxDist/Rooms/Room | 否 | - | 指定保留的房间（删除其他房间） |

### 响应参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| {Warnings} | 是 | - | 修改预告警告（如 warnModifyDates, warnModifyHolder, warnModifyDistribution, warnModifyBookingComments, warnModifyNotNecessary, warnDeleteRooms） |
| {Errors} | 否 | - | 如 NO_AVAIL_FOUND 表示修改不可行 |
| HotelModifyResult | 否 | - | 修改结果（仅在需要选择新组合时返回） |
| HotelOption/ModifyCode | 否 | String | **修改码**，用于 HotelConfirmModify |
| ModifyCode/@ExpirationDate | 否 | DateTime | 修改码过期时间 |
| HotelOption/Board, Prices, HotelRooms, CancellationPolicy | 否 | - | 新组合的详细信息 |

### XML 示例

```xml
<!-- 请求: 修改入住日期 -->
<HotelModify>
  <HotelModifyRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <ReservationLocator ItemId="123456">XXXXXX</ReservationLocator>
    <SearchSementHotels Start="2015-12-19" End="2015-12-20"/>
  </HotelModifyRQ>
</HotelModify>

<!-- 响应: 返回可用组合 -->
<Warnings>
  <Warning Code="warnModifyDates" Text="The dates will be modified. Before: [19/12/2015-21/12/2015] After: [19/12/2015-20/12/2015]"/>
</Warnings>
<Results>
  <HotelModifyResult>
    <HotelResult Code="JP15264" Start="2015-12-19" End="2015-12-20">
      <HotelOptions>
        <HotelOption Status="OK">
          <ModifyCode ExpirationDate="2015-11-16T17:01:39+01:00">fVxmnhm.....</ModifyCode>
          <Board Type="BB">Bed &amp; Breakfast</Board>
          <Prices><Price Type="S" Currency="EUR">
            <TotalFixAmounts Gross="249.76" Nett="225.23"/>
          </Price></Prices>
        </HotelOption>
      </HotelOptions>
    </HotelResult>
  </HotelModifyResult>
</Results>
```

---

## 6. HotelConfirmModify - 确认修改

**用途**: 在 HotelModify 确认修改可行后，实际执行预订修改。需传入 ModifyCode（如涉及组合变更）和修改信息。响应结构与 HotelBooking 一致，附带修改警告。

### 请求参数

| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| @Version | 是 | String | Web Service 版本 |
| @Language | 是 | String | 响应语言 |
| {Login} | 是 | - | 登录凭证 |
| ReservationLocator | 是 | String | 预订确认号 |
| ReservationLocator/@ItemId | 是 | String | 酒店项目 ID |
| {Paxes} | 否 | - | 修改旅客信息 |
| Holder/RelPax/@IdPax | 否 | Integer | 修改主旅客 |
| ExternalBookingReference | 否 | String | 修改外部参考号 |
| Comments/Comment | 否 | String | 修改备注 |
| **HotelElement/ModifyCode** | 条件必填 | String | **从 HotelModify 获得的修改码**（仅在涉及组合变更时需要） |
| HotelElement/RelPaxesDist | 否 | - | 修改后的房间旅客分配 |

### 响应参数

与 HotelBooking 响应结构一致，额外包含修改确认警告（如 `warnConfirmModifyBookingComments`, `warnConfirmModifyHolder`, `warnConfirmModifyDates` 等）。

### XML 示例

```xml
<!-- 请求: 确认修改备注 -->
<HotelConfirmModify>
  <HotelConfirmModifyRQ Version="1.1" Language="en">
    <Login Email="user@mydomain.com" Password="pass"/>
    <ReservationLocator ItemId="123456">XXXXXX</ReservationLocator>
    <Comments>
      <Comment Type="RES">General booking comments</Comment>
    </Comments>
  </HotelConfirmModifyRQ>
</HotelConfirmModify>

<!-- 响应 -->
<Warnings>
  <Warning Code="warnConfirmModifyBookingComments"
           Text="The booking comments have been modified. Before: [1234] After: [Reservation comments]"/>
</Warnings>
<Reservations>
  <Reservation Locator="XXXXXX" Status="PAG">
    <!-- 完整预订信息，与 HotelBooking 响应一致 -->
  </Reservation>
</Reservations>
```

---

## 附录: 取消政策规则类型

| Rule @Type | 说明 |
|------------|------|
| V | 按日期范围（@DateFrom - @DateTo）计费 |
| S | No-show 费用 |
| R | 按确认后天数计费 |

| 费用计算字段 | 说明 |
|-------------|------|
| @FixedPrice | 固定费用金额 |
| @PercentPrice | 按百分比收费 |
| @Nights | 按晚数收费 |
| @ApplicationTypeNights | 晚数计算方式: FirstNight / MostExpensiveNight / Average |

## 附录: 预订状态码

| 状态码 | 说明 |
|--------|------|
| PAG | 已确认并已付款 |
| CON | 已确认 |
| CAN / CAC | 已取消 |
| PRE / PDI | 候补（待确认） |
| QUO | 报价（需通过 WebService 付款的账户） |
| TAR | 待信用卡付款 |

---

# Part 4: FAQ & 认证流程


---

## 一、Hotel Frequently Asked Questions (常见问题)

### Q1: 可用性请求最多可以查询多少间房?

大多数供应商默认允许最多 **3间房** 的组合预订，但具体取决于供应商配置。如需更多房间，请联系 Juniper 供应商。

### Q2: 如何获取酒店代码 (Hotel Codes)?

- **HotelPortfolio**: 获取供应商连接下可用的 JPCode 列表（不同凭证可能有不同 portfolio）
- **HotelContent**: 获取每个酒店的详细模板信息
- **ZoneList**: 获取目的地映射关系，用于按目的地搜索时识别需要查询哪些酒店代码
- 连接多个 Juniper 供应商时，参考多供应商静态数据管理建议

### Q3: 按目的地搜索时，如何确定需要发送哪些酒店代码?

需要使用静态数据事务进行酒店映射，并通过 **ZoneList** 获取目的地的区域树结构。

**关键点**: 不能只关注直接目的地，必须递归包含所有下级子区域的酒店。例如搜索 "Miami City" 时，还需包含 Wynwood、Upper East Side、Miami Downtown、Brickell 等子区域的酒店。

### Q4: 系统能否过滤/阻止 On Request 类型的组合?

API 本身 **不提供** 过滤功能，需要在预订流程每个步骤自行处理:

| 步骤 | 处理方式 |
|------|---------|
| **HotelAvail** | 使用 `ShowOnlyAvailable` AdvancedOption 过滤 |
| **HotelBookingRules** | 检查 `warnStatusChanged` 警告和 `HotelOption@Status`，过滤从 OK 变为 RQ 的 |
| **HotelBooking** | 检查 `Status` 节点，阻止 RQ 状态的预订创建 |

### Q5: 多供应商管理静态数据有什么建议?

**仅适用于使用 JPCode 的供应商** (格式如 JP046300):

- 同一个 JPCode 在所有 Juniper 供应商中代表 **同一家酒店**
- 建议维护一个 **唯一的 JPCode 数据库**，避免重复存储
- 另建一张表记录 "供应商 <-> 可用 JPCode 列表" 的关系
- 不要向供应商请求其不可用的 JPCode（会导致大量无结果响应）

### Q6: 能否大量发送 HotelBookingRules 请求来补充可用性结果?

**绝对不允许!**

- HotelBookingRules 是高性能消耗事务，仅用于估价步骤 (pre-book)
- 滥用会影响整个 Juniper 供应商系统性能
- **违规将导致相关 IP 被自动、无通知地封禁**

### Q7: 多酒店可用性请求每次返回的结果数量不同，为什么?

这是 **正常行为**:
- 多酒店/按目的地搜索时，多个费率从多个来源独立请求
- 某些费率可能在截止时间内返回，也可能未返回
- 可用性超时由请求中的 `TimeOut` 参数或供应商配置决定（API 最大允许 **8秒**）
- **建议**: 使用 `HotelCheckAvail` 验证特定 RatePlanCode 的可用性，而非重新发送可用性请求

### Q8: JP_BOOK_OCCUPANCY_ERROR 错误是什么意思?

在 HotelBooking 中，乘客分配与 HotelAvail 中的不一致时触发。**必须保持一致的**:
- 房间数量
- 乘客顺序
- 乘客年龄（成人必须 >= 18岁，儿童必须保持原始年龄）

违反任何一项都会导致此错误。

### Q9: 如何识别需要在目的地支付的费用和税款?

在结果的 `AdditionalElements > HotelSupplements` 中查找 `DirectPayment="true"` 的补充项:

```xml
<HotelSupplement Code="1" DirectPayment="true" Amount="4.73" Currency="EUR">
    <Name>Mandatory Tax</Name>
    <Description>Payment at destination</Description>
</HotelSupplement>
```

- `DirectPayment="true"` = 需在目的地支付，**不包含** 在总价中
- 需展示 Amount、Currency、Name 和 Description

### Q10: 如何获取餐食类型 (Board Types) 列表?

- 通过 **HotelCatalogueData** 请求程序化获取
- **供应商特定**: 不同供应商的餐食类型代码不同，绝不能跨供应商使用
- **不要** 手动向供应商索要此信息（可能不准确/不完整）

### Q11: 能否通过 API 获取酒店确认号 (HCN)?

可以，在 `HotelBooking` 和 `ReadBooking` 响应的 `ExternalInfo > HotelConfirmationNumber` 节点中:

```xml
<ExternalInfo>
    <HotelConfirmationNumber>HEREGOESTHEHCN123</HotelConfirmationNumber>
</ExternalInfo>
```

**重要**: 是否可用完全取决于供应商:
- 供应商可能根本不提供 HCN
- 供应商可能在确认后 **48小时内** 才加载 HCN（需定期发送 ReadBooking 轮询）
- 需与供应商协调确认

### Q12: 可用性请求的超时是多少?

**最大 8 秒**。可通过 `TimeOut` AdvancedOption 自定义。

优化建议:
1. 正确使用 `TimeOut`，需扣除传输和处理时间
2. 使用 `ShowOnlyBestPriceCombination` 减少响应体积（仅多酒店请求）
3. 按酒店代码请求代替按目的地请求，控制每次请求的酒店数量
4. 关闭不必要的信息: `ShowHotelInfo=false`、`ShowBreakdownPrice=false`、`ShowCancellationPolicies=false`

### Q13: 预订确认请求的超时是多少?

**固定 180 秒**，不可自定义。

如需使用更短超时:
- 默认情况下，客户对供应商系统中确认的预订的取消费用负责
- 需与供应商达成协议，由供应商跟踪管理超时后确认的预订
- 需双方就取消费用责任达成一致

### Q14: 如何通过 Juniper API 购买迪士尼产品?

需先与供应商确认可销售迪士尼产品，然后可在 Orlando 地区酒店的可用性中获取。详见 Juniper 迪士尼产品专用文档。

---

## 二、Hotel Certification Process (认证流程)

### 2.1 概述

- 在完成集成开发后、首次连接生产环境前必须通过认证
- 连接新生产环境后需 **每年至少重新认证一次**（轻量版）
- 通过认证后获得生产环境访问权限（需在买方平台注册生产 IP）

### 2.2 预订流程认证 (Booking Flow Certification)

#### 2.2.1 预订流程要点

**可用性 (Availability)**:
- 所有必填字段必须正确
- 儿童年龄必须与预订时一致
- `CountryOfResidence` 为必填项，且必须与 HotelBooking 步骤中的值一致
- **必须** 接受 gzip 压缩响应（`Accept-Encoding: gzip, deflate`），否则返回 `COMPRESSION_REQUIRED` 错误
- RatePlanCode 不可拆分房间，如需单独预订某个房间，须重新发起 HotelAvail

**预订规则 (Pre-book / HotelBookingRules)**:
- 这是预订流程的 **必经步骤**
- 验证库存和价格（部分供应商使用动态分配，此步骤才真正确认）
- BookingCode 有效期 **10分钟**，过期需重新请求
- 如果取消政策不可用，**应假定不可退款**
- 必须展示酒店评论 (HOT 类型 Comment)，可能包含额外税费、警告等

**确认 (Confirmation / HotelBooking)**:
- 使用未过期的 BookingCode
- 填写所有 HotelBookingRules 返回的必填字段
- Holder 的 Nationality 必须与 Availability 的 CountryOfResidence 一致
- 强烈建议设置 `ExternalBookingReference` (自有参考号)
- 设置价格接受范围 `PriceRange` — 建议 Minimum=25% / Maximum=100%
- 保持整个流程使用相同的 Language
- 保持住宿日期、酒店代码、房间/乘客分配一致

#### 2.2.2 认证检查清单

| 项目 | 要求 |
|------|------|
| 预订流程描述 | 描述使用哪些事务、预计每日/每秒请求量、自定义超时长度 |
| 语言一致性 | 整个预订流程保持相同 Language |
| 国籍一致性 | CountryOfResidence = Holder Nationality，否则可能导致费率不可用或确认错误 |
| 取消政策 | 描述处理方式；注意取消政策时区可变，建议加 12小时安全边际 |
| 请求上下文 (@Context) | 必须发送: `FULLAVAIL`(目的地) 或 `SINGLEAVAIL`(单酒店) |
| 可用性超时 | 必须使用 TimeOut 参数，需扣除传输/处理时间 |
| 酒店代码搜索 | 不允许按目的地搜索，必须按酒店代码（最多 500个/请求） |
| 警告处理 | 正确处理 warnStatusChanged、价格变更等警告 |
| 必填字段处理 | 根据 HotelBookingRules 返回的必填字段填写（可能每个组合不同） |
| 状态处理 | 正确处理 CON/CAN/PRE 等状态，不能假设所有预订都是确认状态 |
| 自有参考号 | 发送 ExternalBookingReference |
| 价格接受范围 | 建议 25%-100% |
| BookingCode 过期 | 10分钟过期，需重新请求或限制自有步骤时间 |

#### 2.2.3 认证测试用例

需要对以下三种组合 **完成预订+查询+取消**:

1. **1间房**: 2成人
2. **2间房**: 第一间 2成人+1儿童(5岁)，第二间 1成人+2儿童(1岁和8岁)
3. **3间房**: 第一间 1成人，第二间 1成人+1儿童(17岁)，第三间 3成人

每个预订需提供完整 XML 日志:
- HotelAvail / HotelCheckAvail(如有) / HotelBookingRules / HotelBooking / ReadBooking / CancelBooking

还需展示预订确认页面截图，确认显示: 预订状态、价格、日期、持有人信息、所有乘客信息、酒店/房间/餐食名称。

### 2.3 静态数据认证 (Static Data Certification)

#### 要求 1: 更新频率
- 所有静态数据至少 **每15天更新一次**
- 必须处理已匹配记录的变更（不能只检查新增/删除）
- 需说明每种数据元素的更新频率

#### 要求 2: 酒店重要信息验证

从估价步骤开始，确保展示的酒店名称、地址、星级是经过验证的。两种方案:

**方案A — 直接使用 API 响应数据**:
- 估价页面使用 HotelBookingRules 响应中的酒店信息
- 确认/凭证页面使用 HotelBooking 响应中的酒店信息
- 不使用本地缓存的旧数据

**方案B — 与本地数据交叉验证**:
- 将 HotelBookingRules 返回的酒店信息与本地存储比对
- 发现差异时自行处理（中断流程/更新映射/展示差异让用户决定）
- 验证错误由集成方自行负责

#### 推荐: 预订流程中获取酒店模板

如需在预订流程中获取更多酒店静态数据，可用 RatePlanCode 或 BookingCode 调用 HotelContent:

```xml
<Hotel RatePlanCode="3WCCdKrNDmJB1QQRyLq2X3CEfL..."/>
```

---

## 三、补充交易: 预订修改 (Hotel Modification)

### 3.1 可修改内容

| 层级 | 可修改项 |
|------|---------|
| 预订级别 | 评论、代理参考号、主乘客姓名 |
| 酒店级别 | 行评论、日期、乘客(增删)、房间(增删)、乘客姓名、餐食、房间类型 |

### 3.2 重要限制

- **并非所有预订都可修改**，取决于产品类型（直签合同通常可修改，外部产品通常不可）
- 某些修改需要取消旧预订行并创建新行（不会取消整个预订）
- 有取消费用的预订行无法修改，需手动取消并重新预订

### 3.3 两步修改流程

**Step 1 — HotelModify** (检查是否可修改):
- 提交想要修改的信息
- 响应返回: 是否可修改 + 可用组合列表（每个带 `@ModifyCode`）
- 如果只修改评论/参考号/主乘客姓名，不需要 ModifyCode

**Step 2 — HotelConfirmModify** (确认修改):
- 提交修改信息 + 选择的 ModifyCode（如需要）
- 响应返回修改后的预订信息和变更警告

### 3.4 修改警告代码

| 警告代码 | 含义 |
|---------|------|
| `warnModifyBookingComments` | 评论将被修改 |
| `warnModifyHolder` | 主乘客将被修改 |
| `warnModifyDistribution` | 乘客分配将被修改 |
| `warnModifyDates` | 日期将被修改 |
| `warnModifyNotNecessary` | 无需修改（新信息与现有相同） |
| `warnDeleteRooms` | 房间将被删除 |
| `warnConfirmModifyBookingComments` | 评论已修改 |
| `warnConfirmDeleteRooms` | 房间已删除 |

---

## 四、预订取消 (CancelBooking) 补充

### 4.1 功能

- 可取消整个预订 (`@ReservationLocator`) 或单个服务项 (`@ItemId`)
- 可仅查询取消费用而不实际取消 (`@OnlyCancellationFees="true"`)

### 4.2 取消响应警告

| 警告代码 | 含义 |
|---------|------|
| `warnCancellationCostRetrieved` | 取消费用已获取，预订 **未取消** |
| `warnCancellationNotCalculated` | 取消费用无法计算，预订 **未取消** |
| `warnCancelledAndCancellationCostRetrieved` | 预订已取消，取消费用已获取 |
| `warnCancelledAndCancellationNotCalculated` | 预订已取消，但取消费用无法计算 |

### 4.3 关键警告

> **当收到 `warnCancelledAndCancellationNotCalculated` 时，绝不能假设没有费用! 必须联系 Juniper 供应商确认。**

### 4.4 CancelInfo 响应结构

- `BookingCodeState`: 预订最终状态 (如 `CaC` = 已取消)
- `BookingCancelCost`: 取消费用金额
- `BookingCancelCostCurrency`: 取消费用货币
- `BreakDown`: 取消费用明细

---

## 五、关键注意事项汇总

### RatePlanCode 行为
- 可用性响应中每个组合包含一个 RatePlanCode
- **不能拆分** 同一 RatePlanCode 下的房间
- 如只需预订部分房间，必须重新发起 HotelAvail
- RatePlanCode 用于 HotelBookingRules 请求
- BookingCode (从 HotelBookingRules 获取) 用于 HotelBooking，**有效期 10 分钟**

### 国籍/国家代码要求
- `CountryOfResidence` (HotelAvail) 和 Holder 的 `Nationality` (HotelBooking) **必须一致**
- 国籍变更可能导致费率不可用甚至确认错误
- 使用 ISO 国家代码 (如 `ES`, `DE`, `US`)

### 价格处理指南
- 使用 `PriceRange` 设置可接受价格范围: 建议 Minimum=25%, Maximum=100%
- 价格类型: `Gross`(含佣金总价), `Nett`(净价), `Service`(服务费), `ServiceTaxes`(税费)
- `ServiceTaxes@Included`: 指示税费是否已包含在总价中
- `DirectPayment="true"` 的补充项不包含在总价中，需在目的地支付
- HotelBookingRules 步骤会验证并更新价格，必须检查是否有变更

### 错误处理要点
- 必须接受 gzip 压缩响应，否则返回 `COMPRESSION_REQUIRED`
- 正确处理所有预订状态: `PAG`(已付), `CON`(已确认), `CAN`(已取消), `PRE`(预请求/On Request), `CaC`(取消已确认)
- 处理 `warnStatusChanged` — 可用状态可能从 OK 变为 RQ
- `NO_AVAIL_FOUND` — 修改时无可用组合
- `JP_BOOK_OCCUPANCY_ERROR` — 乘客分配不一致

### 边缘情况警告
1. **BookingCode 过期**: 10分钟过期，需重新获取并验证条件未变
2. **多酒店搜索结果不稳定**: 正常行为，受超时截止影响
3. **取消费用无法计算**: 不代表没有费用，必须联系供应商
4. **如果 ItemId 是预订中唯一/最后一项**: 必须取消整个预订 (Locator)
5. **取消政策时区可变**: 建议加 12 小时安全边际
6. **必填字段因组合而异**: 每次都要检查 HotelBookingRules 返回的 HotelRequiredFields
7. **预订确认超时 180秒固定**: 如需更短超时，需与供应商达成特殊协议
8. **大量发送 HotelBookingRules 将被封 IP**: 严禁用于非估价目的

---

# Part 5: 与本项目的对照

> 实现位置以 `juniper_ai/app/juniper/client.py`（生产 SOAP）、`mock_client.py`（测试）、`static_data.py` + `tasks/sync_static_data.py`（静态同步）为准；下文反映当前仓库状态。

## 接口实现状态

### 静态数据接口

| Juniper API | 用途 | 实现状态 | 说明 |
|---|---|---|---|
| **ZoneList** | 目的地树与可搜索区域 | `zone_list()` + `sync_zones` | 已对接；同步入 `zones` 表 |
| **HotelCatalogueData** | 星级、餐食等酒店侧目录 | `hotel_catalogue_data()` + `sync_catalogue` | 已对接；类目写入 `hotel_categories` / `board_types` |
| **GenericDataCatalogue** | 货币、国家等通用目录 | `generic_data_catalogue()` + `sync_catalogue` | 已对接（与 Common 文档一致） |
| **HotelPortfolio** | 全量酒店 JPCode（分页） | `hotel_portfolio()` + `sync_hotels` | 已对接；写入 `hotel_cache` |
| **HotelContent** | 酒店详情（≤25 家/次） | `hotel_content()` | 客户端已对接；**全量预同步**未纳入 `run_full_sync`，可按需任务化或按需调用 |
| **HotelList** | 按目的地列酒店 | 未实现 | 官方已弃用，以 HotelPortfolio + 映射为准 |
| **AccommodationPortfolio** | 非酒店住宿代码 | 未实现 | 低优先级 |
| **RoomList** | 房间 JRCode 列表 | 未实现 | 依赖供应商启用 room mapping |

### 预订流程接口

| Juniper API | 用途 | 实现状态 | 说明 |
|---|---|---|---|
| **HotelAvail** | 可用性搜索 | `hotel_avail()` | 已对接；主要为 Zone + 日期 + Pax；`CountryOfResidence` 已支持传入；`AdvancedOptions` / 按酒店代码批量等仍可增强 |
| **HotelAvailCalendar** | 日历可用性 | 未实现 | 低优先级 |
| **HotelFutureRates** | 未来费率 | 未实现 | 低优先级；常需供应商开通 |
| **HotelCheckAvail** | RatePlanCode 复核 | `hotel_check_avail()` | 已对接 |
| **HotelBookingRules** | BookingCode、取消规则、必填项 | `hotel_booking_rules()` | 已对接；应用层需处理 **BookingCode 过期** 与 **Warnings** |
| **HotelBooking** | 确认预订 | `hotel_booking()` | 已对接；支持 `BookingCode` / `ExternalBookingReference` 等 |
| **ReadBooking** | 按 Locator 读预订 | `read_booking()` | **SOAP 已对接**；产品侧可优先读本地订单表再回源 Juniper |
| **CancelBooking** | 取消 / 仅查取消费 | `cancel_booking(..., only_fees=...)` | 已对接 `OnlyCancellationFees` |
| **HotelModify** | 修改预检 | `hotel_modify()` | 已对接 |
| **HotelConfirmModify** | 确认修改 | `hotel_confirm_modify()` | 已对接 |
| **List bookings** | — | `list_bookings()` 抛 `NotImplementedError` | Juniper 无列表 SOAP；用本地 `GET /api/v1/bookings` |

## 待补齐工作（按优先级）

### P0 — 数据与产品闭环

1. **HotelContent 同步策略**: 按需拉取或后台分批写入 `hotel_content_cache`（若表已存在），与搜索/卡片展示对齐。
2. **按酒店代码的 HotelAvail**: 认证与性能场景下需映射后组批（≤500 酒店/请求）；当前客户端以 Zone 搜索为主。
3. **认证必填 Context**: 各请求按官方建议设置 `@Context`（见本文「酒店通用类型」与 Part 4）。

### P1 — 流程与健壮性

4. **BookingCode 过期**: 解析 `ExpirationDate`，超时前重新 `HotelBookingRules`。
5. **Warnings**: 统一处理 `warnPriceChanged`、`warnStatusChanged` 等（参见 [Warnings FAQ](https://api-edocs.ejuniper.com/api/faq/warnings)）。
6. **HotelBookingRules Extended information**: 可选补充费、PickUpPoints、Preferences 等与下单字段联动。
7. **取消政策展示**: 无结构化规则时按官方要求按 **不可退款** 处理。

### P2 — 增强功能

8. **HotelAvail 高级选项**: `ShowCancellationPolicies`、`ShowHotelInfo`、`UseCurrency`、`TimeOut` 等与响应体积、认证清单对齐。
9. **HotelAvailCalendar / HotelFutureRates**: 有日历/远期询价产品需求时再接入。
10. **AccommodationPortfolio / RoomList**: 非酒店或 JRCode 映射需求时再接入。
11. **RatePlanCode / BookingCode 字段长度**: 数据库与 API 模型预留足够长度。
12. **gzip**: `JuniperClient` 已设置 `Accept-Encoding: gzip`；全链路代理需避免剥离压缩。
