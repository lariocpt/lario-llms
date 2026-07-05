@echo off
echo Starting llama.cpp server with Vulkan support for Geekom Strix Halo (96GB VRAM)
echo -------------------------------------------------------------------------------
echo Make sure you have downloaded llama.cpp for Windows with Vulkan support.
echo Place your models in a 'models' directory next to this script.
echo.

:: Configuration for MiniMax-M2.7 UD-Q3_K_S (87 GB MoE)
:: -ngl 99   : Offload all 62 layers to the GPU
:: -c 8192   : Context size (adjust based on remaining memory)
:: --vulkan  : Force Vulkan backend if it doesn't auto-detect

set MODEL_PATH="models\minimax-m2.7-ud-q3_k_s.gguf"
set CONTEXT_SIZE=8192
set PORT=11434

:: If llama-server.exe is in a different folder, update the path below.
llama-server.exe ^
  -m %MODEL_PATH% ^
  -c %CONTEXT_SIZE% ^
  -ngl 99 ^
  --host 0.0.0.0 ^
  --port %PORT%

pause
