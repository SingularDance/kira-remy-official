@echo off
chcp 65001 >nul
echo ========================================
echo  Remy 桌宠 - 依赖库安装程序
echo ========================================
echo.
echo 正在安装必要的Python库...
echo.

python -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
python -m pip install PyQt5 requests pyperclip winrt-Windows.Media.Control winrt-Windows.Foundation pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple

py -m pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
py -m pip install PyQt5 requests pyperclip winrt-Windows.Media.Control winrt-Windows.Foundation pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple

echo.
echo ========================================
echo  安装完成！
echo  请确保 Remy_*.png 头像图片在目录中
echo  配置 API：复制 config.example.json 为 config.json 并填入 Key
echo  也可以启动后在弹窗里填写
echo ========================================
pause
