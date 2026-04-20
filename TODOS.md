# TODOS

## P3 — Agent Graph 单例转工厂模式

**What:** `graph.py` 的 `agent_graph = build_graph()` 单例改为 `build_graph(config)` 工厂，支持 per-IM 平台定制（不同工具集、不同 prompt）。

**Why:** 多 IM 平台接入时需要不同配置。当前只有一个合作方，单例够用。

**Effort:** S (human ~2h / CC ~10 min)

**Priority:** P3

**Depends on:** 第二个 IM 平台合作方出现时再做。

## P2 — Webhook SSRF DNS Rebinding 防护

**What:** webhook URL 验证需要在 DNS 解析后再检查 IP 是否私有。当前 `_validate_webhook_url` 只检查 IP 字面量和 hostname，不解析 DNS。攻击者可注册域名指向 127.0.0.1 或 169.254.169.254 绕过防护。

**Why:** 安全加固。当前 SSRF 防护对 DNS rebinding 攻击无效。

**Effort:** S (human ~2h / CC ~15 min)

**Priority:** P2

**Depends on:** 无。可独立修复。
