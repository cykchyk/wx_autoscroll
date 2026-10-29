@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/2] 安装依赖...
python -m pip install -U pip opencv-python pyinstaller
echo [2/2] 打包...
python -m PyInstaller --noconfirm --clean --onefile --name wx_autoscroll --add-data "assets;assets" main.py
echo.
echo 输出: dist\wx_autoscroll.exe
pause
