from core.bridge import get_bridge

# Force initialization
bridge = get_bridge()

# Check if ControlLayer has MCP Hub
print('🔍 CHECKING MCP HUB INJECTION:')
print('')

control = bridge.control
if hasattr(control, 'mcp_hub'):
    hub = control.mcp_hub
    if hub:
        print('✅ ControlLayer HAS MCP Hub connected!')
        print(f'   MCP Hub type: {type(hub).__name__}')
        
        # Try to list tools
        try:
            tools = hub.list_tools()
            st_tools = [t for t in tools if 'think' in t.get('name', '').lower()]
            print(f'   Total MCP tools: {len(tools)}')
            if st_tools:
                print(f'   ✅ Sequential Thinking tools found: {len(st_tools)}')
                for tool in st_tools:
                    print(f'      - {tool.get("name")}: {tool.get("description", "")[:50]}...')
            else:
                print('   ⚠️  No Sequential Thinking tools found')
                print('   Available tools:')
                for tool in tools[:5]:
                    print(f'      - {tool.get("name")}')
        except Exception as e:
            print(f'   ⚠️  Could not list tools: {e}')
    else:
        print('⚠️  ControlLayer has mcp_hub attribute but it is None')
else:
    print('❌ ControlLayer does NOT have mcp_hub attribute')
