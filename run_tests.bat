@echo off
REM 快速运行 node_id 测试（绕过 uv 打包问题）
cd /d "%~dp0"
set PYTHONPATH=.
python tests\test_node_id.py
pause
