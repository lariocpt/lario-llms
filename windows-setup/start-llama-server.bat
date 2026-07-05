@echo off
echo Starting llama.cpp server with Vulkan support for Geekom Strix Halo (96GB VRAM)
echo -------------------------------------------------------------------------------
echo Make sure you have downloaded llama.cpp for Windows with Vulkan support.
echo Place your models in a 'models' directory next to this script.
echo.

:: Configuration for Gemma 4 31B (Smart General Agent)
:: -ngl 999  : Offload all layers to the GPU
:: -c 32768  : Context size
:: --vulkan  : Force Vulkan backend if it doesn't auto-detect

:: IMPORTANT: Ensure the name below matches the EXACT name of the Gemma file you downloaded!
set MODEL_PATH="models\gemma-4-31b-it-Q8_0.gguf"
set CONTEXT_SIZE=32768
set PORT=11434

:: If llama-server.exe is in a different folder, update the path below.
llama-server.exe ^
  -m %MODEL_PATH% ^
  -c %CONTEXT_SIZE% ^
  -ngl 99 ^
  --cache-type-k q8_0 ^
  --cache-type-v q8_0 ^
  --host 0.0.0.0 ^
  --port %PORT%


pause
