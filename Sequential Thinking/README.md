# Sequential Thinking MCP

A minimal Model Context Protocol (MCP) server that provides a "sequential thinking" tool. This module currently serves as a basic demonstration or placeholder for more complex reasoning chains.

## Purpose

The `sequential-thinking` module allows an AI assistant to simulate or request a multi-step reasoning process.
*Current State*: The implementation is a basic skeleton that accepts a message and returns a mock "analysis" for a specified number of steps.

## Dependencies

- **FastMCP**: Framework for building MCP servers.

## Tools

### `think`
Simulates a multi-step thinking process.
- **Args**:
    - `message` (str): The input topic or problem to think about.
    - `steps` (int): The number of thinking steps to generate (default: 3).
- **Returns**: A JSON object containing the input, the generated steps, and a summary.

## Usage

### Running with Docker
A `Dockerfile` and `docker-compose.yaml` are provided to run this service in a container.

### Running Manually
```bash
python Sequential-thinking.py
```
**Note**: Runs on port 8085 by default.
