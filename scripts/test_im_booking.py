#!/usr/bin/env python3
"""
模拟上游 IM 平台调用 JuniperAI Agent 预订酒店的完整流程。

使用方式:
    python scripts/test_im_booking.py

模拟场景:
    一个 IM 平台用户（张三）想在巴塞罗那订一家四星级酒店，
    4月15日入住，4月18日退房。通过对话完成搜索、选择、预订。
"""

import httpx
import json
import sys
import time

# ============================================================
# 配置
# ============================================================
BASE_URL = "http://127.0.0.1:8000"
API_KEY = "test-api-key-1"  # .env 中配置的 API Key
IM_USER_ID = "im-user-zhangsan-001"  # IM 平台方的用户标识

HEADERS = {
    "X-API-Key": API_KEY,
    "X-External-User-Id": IM_USER_ID,
    "Content-Type": "application/json",
}


def print_step(step: int, title: str):
    print(f"\n{'='*60}")
    print(f"  Step {step}: {title}")
    print(f"{'='*60}")


def print_response(label: str, data: dict):
    print(f"\n  [{label}]")
    print(f"  {json.dumps(data, indent=2, ensure_ascii=False)}")


def print_agent(text: str):
    print(f"\n  🤖 Agent: {text}")


def print_user(text: str):
    print(f"\n  👤 用户: {text}")


def main():
    transport = httpx.HTTPTransport(local_address="0.0.0.0")
    client = httpx.Client(base_url=BASE_URL, timeout=120.0, transport=transport)

    # ============================================================
    # Step 0: 健康检查
    # ============================================================
    print_step(0, "健康检查")
    try:
        r = client.get("/api/v1/health")
        if r.status_code == 200:
            print_response("健康状态", r.json())
        else:
            print(f"  ❌ 服务不可用: {r.status_code}")
            sys.exit(1)
    except httpx.ConnectError:
        print("  ❌ 无法连接到 http://localhost:8000，请确认服务已启动")
        sys.exit(1)

    # ============================================================
    # Step 1: 创建对话
    # ============================================================
    print_step(1, "创建对话会话")
    r = client.post(
        "/api/v1/conversations",
        headers=HEADERS,
        json={"external_user_id": IM_USER_ID},
    )
    if r.status_code != 200:
        print(f"  ❌ 创建对话失败: {r.status_code} {r.text}")
        sys.exit(1)

    conv = r.json()
    conversation_id = conv["id"]
    print_response("对话创建成功", conv)
    print(f"\n  📝 conversation_id = {conversation_id}")

    # ============================================================
    # Step 2: 用户发送第一条消息 — 搜索酒店
    # ============================================================
    print_step(2, "搜索酒店")
    user_msg = "帮我搜一下巴塞罗那的酒店，4月15日入住，4月18日退房，2个大人"
    print_user(user_msg)

    print("\n  ⏳ Agent 思考中...")
    start = time.time()
    r = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=HEADERS,
        json={"content": user_msg},
    )
    elapsed = time.time() - start

    if r.status_code != 200:
        print(f"  ❌ 发送消息失败: {r.status_code} {r.text}")
        sys.exit(1)

    msg = r.json()
    print_agent(msg["text"][:500] + ("..." if len(msg["text"]) > 500 else ""))
    print(f"\n  ⏱️  响应耗时: {elapsed:.1f}s")

    # ============================================================
    # Step 3: 用户选择一家酒店 — 查看可用性
    # ============================================================
    print_step(3, "选择酒店并查看可用性")
    user_msg = "第一家看起来不错，帮我查一下它的可用性和取消政策"
    print_user(user_msg)

    print("\n  ⏳ Agent 思考中...")
    start = time.time()
    r = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=HEADERS,
        json={"content": user_msg},
    )
    elapsed = time.time() - start

    if r.status_code != 200:
        print(f"  ❌ 发送消息失败: {r.status_code} {r.text}")
        sys.exit(1)

    msg = r.json()
    print_agent(msg["text"][:500] + ("..." if len(msg["text"]) > 500 else ""))
    print(f"\n  ⏱️  响应耗时: {elapsed:.1f}s")

    # ============================================================
    # Step 4: 用户确认预订
    # ============================================================
    print_step(4, "确认预订")
    user_msg = "好的，帮我预订这家酒店。我叫张三，邮箱 zhangsan@example.com"
    print_user(user_msg)

    print("\n  ⏳ Agent 思考中...")
    start = time.time()
    r = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=HEADERS,
        json={"content": user_msg},
    )
    elapsed = time.time() - start

    if r.status_code != 200:
        print(f"  ❌ 发送消息失败: {r.status_code} {r.text}")
        sys.exit(1)

    msg = r.json()
    print_agent(msg["text"][:500] + ("..." if len(msg["text"]) > 500 else ""))
    print(f"\n  ⏱️  响应耗时: {elapsed:.1f}s")

    # ============================================================
    # Step 5: 查询预订记录
    # ============================================================
    print_step(5, "查询预订记录")
    r = client.get("/api/v1/bookings", headers=HEADERS)

    if r.status_code == 200:
        bookings = r.json()
        if bookings:
            print(f"\n  ✅ 找到 {len(bookings)} 笔预订:")
            for b in bookings:
                print(f"     - {b.get('hotel_name', 'N/A')} | {b.get('status')} | {b.get('check_in')} ~ {b.get('check_out')} | {b.get('total_price')} {b.get('currency')}")
        else:
            print("\n  📭 暂无预订记录（预订可能尚未写入数据库）")
    else:
        print(f"  ❌ 查询预订失败: {r.status_code} {r.text}")

    # ============================================================
    # Step 6: 查询用户偏好
    # ============================================================
    print_step(6, "设置并查询用户偏好")

    # 设置偏好
    r = client.put(
        f"/api/v1/users/{IM_USER_ID}/preferences",
        headers=HEADERS,
        json={
            "star_rating": "4 stars",
            "board_type": "Bed & Breakfast",
            "budget_range": "€100-200/night",
        },
    )
    if r.status_code == 200:
        print_response("偏好设置成功", r.json())
    else:
        print(f"  ❌ 设置偏好失败: {r.status_code} {r.text}")

    # 查询偏好
    r = client.get(
        f"/api/v1/users/{IM_USER_ID}/preferences",
        headers=HEADERS,
    )
    if r.status_code == 200:
        print_response("当前偏好", r.json())
    else:
        print(f"  ❌ 查询偏好失败: {r.status_code} {r.text}")

    # ============================================================
    # Step 7: 继续对话 — 测试偏好感知
    # ============================================================
    print_step(7, "用偏好再次搜索（验证偏好是否生效）")
    user_msg = "再帮我搜一下马德里的酒店，同样的日期"
    print_user(user_msg)

    print("\n  ⏳ Agent 思考中...")
    start = time.time()
    r = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=HEADERS,
        json={"content": user_msg},
    )
    elapsed = time.time() - start

    if r.status_code != 200:
        print(f"  ❌ 发送消息失败: {r.status_code} {r.text}")
        sys.exit(1)

    msg = r.json()
    print_agent(msg["text"][:500] + ("..." if len(msg["text"]) > 500 else ""))
    print(f"\n  ⏱️  响应耗时: {elapsed:.1f}s")

    # ============================================================
    # 总结
    # ============================================================
    print(f"\n{'='*60}")
    print(f"  ✅ 完整预订流程测试完成")
    print(f"{'='*60}")
    print(f"  对话 ID:    {conversation_id}")
    print(f"  IM 用户:    {IM_USER_ID}")
    print(f"  认证方式:   API Key + X-External-User-Id")
    print(f"  LLM:        OpenAI gpt-4o")
    print(f"  酒店供给:   Mock 数据（巴塞罗那 5 家酒店）")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
