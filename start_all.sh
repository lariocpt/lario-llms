#!/bin/bash
echo "Starting the Dockerized Local AI Orchestration Hub..."

# Ensure we are in the correct directory
cd "$(dirname "$0")"

# Start everything using docker-compose
# It will automatically pick up docker-compose.yml AND docker-compose.override.yml
docker compose up -d --build

echo "Containers are spinning up!"
echo "-------------------------------------"
echo "Bifrost Gateway: http://localhost:8080"
echo "Ollama API:      http://localhost:11434"
echo "-------------------------------------"
echo "To jump into your ML environment and run scripts:"
echo "docker exec -it ml_pipeline /bin/bash"
