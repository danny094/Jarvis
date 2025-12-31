# Utils

General utility functions used throughout the application.

## Components

### `json_parser.py`
Provides robust JSON parsing capabilities, specifically designed to handle common issues in LLM outputs (e.g., markdown code blocks wrapping JSON, trailing commas).
- `extract_json_from_text`: Attempts to find and parse JSON within a larger text block.

### `logger.py`
Standardized logging configuration.
- Exports `log_info`, `log_error`, `log_warning`, `log_debug`.

### `ollama.py`
Wrapper functions for making requests to the Ollama API.
- `query_model`: Sends a completion request to a specified model.
- `get_embeddings`: Retrieves vector embeddings.

### `prompt.py`
Helpers for loading and formatting prompt templates from files.
