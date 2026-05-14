@echo off
chcp 65001 > nul
echo ============================================================
echo  Gene Synthesizer DLP - Build Script
echo ============================================================

:: 1. Eski build va dist papkalarini o'chirish
echo.
echo [1/3] Cleaning old build files...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist
echo Done.

:: 2. PyInstaller bilan .exe yaratish
echo.
echo [2/3] Building executable with PyInstaller...
pyinstaller ^
    --name DLP ^
    --onedir ^
    --windowed ^
    --noconfirm ^
    --add-data "DNK.png;." ^
    --collect-all pypylon ^
    --hidden-import serial ^
    --hidden-import serial.tools ^
    --hidden-import serial.tools.list_ports ^
    main.py

if errorlevel 1 (
    echo.
    echo ERROR: PyInstaller failed!
    pause
    exit /b 1
)
echo Done.

:: 3. Natija
echo.
echo [3/3] Build complete!
echo Output: dist\DLP\DLP.exe
echo.
echo To create installer: run Inno Setup with DLP_installer.iss
echo ============================================================
pause
