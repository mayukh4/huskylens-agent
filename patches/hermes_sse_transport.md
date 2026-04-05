# Hermes SSE Transport Patch (Legacy)

> **Note**: This patch is no longer needed for TARS v3.0+. The system now communicates with HuskyLens V2 directly via I2C binary protocol, bypassing the MCP server entirely. This document is kept for reference only.

## Background

Hermes Agent v0.7.0 only supported StreamableHTTP for URL-based MCP servers, but HuskyLens V2's MCP server used SSE transport. This patch added SSE fallback support to Hermes.

## Why It Was Replaced

- USB MCP polling caused HuskyLens firmware crashes (green screen) after 15-20 min
- Firmware v1.2.2 had broken set_algorithm via MCP
- Pi 5 UART regression (kernel 6.6.51+) made direct UART unusable
- I2C binary protocol is lightweight, stable, and crash-free
