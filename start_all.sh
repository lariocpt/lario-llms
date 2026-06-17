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
echo "Ollama API:       http://localhost:11434  ← raw LLM"
echo "ChromaDB:         http://localhost:8000   ← Vector Store"
echo "RAG API:          http://localhost:8100   ← RAG queries"
echo "--------------------------------------------------------"
echo "Pull general/factual models into Ollama:"
echo "  docker exec ollama ollama pull qwen3-coder:30b"
echo "  docker exec ollama ollama pull gemma4:latest"
echo "  docker exec ollama ollama pull meditron:70b"
echo "  docker exec ollama ollama pull glm-4.7-flash:bf16"
echo "  docker exec ollama ollama pull llama3.3:70b"
echo "  docker exec ollama ollama pull Qwen3-Coder-Next"
echo ""  
echo "To jump into your ML environment:"
echo "  docker exec -it ml_pipeline /bin/bash"
echo ""
echo "To use the RAG API:"
echo '  curl -X POST http://localhost:8100/query -H "Content-Type: application/json" -d '\''{"query": "your question here"}'\'''
echo ""
echo "To ingest documents into RAG:"
echo '  curl -X POST http://localhost:8100/ingest -H "Content-Type: application/json" -d '\''{"documents": ["doc text here"], "collection": "default"}'\'''

