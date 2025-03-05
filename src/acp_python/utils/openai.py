from acp_python.types import AgentInfo
from typing import Any, Dict


def agent_to_tool(agent: AgentInfo) -> Dict[str, Any]:
    """
    Convert an AgentInfo object into an OpenAI API tool format (ChatCompletionToolParam).

    This function takes an agent's information and formats it as a tool definition
    that can be used with OpenAI's API function calling interface. The tool is
    configured as a function that can send messages to the specified agent.

    Args:
        agent: The AgentInfo object containing the agent's name and description

    Returns:
        A dictionary matching OpenAI's ChatCompletionToolParam format, defining
        a function tool that can message the agent
    """
    return {
        "type": "function",
        "function": {
            "name": agent.name.lower(),
            "description": agent.description,
            "parameters": {
                "type": "object",
                "properties": {
                    "msg": {
                        "type": "string",
                        "description": "The message to send to the agent",
                    }
                },
                "required": ["msg"],
            },
        },
    }
