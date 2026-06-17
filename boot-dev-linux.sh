#!/bin/bash
# boot-dev-linux.sh - Manually spin up Pop!_OS, Ubuntu, and Mint dev containers
set -e

cd "$(dirname "$0")"

# Grant local Docker containers permission to connect to the X11 graphical server
if [ -n "$DISPLAY" ] && command -v xhost &>/dev/null; then
  echo "Enabling GUI forwarding permission (headed display) for Docker..."
  timeout 2s xhost +local:docker || true
fi

echo "Starting the 3 Linux Dev Containers (Pop!_OS, Ubuntu, Mint)..."
docker compose -f dev-containers/docker-compose.dev.yml up -d --build

echo ""
echo "Dev containers are running!"
echo "--------------------------------------------------------"
echo "Pop!_OS Dev:      http://localhost:8440"
echo "Ubuntu Dev:       http://localhost:8441"
echo "Mint Dev:         http://localhost:8442"
echo "--------------------------------------------------------"
