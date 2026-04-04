# Hermes SSE Transport Patch

Hermes Agent v0.7.0 only supports StreamableHTTP for URL-based MCP servers, but HuskyLens V2 uses the older SSE transport. This patch adds SSE fallback support.

## What it changes

File: `~/.hermes/hermes-agent/tools/mcp_tool.py`

### 1. Add SSE flag (after existing flags ~line 92)

```python
_MCP_SSE_AVAILABLE = False
```

### 2. Add SSE import (inside the `try: from mcp import ...` block, after `_MCP_NEW_HTTP`)

```python
    # SSE transport fallback for older MCP servers (e.g. HuskyLens V2)
    try:
        from mcp.client.sse import sse_client
        _MCP_SSE_AVAILABLE = True
    except ImportError:
        pass
```

### 3. Add `_run_sse` method (before `_discover_tools`)

```python
    async def _run_sse(self, config: dict):
        """Run the server using legacy SSE transport (e.g. HuskyLens V2)."""
        if not _MCP_SSE_AVAILABLE:
            raise ImportError(
                f"MCP server '{self.name}' requires SSE transport but "
                "mcp.client.sse is not available."
            )
        url = config["url"]
        headers = dict(config.get("headers") or {})
        sampling_kwargs = self._sampling.session_kwargs() if self._sampling else {}
        if _MCP_NOTIFICATION_TYPES and _MCP_MESSAGE_HANDLER_SUPPORTED:
            sampling_kwargs["message_handler"] = self._make_message_handler()
        async with sse_client(url, headers=headers) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream, **sampling_kwargs) as session:
                await session.initialize()
                self.session = session
                await self._discover_tools()
                self._ready.set()
                await self._shutdown_event.wait()
```

### 4. Add SSE routing in the `run` method (modify the transport selection)

Replace:
```python
                if self._is_http():
```
With:
```python
                transport = config.get("transport", "auto")
                if transport == "sse":
                    await self._run_sse(config)
                elif self._is_http():
```

## Config

```yaml
mcp_servers:
  huskylens:
    url: "http://192.168.88.1:3000/sse"
    transport: sse  # This triggers the SSE path
    timeout: 30
    connect_timeout: 15
```

## Verify

```bash
hermes mcp test huskylens
# Should show: Connected, 10 tools discovered
```
