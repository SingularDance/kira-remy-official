@echo off
chcp 65001 >nul
echo ========================================
echo  Remy 桌宠 - 打包程序 (生成exe)
echo ========================================
echo.

echo [1/3] 清理旧文件...
if exist "dist" rmdir /s /q dist
if exist "build" rmdir /s /q build
if exist "*.spec" del *.spec
echo [√] 清理完成

echo [2/3] 开始打包...
python -m PyInstaller --onefile --windowed --name "星夜颂歌-蕾咪！" ^
    --icon="Remybaby.ico" ^
    --add-data "Remy_Shut.png;." ^
    --add-data "Remy_Open.png;." ^
    --add-data "Remy_Angry.png;." ^
    --add-data "Remy_Expect.png;." ^
    --add-data "Remy_Wronged.png;." ^
    --add-data "Remy_Happy.png;." ^
    --add-data "Remy_Sleep.png;." ^
    --add-data "Remy_Dangle.png;." ^
    --add-data "shortcuts.json;." ^
    --add-data "help.md;." ^
    --add-data "config.example.json;." ^
    --add-data "Remybaby.ico;." ^
    Remy.py

if %errorlevel% == 0 (
    echo [√] 打包成功！
    echo [3/3] 生成文件：dist\星夜颂歌-蕾咪！.exe
) else (
    echo [×] 打包失败！请检查错误信息
)

echo.
echo ========================================
echo  打包完成！
echo  please check dist folder
echo ========================================
pause