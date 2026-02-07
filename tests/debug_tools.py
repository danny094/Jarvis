from mcp.hub import get_hub
import json
from utils.logger import log_info

def list_all_tools():
    hub = get_hub()
    hub.initialize()
    
    tools = hub.list_tools()
    print(f"\nDistcovered {len(tools)} tools:")
    for tool in tools:
        print(f"- {tool['name']} (MCP: {hub.get_mcp_for_tool(tool['name'])})")
        # print(f"  Desc: {tool.get('description', '')}")

    mcps = hub.list_mcps()
    print(f"\nMCP Status:")
    for m in mcps:
        print(f"- {m['name']}: {m['tools_count']} tools, Online: {m['online']}")

if __name__ == "__main__":
    list_all_tools()
