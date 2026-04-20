# imToolTest — 酒店预定人机交互前端开发计划

## 1. 项目目标

构建一个基于 React 的酒店预定聊天界面，模拟真实 IM 工具中的人机交互体验。用户通过对话方式完成酒店搜索、查看详情、预定、取消等操作。由于尚未获得 Juniper API 沙箱，全程使用 Mock 数据驱动。

## 2. 技术栈

| 类别 | 选型 | 理由 |
|------|------|------|
| 框架 | React 18 + TypeScript | 类型安全，生态成熟 |
| 构建工具 | Vite | 快速启动，开箱即用 |
| UI 组件 | Tailwind CSS | 快速定制聊天界面样式 |
| 状态管理 | React useState/useReducer | 项目规模不大，不需要 Redux |
| Mock 数据 | 本地 JSON + 模拟延迟 | 对齐后端 mock_client.py 的数据结构 |

## 3. 核心功能

### 3.1 聊天界面
- 消息列表：支持用户消息和 AI 助手消息的气泡展示
- 输入框：文本输入 + 发送按钮
- 消息类型：纯文本、酒店卡片（富文本）、确认按钮、状态通知

### 3.2 酒店搜索流程
- 用户输入搜索意图（如"帮我找巴塞罗那的酒店"）
- AI 回复引导用户补充信息（入住日期、退房日期、人数）
- 展示搜索结果卡片列表（酒店名、星级、价格、房型、餐食类型）

### 3.3 酒店预定流程
- 用户选择酒店 → AI 展示可用性确认和价格
- AI 展示取消政策和最终价格
- 用户确认预定 → 填写入住人信息（姓名、邮箱）
- 预定成功 → 展示预定确认卡片（预定号、酒店、日期、金额）

### 3.4 预定管理
- 查询已有预定
- 取消预定（带确认弹窗）
- 修改预定日期

## 4. Mock 数据设计

对齐后端 `juniper_ai/juniper/mock_client.py` 中的 5 家巴塞罗那酒店：

```typescript
interface Hotel {
  hotel_code: string;
  hotel_name: string;
  star_rating: number;
  location: string;
  price_per_night: number;
  currency: string;
  room_type: string;
  board_type: string;       // BB / RO / HB / FB
  rate_plan_code: string;
  cancellation_policy: string;
}

interface Booking {
  booking_id: string;        // JNP-XXXXXXXX
  hotel_name: string;
  check_in: string;
  check_out: string;
  guest_name: string;
  guest_email: string;
  total_price: number;
  currency: string;
  status: 'confirmed' | 'cancelled' | 'modified';
}
```

### Mock 对话引擎
- 基于关键词匹配 + 状态机驱动对话流转
- 状态：`idle` → `collecting_info` → `showing_results` → `checking_availability` → `confirming_booking` → `booking_complete`
- 模拟 AI 响应延迟（500ms-1500ms）

## 5. 页面结构

```
imToolTest/
├── PLAN.md                  # 本文件
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
├── index.html
├── public/
└── src/
    ├── main.tsx             # 入口
    ├── App.tsx              # 根组件
    ├── components/
    │   ├── ChatWindow.tsx       # 聊天主窗口
    │   ├── MessageList.tsx      # 消息列表
    │   ├── MessageBubble.tsx    # 单条消息气泡
    │   ├── HotelCard.tsx        # 酒店搜索结果卡片
    │   ├── BookingCard.tsx      # 预定确认卡片
    │   ├── InputBar.tsx         # 输入栏
    │   └── ConfirmDialog.tsx    # 确认对话框
    ├── mock/
    │   ├── hotels.ts            # Mock 酒店数据
    │   ├── chatEngine.ts        # Mock 对话引擎（状态机）
    │   └── bookingStore.ts      # Mock 预定存储
    ├── types/
    │   └── index.ts             # TypeScript 类型定义
    └── styles/
        └── index.css            # Tailwind 入口 + 自定义样式
```

## 6. 对话状态机设计

```
                  ┌──────────────┐
                  │    idle      │
                  └──────┬───────┘
                         │ 用户发送搜索意图
                  ┌──────▼───────┐
                  │collecting_info│ ◄── AI 追问缺失信息
                  └──────┬───────┘     (日期/人数/目的地)
                         │ 信息收集完毕
                  ┌──────▼───────┐
                  │showing_results│ ── 展示酒店卡片列表
                  └──────┬───────┘
                         │ 用户选择酒店
                  ┌──────▼────────────┐
                  │checking_availability│ ── 检查可用性和价格
                  └──────┬────────────┘
                         │ 可用
                  ┌──────▼───────────┐
                  │confirming_booking │ ── 展示政策，收集姓名/邮箱
                  └──────┬───────────┘
                         │ 用户确认
                  ┌──────▼───────────┐
                  │ booking_complete  │ ── 展示预定确认卡片
                  └──────────────────┘
                         │
                         ▼ 回到 idle，可继续新搜索或管理预定
```

## 7. 开发阶段

### Phase 1: 基础骨架（Day 1）
- [x] 初始化 Vite + React + TypeScript + Tailwind 项目
- [ ] 搭建 ChatWindow、MessageList、MessageBubble、InputBar 组件
- [ ] 实现基本消息收发（纯文本）

### Phase 2: Mock 对话引擎（Day 2）
- [ ] 实现状态机驱动的 chatEngine
- [ ] 关键词识别：搜索意图、日期解析、酒店选择、确认/取消
- [ ] 对接 mock 酒店数据

### Phase 3: 富文本消息（Day 3）
- [ ] HotelCard 组件：星级、价格、餐食标签、选择按钮
- [ ] BookingCard 组件：预定号、详情摘要
- [ ] ConfirmDialog 组件：取消预定确认

### Phase 4: 预定管理（Day 4）
- [ ] 查询已有预定
- [ ] 取消预定流程
- [ ] 修改预定日期流程
- [ ] bookingStore 内存存储

### Phase 5: 体验优化（Day 5）
- [ ] AI 打字动画效果
- [ ] 消息滚动到底部
- [ ] 响应式布局适配移动端
- [ ] 错误状态处理

## 8. 后续衔接

当 Juniper API 沙箱就绪后：
1. 将 `mock/chatEngine.ts` 替换为调用后端 `POST /api/v1/conversations/{id}/messages` 接口
2. 使用 SSE 流式接口 (`/messages/stream`) 实现实时响应
3. Mock 数据层可保留作为离线开发/测试的 fallback
