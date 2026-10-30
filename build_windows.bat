@echo off
REM ===== MySQL 数据对比工具 - Windows 打包脚本 =====
chcp 65001 >nul
cd /d %~dp0

echo [1/2] 安装依赖 ...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo 依赖安装失败，请检查 Python 环境
    pause
    exit /b 1
)

echo [2/2] 开始打包 ...
pyinstaller --noconfirm --clean MySQLDiffTool.spec
if errorlevel 1 (
    echo 打包失败
    pause
    exit /b 1
)

echo.
echo ===== 打包完成！可执行文件: dist\MySQLDiffTool.exe =====
echo 直接把 dist\MySQLDiffTool.exe 拷给任何人，双击即可运行（无需安装 Python）
pause
