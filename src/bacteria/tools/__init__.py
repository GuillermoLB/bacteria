from claude_agent_sdk import create_sdk_mcp_server

from bacteria.tools.memory import read_memory, write_memory

bacteria_tool_server = create_sdk_mcp_server(
    name="bacteria",
    version="1.0.0",
    tools=[read_memory, write_memory],
)
