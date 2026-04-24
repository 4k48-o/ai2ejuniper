# imToolTest

酒店预订 **IM 风格聊天前端**，用于与 **JuniperAI 后端 Agent** 联调。请求经 Vite 代理到本机 `8000` 端口的 FastAPI；Juniper SOAP 由 `JUNIPER_USE_MOCK=true` 时使用 **`MockJuniperClient`**，无需白名单网络。

## 快速开始

1. 按仓库根目录说明启动 **Postgres** 并做好 **DB 迁移**与（建议）**静态酒店数据同步**。  
2. 配置根目录 `.env`：`API_KEYS` 含 `test-api-key-1`，并配置 **LLM** API Key。  
3. 启动后端：`uvicorn juniper_ai.app.main:app --reload --host 0.0.0.0 --port 8000`  
4. 本目录：`npm ci && npm run dev`  
5. 打开浏览器，选测试用户，开始对话。

详细步骤、验证命令与排障见 **[IM_DEV_CHECKLIST.md](./IM_DEV_CHECKLIST.md)**。

## 技术栈

React 18、TypeScript、Vite、Tailwind CSS v4（`@tailwindcss/vite`）。

## 相关文件

| 路径 | 作用 |
|------|------|
| `src/api/client.ts` | `X-API-Key` / `X-External-User-Id`，会话与发消息 |
| `vite.config.ts` | `/api` → `http://localhost:8000` |
| `src/mock/*` | 离线状态机 + 假数据（可选；主流程已接真后端） |
