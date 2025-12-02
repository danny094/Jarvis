**📡 MCP-Hub**

A central router for Model Context Protocol (MCP) tools
The MCP Hub consolidates multiple MCP servers into a single endpoint, manages priorities, health status, and tool routing—thus providing the foundation for complex multi-agent or multi-tool systems.
It acts as a central hub between LLM clients and any MCP services.



***

***🚀 Features***

🔹 1.  Central MCP Registry

The hub maintains a configurable list of registered MCP servers:

1. Storage servers (e.g., SQL memory)
2. Thinking/Reasoning servers
3. Code executors
4. Validators
5. Custom tools
6. Legacy HTTP MCP services

Activated servers can be dynamically switched on or off.

***

***2. Automatic tool routing***

The hub receives tool requests in the following format:
```{
  "tool": "memory_search",
  "arguments": {
    "query": "Wohnort",
    "limit": 5
  }
}
```

Then the following happens automatically:

1. All active MCP servers are searched.
2. The server providing the tool is selected.
3. The tool is forwarded there.
4. The result is sent back to the client.

If multiple servers offer a tool, priority is determined.
***

***🔹 3. Health-Checks & Fallbacks***

The hub monitors every MCP server:

* Faulty servers → automatically ignored
* Unreachable URLs → skipped
* Optional retry mechanism

If a tool cannot be found, the hub can:
* Try alternative servers
* Return a standardized error message
* Optionally trigger default tools
***

***🔹 4. Legacy-HTTP-Support***

If an MCP server does not use streamable HTTP or an official MCP structure, the hub offers:
* Fallback to JSON-RPC over HTTP
* Payload transformation
* Response parsing
This also makes older or unconventional MCP implementations compatible.
***

***🔹 5. Saubere JSON-RPC-Schnittstelle***

Der Hub kapselt alle Tools in standardisierte Endpoints:
* ```POST /mcp/hub/call```

Input:

```{
  "tool": "fact_get",
  "arguments": {
    "subject": "Danny"
  }
}
```
Output:

```{
  "ok": true,
  "tool": "fact_get",
  "response": { ... }
}
```
***

***⚙️ configuration***

The hub reads the registry:
* `mcp_registry.json`

```{
  "sql-memory": {
    "url": "http://localhost:8081/mcp",
    "enabled": true,
    "description": "Vector Memory Server"
  },
  "sequential-thinking": {
    "url": "http://localhost:8085/mcp",
    "enabled": true
  }
}
```
Optionally you can:
* Prioritize tools
* Disable specific MCP servers
* Configure timeouts
* Define local tools
***
🧪 Example: Tool call

Inquiry: 
```POST /mcp/hub/call```
Body:
```{
  "tool": "memory_save",
  "arguments": {
    "conversation_id": "abc123",
    "content": "Ich wohne am Bodensee."
  }
}
```
Answer:
```{
  "ok": true,
  "server": "sql-memory",
  "response": {
    "status": "ok",
    "id": 42,
    "layer": "ltm"
  }
}
```

