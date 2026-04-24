# imToolTest + Agent 本地联调清单

通过 **imToolTest** 对话走真实 **FastAPI + LangGraph Agent**，Juniper 侧使用 **`MockJuniperClient`**（`JUNIPER_USE_MOCK=true`），无需白名单网络。

---

## 一、环境与配置

| 步骤 | 说明 |
|------|------|
| [X] **Postgres** | 与 `database_url` 一致（默认见 `juniper_ai/app/config.py`；仓库根 `docker-compose.yml` 可起库）。 |
| [X] **迁移** | 在项目根执行 `alembic upgrade head`（或团队约定命令），表结构就绪。 |
| [ ] **静态酒店缓存** | Agent 搜索会按 zone 从 DB 取 `jp_codes` 再调 `hotel_avail`。Mock 目录含 `JP046300`（Palma）与 `HOT001`…（巴塞罗那）；**若搜某城市 0 结果，需确认该区已 sync 酒店列表**。 |
| [ ] **`JUNIPER_USE_MOCK=true`** | **以根目录 `.env` 为准**（会覆盖代码默认值）。若为 `false`，日志会出现 `Juniper supplier: LIVE SOAP` 与 `HotelAvail: … batches`，并连 `xml-uat` —— 与 imToolTest 离线预期不符。改完后**重启 uvicorn**；启动行应含 **`Juniper supplier: MOCK`**。 |
| [ ] **`API_KEYS`** | 须包含 `test-api-key-1`（与 `src/api/client.ts` 中 `X-API-Key` 一致）。后端默认与 `.env.example` 已对齐为 `test-api-key-1,test-api-key-2`。若本地 `.env` 仍只有旧值 `test-api-key`，请改为包含 `test-api-key-1`，否则前端会 401。 |
| [ ] **LLM** | 配置 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`（及 `llm_provider`），否则 Agent 无法推理。 |

---

## 二、启动顺序

1. **后端**（仓库根目录）  
   `uvicorn juniper_ai.app.main:app --reload --host 0.0.0.0 --port 8000`

2. **前端**  
   `cd imToolTest && npm ci && npm run dev`  
   Vite 将 `/api` 代理到 `http://localhost:8000`（见 `vite.config.ts`）。

3. 浏览器打开终端提示的本地地址（常见 `http://localhost:5173`），**选择测试用户**，在聊天框发消息。

---

## 三、冒烟验证

| 步骤 | 说明 |
|------|------|
| [ ] **健康检查** | `curl -s http://localhost:8000/api/v1/health` 返回 `healthy`。 |
| [ ] **创建会话** | `POST /api/v1/conversations`，Header：`X-API-Key: test-api-key-1`，Body：`{"external_user_id":"user-alice"}`。 |
| [ ] **发消息** | `POST /api/v1/conversations/{id}/messages`，Header 同上并加 `X-External-User-Id: user-alice`，Body：`{"content":"你好"}`，应返回 assistant 文本。 |
| [ ] **前端** | 选预设用户后发一句，无「连接后端失败」且出现助手回复。 |

---

## 四、推荐对话场景（Mock）

- **巴塞罗那**：例如「帮我找巴塞罗那 4 月 15 到 18 号、2 大人的酒店」——依赖 DB 中该区 `jp_codes` 与 mock 中 `HOT001`… 交集。  
- **Palma / JP046300**：`mock_client` 已内置 **UAT 形态**一条（`MOCK_RPC_IM_JP046300_SA`，291.52 EUR，Room Only）；DB 中 Palma 列表含 `JP046300` 时，搜 Mallorca/Palma 应能出结果并走完整预订链路。

---

## 五、常见问题

| 现象 | 处理 |
|------|------|
| **401** | 检查 `API_KEYS` 是否包含 `test-api-key-1`，与前端 `client.ts` 一致。 |
| **400 X-External-User-Id** | API Key 模式下发消息必须带 `X-External-User-Id`（前端已带）。 |
| **搜不到酒店** | 多为 zone 下无缓存 JPCode，或 **缓存 JP 与 mock 目录无交集**（例如 Palma 区里没有 `JP046300`）；先 `run_static_data_sync`，或看后端日志 `search_hotels ZERO_RESULTS`。Mock 下工具会返回以 **`[Mock Juniper]`** 开头的说明，勿与真实 SOAP/网络故障混淆。 |
| **只输入「Palma」解析错城** | 供应商有多座同名 CTY；代码已将 **`Palma` → `Palma de Mallorca`**（`JPD054557`）。若仍异常，可显式说 **Palma de Mallorca** 或 **马略卡帕尔马**。 |
| **Agent 英文固定回复 / 报错** | 查后端日志；多为 LLM 配额、模型名或网络。 |

---

## 六、与纯前端 Mock 的关系

`src/mock/chatEngine.ts`、`src/mock/hotels.ts` 为**离线状态机演示**，当前主流程已接 **`sendMessage` → 后端 Agent**。保留可作 UI 原型 fallback；以本清单「真后端 + Mock Juniper」为准做集成测试。
