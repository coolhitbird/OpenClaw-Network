@echo off
REM ClawMesh Phase 1 一键演示脚本
REM 用法：双击运行，观察两个终端窗口

echo [INFO] 启动 ClawMesh Phase 1 演示
echo [INFO] 步骤 1/3: 启动 WebSocket Server...

REM 启动 server（新窗口）
start "ClawMesh Server" cmd /k ".venv\Scripts\python.exe node\server.py --port 8765"

echo [INFO] 等待 3 秒服务器完全启动...
timeout /t 3 /nobreak >nul

echo [INFO] 步骤 2/3: 启动节点 A（新窗口）
start "Node A" cmd /k ".venv\Scripts\python.exe examples\demo.py --server ws://localhost:8765"

echo [INFO] 等待 2 秒...
timeout /t 2 /nobreak >nul

echo [INFO] 步骤 3/3: 启动节点 B（新窗口）
start "Node B" cmd /k ".venv\Scripts\python.exe examples\demo.py --server ws://localhost:8765 --node-id CL-01S-TESTNODE-0001"

echo.
echo [INFO] 演示已启动，请观察各个窗口的日志输出。
echo [INFO] 预期结果：
echo   - Server 显示两个节点连接
echo   - Node A/B 互相发送消息
echo   - 最后 Node A/B 显示 Demo complete
echo.
echo [INFO] 手动关闭：关闭所有窗口或按 Ctrl+C
pause
