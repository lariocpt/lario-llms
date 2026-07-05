@echo off
echo Setting up VS Code Extensions (Cline and OpenCode) for Daniel
echo -------------------------------------------------------------------------------

:: Set up Cline config
set "CLINE_DIR=%APPDATA%\Code\User\globalStorage\saoudrizwan.claude-dev\settings"
if not exist "%CLINE_DIR%" mkdir "%CLINE_DIR%"
copy /Y "agents\General-Helper\editor-configs\cline_api_settings.json" "%CLINE_DIR%\cline_api_settings.json" >nul
echo [OK] Cline successfully configured to use local Bifrost Gateway.

:: Set up OpenCode config
set "OPENCODE_DIR=%USERPROFILE%\.config\opencode"
if not exist "%OPENCODE_DIR%" mkdir "%OPENCODE_DIR%"
copy /Y "agents\General-Helper\editor-configs\opencode.jsonc" "%OPENCODE_DIR%\opencode.jsonc" >nul
echo [OK] OpenCode successfully configured to use local Bifrost Gateway.

echo.
echo Setup Complete! 
echo You can now open VS Code and start using the agents instantly.
pause
