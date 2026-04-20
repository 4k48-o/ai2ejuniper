"""LangGraph agent graph for hotel booking conversations."""

import logging
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from juniper_ai.app.agent.prompts.system import build_system_prompt
from juniper_ai.app.agent.tools.book_hotel import book_hotel
from juniper_ai.app.agent.tools.booking_rules import get_booking_rules
from juniper_ai.app.agent.tools.cancel_booking import cancel_booking
from juniper_ai.app.agent.tools.cancel_estimate import estimate_cancellation_fees
from juniper_ai.app.agent.tools.check_availability import check_availability
from juniper_ai.app.agent.tools.confirm_modify import confirm_modify
from juniper_ai.app.agent.tools.list_bookings import list_bookings
from juniper_ai.app.agent.tools.modify_booking import modify_booking
from juniper_ai.app.agent.tools.read_booking import read_booking
from juniper_ai.app.agent.tools.search_hotels import search_hotels
from juniper_ai.app.agent.tools.static_lookup_tools import (
    explain_catalog,
    list_hotels_for_zones,
    resolve_destination,
)
from juniper_ai.app.config import settings
from juniper_ai.app.llm.client import get_llm_client

logger = logging.getLogger(__name__)

ALL_TOOLS = [
    resolve_destination,
    list_hotels_for_zones,
    explain_catalog,
    search_hotels,
    check_availability,
    get_booking_rules,
    book_hotel,
    read_booking,
    list_bookings,
    cancel_booking,
    estimate_cancellation_fees,
    modify_booking,
    confirm_modify,
]


class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    conversation_id: str
    preferences: dict
    language: str


def _get_llm_with_tools():
    """Get the LLM bound with hotel booking tools."""
    client = get_llm_client()
    return client.bind_tools(ALL_TOOLS)


async def agent_node(state: AgentState) -> dict:
    """Main agent node: invoke LLM with tools."""
    llm = _get_llm_with_tools()

    # Build system message with preferences
    system_prompt = build_system_prompt(
        preferences=state.get("preferences", {}),
        language=state.get("language", "en"),
    )

    # Ensure system message is first
    messages = state["messages"]
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + list(messages)
    else:
        messages = [SystemMessage(content=system_prompt)] + list(messages[1:])

    # Truncate to last N messages (keep system message)
    max_messages = settings.max_message_history
    if len(messages) > max_messages + 1:
        messages = [messages[0]] + list(messages[-(max_messages):])

    response = await llm.ainvoke(messages)
    return {"messages": [response]}


def should_continue(state: AgentState) -> str:
    """Determine if we should continue to tools or end."""
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END


def build_graph() -> StateGraph:
    """Build the LangGraph agent graph."""
    tool_node = ToolNode(ALL_TOOLS)

    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)

    graph.set_entry_point("agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

    return graph.compile()


# Compiled graph singleton
agent_graph = build_graph()
