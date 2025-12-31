# Validator Service

A standalone FastAPI service designed to validate AI-generated responses using both embedding-based semantic similarity and LLM-based evaluation.

## Purpose

The `validator-service` ensures the quality and correctness of AI outputs by providing two main validation mechanisms:
1.  **Semantic Validation**: Checks if a generated answer is semantically similar to a reference answer (using vector embeddings).
2.  **LLM Validation**: Uses a small evaluation LLM to judge the answer based on relevance, instruction following, and hallucination risks.

## Dependencies

- **FastAPI**: Web framework for the API.
- **Uvicorn**: ASGI server.
- **Httpx**: For making asynchronous HTTP requests to Ollama.
- **Ollama**: External service for embeddings (`mxbai-embed-large`) and LLM evaluation (`qwen2.5:0.5b-instruct`).

## Configuration

Environment variables control the service's behavior:

- `OLLAMA_BASE_URL`: URL of the Ollama instance (default: `http://ollama:11434`)
- `EMBEDDING_MODEL`: Model for generating embeddings (default: `hellord/mxbai-embed-large-v1:f16`)
- `VALIDATOR_MODEL`: LLM used for the `/validate_llm` endpoint (default: `qwen2.5:0.5b-instruct`)

## API Endpoints

### `POST /validate`
Checks if an answer matches a reference question/answer pair via cosine similarity.

**Request:**
```json
{
  "question": "What is the capital of France?",
  "answer": "Paris",
  "threshold": 0.7
}
```

**Response:**
```json
{
  "similarity": 0.85,
  "passed": true,
  "reason": "similarity >= threshold"
}
```

### `POST /validate_llm`
Uses an LLM to evaluate the quality of an answer.

**Request:**
```json
{
  "question": "Explain quantum physics",
  "answer": "It's about particles...",
  "instruction": "Keep it simple",
  "rules": "No math"
}
```

**Response:**
```json
{
  "final_result": "pass",
  "relevance": "good",
  "instruction_following": "good",
  "hallucination": "no"
}
```

### `POST /compare`
Calculates the cosine similarity between two texts.

**Request:**
```json
{
  "text1": "Hello world",
  "text2": "Hi earth"
}
```

## Usage

### Running with Docker
The service is intended to run as a container within a Docker Compose setup, interconnected with an Ollama service.

### Running Manually
```bash
uvicorn validator-service.main:app --host 0.0.0.0 --port 8000
```
