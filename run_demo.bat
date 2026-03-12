@echo off
REM ClawMesh Phase 1 Demo Script
REM Usage: Run this script to start server and two demo nodes

echo [INFO] Starting ClawMesh Phase 1 Demo
echo [INFO] Step 1/3: Starting WebSocket Server...

REM Start server in new window
start "ClawMesh Server" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe node\server.py --port 8765"

echo [INFO] Waiting 3 seconds for server to start...
timeout /t 3 /nobreak >nul

echo [INFO] Step 2/3: Starting Node A (new window)
start "Node A" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe examples\demo.py --server ws://localhost:8765"

echo [INFO] Waiting 2 seconds...
timeout /t 2 /nobreak >nul

echo [INFO] Step 3/3: Starting Node B (new window)
start "Node B" cmd /k "cd /d "%~dp0" && .venv\Scripts\python.exe examples\demo.py --server ws://localhost:8765"

echo.
echo [INFO] Demo started. Watch the windows for log output.
echo [INFO] Expected result:
echo   - Server shows two nodes connecting
echo   - Nodes exchange messages
echo   - Nodes show "Demo complete"
echo.
echo [INFO] To stop: close all windows or press Ctrl+C
pause
