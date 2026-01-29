# Agents and environment configuration

## Agents used in the current pipeline
- Planner
- Retriever
- Writer
- Critic
- Verifier

## Environment variables

### LLM
- `LLM_PROVIDER` (default: `stub`, options: `openai`)
- `OPENAI_API_KEY` (required when `LLM_PROVIDER=openai`)
- `OPENAI_MODEL` (default: `gpt-4o-mini`)

### Retrieval / Storage
- `DATABASE_URL` (Postgres connection string with pgvector enabled)
- `EMBEDDING_MODEL` (default: `sentence-transformers/all-MiniLM-L6-v2`)
- `EMBEDDING_DIM` (default: `384`)

### Web Search
- `BING_API_KEY` (primary provider)
- `SERPAPI_KEY` (fallback provider)
