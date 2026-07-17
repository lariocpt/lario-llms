@echo off
echo Starting AI Model Orchestrator (llama-swap) for Geekom Strix Halo
echo -------------------------------------------------------------------------------
echo This script will automatically download and route between the optimal models 
echo (Gemma, Qwen, Vision) based on what your agents request.
echo.

:: Ensure llama-swap.exe is in the same directory as this script.
if not exist "llama-swap.exe" (
    echo ERROR: llama-swap.exe not found!
    echo Please download it and place it in the same folder as this script.
    pause
    exit /b
)

:: Run llama-swap using the FAST configuration by default
llama-swap.exe -config config-fast.yaml

pause
