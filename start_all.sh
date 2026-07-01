#!/bin/bash
set -e
echo "Starting the Dockerized Local AI Orchestration Hub..."

cd "$(dirname "$0")"

# Grant local Docker containers permission to connect to the X11 graphical server (headed display)
if [ -n "$DISPLAY" ] && command -v xhost &>/dev/null; then
  echo "Enabling GUI forwarding permission (headed display) for Docker..."
  timeout 2s xhost +local:docker || true
fi

docker compose up -d --build

echo ""
echo "Containers are spinning up!"
echo "--------------------------------------------------------"
echo "Bifrost Gateway:  http://localhost:8080   ← AI Router"
echo "llama.cpp API:    http://localhost:11434  ← raw LLM (llama-swap, OpenAI /v1)"
echo "ChromaDB:         http://localhost:8000   ← Vector Store"
echo "RAG API:          http://localhost:8100   ← RAG queries"
echo "--------------------------------------------------------"
echo "Models are served by llama.cpp + llama-swap (config: llama-cpp/config.yaml)."
echo "  List served models:   curl -s localhost:11434/v1/models | jq -r '.data[].id'"
echo "  Run a llama.cpp tool:  llama cli -hf <repo>:<quant>   |   llama bench -m /models/gguf/<name>.gguf"
echo "  Add a model:          edit llama-cpp/config.yaml (live-reloaded), then request it by id"
echo "  Pull a new GGUF:      llama cli -hf unsloth/<repo>:<quant>   (caches under ~/.cache/huggingface)"
echo ""
echo "To jump into your ML environment:"
echo "  docker exec -it ml_pipeline /bin/bash"
echo ""
echo "To use the RAG API:"
echo '  curl -X POST http://localhost:8100/query -H "Content-Type: application/json" -d '\''{"query": "your question here"}'\'''
echo ""
echo "To ingest documents into RAG:"
echo '  curl -X POST http://localhost:8100/ingest -H "Content-Type: application/json" -d '\''{"documents": ["doc text here"], "collection": "default"}'\'''

