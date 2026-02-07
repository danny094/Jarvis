# Time MCP Server

Simple MCP server that provides current time information.

## Tools

### get_current_time
Returns current time in various formats:
- UTC
- Local
- ISO 8601
- Unix timestamp

**Arguments:**
- `format` (optional): "utc", "local", "iso", "timestamp", or "all" (default)

**Example:**
```json
{
  "format": "all"
}
```

### get_timezone
Returns system timezone information including:
- Timezone name
- UTC offset in hours
- DST status

**Arguments:** None

## Installation

Upload this ZIP file via TRION's MCP installer.

## Requirements

- Python 3.10+
- mcp package (installed automatically)
