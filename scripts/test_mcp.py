#!/usr/bin/env python3
"""Test HuskyLens MCP connectivity and list available tools."""

import asyncio
from mcp.client.sse import sse_client
from mcp import ClientSession

async def test():
    print("Connecting to HuskyLens MCP at http://192.168.88.1:3000/sse ...")
    async with sse_client("http://192.168.88.1:3000/sse") as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print(f"\nConnected! {len(tools.tools)} tools available:\n")
            for t in tools.tools:
                desc = (t.description or "")[:60]
                print(f"  {t.name:35s} {desc}")

            # Quick vision test
            print("\n--- Quick vision test ---")
            result = await session.call_tool("get_recognition_result", {})
            for item in result.content:
                text = item.text if hasattr(item, "text") else str(item)
                print(f"  {text[:200]}")

asyncio.run(test())
