@echo off
chcp 65001
echo ====================================
echo 启动对冲策略 - 双进程模式
echo ====================================
echo.

REM 检查Redis是否运行
echo [1/3] 检查Redis服务...
tasklist /FI "IMAGENAME eq redis-server.exe" 2>NUL | find /I /N "redis-server.exe">NUL
if "%ERRORLEVEL%"=="0" (
    echo ✓ Redis服务正在运行
) else (
    echo ✗ Redis服务未运行，请先启动Redis
    echo 运行命令: cd ..\redis\Redis-7.2.4-Windows-x64-msys2 ^&^& start.bat
    pause
    exit /b 1
)
echo.

REM 启动B入口（订阅者）
echo [2/3] 启动B入口进程（订阅模式）...
start "对冲策略-B入口-订阅" cmd /k "python main_B.py --market ETH --config config.yaml"
echo ✓ B入口进程已启动
echo.

REM 等待2秒确保B入口已启动并连接Redis
echo 等待B入口初始化...
timeout /t 3 /nobreak >nul
echo.

REM 启动A入口（发布者）
echo [3/3] 启动A入口进程（挂单模式）...
start "对冲策略-A入口-挂单" cmd /k "python main_A.py --market ETH --quantity 0.01 --depth 1 --config config.yaml"
echo ✓ A入口进程已启动
echo.

echo ====================================
echo 两个进程已成功启动！
echo ====================================
echo.
echo 进程说明：
echo - A入口窗口：执行限价挂单和成交监控
echo - B入口窗口：监听成交消息并执行对冲
echo.
echo 停止方式：
echo - 在各自窗口按 Ctrl+C 优雅停止
echo - 或直接关闭窗口
echo.
pause