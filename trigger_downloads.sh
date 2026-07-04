#!/bin/bash
echo "Pinging FAST profile models to trigger downloads..."
curl -s -X POST http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model": "gemma4", "messages": [{"role": "user", "content": "hi"}]}' > /dev/null &
curl -s -X POST http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model": "qwen-routing", "messages": [{"role": "user", "content": "hi"}]}' > /dev/null &
curl -s -X POST http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model": "qwen2.5-vl", "messages": [{"role": "user", "content": "hi"}]}' > /dev/null &
curl -s -X POST http://localhost:11434/v1/chat/completions -H "Content-Type: application/json" -d '{"model": "gemma3-vision", "messages": [{"role": "user", "content": "hi"}]}' > /dev/null &
wait
echo "All fast models initialized!"
