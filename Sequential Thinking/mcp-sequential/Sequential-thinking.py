from fastmcp import FastMCP

mcp = FastMCP("sequential_thinking")

@mcp.tool()
def think(message: str, steps: int = 3):
    """Schrittweises Denken und Reasoning."""
    chain = []
    for i in range(steps):
        chain.append({
            "step": i + 1,
            "thought": f"Analyse Schritt {i+1}: {message}",
        })

    return {
        "input": message,
        "steps": chain,
        "summary": f"{steps} Schritte generiert"
    }

if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=8085
    )