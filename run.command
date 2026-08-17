#!/bin/zsh
# ============================================================
# Remy 桌宠 —— macOS 一键启动
#
# 双击这个文件即可。第一次会自动准备运行环境（要几分钟），
# 之后每次都是秒开。
#
# 与旧版的三处不同：
#
# 1. **不再写死路径。** 旧版写的是 `cd /Users/kevin/rei-per/`，
#    那只在原作者自己的电脑上成立，别人拿到就跑不了。
#    现在用脚本自己所在的目录。
#
# 2. **不再每次都 pip install。** 旧版每次启动都装一遍依赖，
#    没网就起不来，有网也要等几十秒——那不叫「点一下就能用」。
#    现在只在缺依赖时装。
#
# 3. **装在项目自己的虚拟环境里，不动系统 Python。**
#    往系统 Python 里装包可能弄坏用户电脑上别的东西，
#    而且新版 macOS 会直接拒绝（externally-managed-environment）。
# ============================================================

cd "$(dirname "$0")" || exit 1

VENV=".venv"
PY="$VENV/bin/python3"

echo "========================================"
echo " 星夜颂歌 · 蕾咪桌宠"
echo "========================================"

# ---------- 找一个可用的 Python ----------
BOOT=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" >/dev/null 2>&1; then BOOT="$c"; break; fi
done

if [ -z "$BOOT" ]; then
  echo ""
  echo "没有找到 Python。"
  echo "去 https://www.python.org/downloads/ 装一个（3.10 以上），再双击本文件。"
  echo ""
  read "?按回车关闭…"
  exit 1
fi

# ---------- 首次准备环境 ----------
if [ ! -x "$PY" ]; then
  echo ""
  echo "第一次启动，正在准备运行环境（大概 2–5 分钟，只需要这一次）…"
  echo "用的是 $($BOOT --version 2>&1)"
  echo ""

  if ! "$BOOT" -m venv "$VENV"; then
    echo ""
    echo "创建虚拟环境失败。"
    echo "可能是这个文件夹没有写权限——把整个文件夹拖到「文稿」里再试。"
    read "?按回车关闭…"
    exit 1
  fi
fi

# ---------- 缺什么装什么 ----------
# 每次都 pip install 太慢。先探一下 PyQt5 在不在，
# 在就直接启动——这一步通常只花几十毫秒
if ! "$PY" -c "import PyQt5, requests" >/dev/null 2>&1; then
  echo "正在安装依赖…（走清华镜像，国内快一些）"
  "$PY" -m pip install --upgrade pip -q \
    -i https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null
  if ! "$PY" -m pip install PyQt5 requests pyperclip \
       -i https://pypi.tuna.tsinghua.edu.cn/simple; then
    echo ""
    echo "依赖装不上。检查一下网络，或者换个镜像源重试。"
    read "?按回车关闭…"
    exit 1
  fi
  echo "依赖装好了。"
fi

# ---------- 启动 ----------
echo ""
echo "启动中…（这个终端窗口关掉桌宠也会退出，可以先留着）"
echo ""

"$PY" Remy.py
CODE=$?

if [ $CODE -ne 0 ]; then
  echo ""
  echo "========================================"
  echo " 程序异常退出（退出码 $CODE）"
  echo " 上面的报错信息麻烦截图发给开发者"
  echo "========================================"
  read "?按回车关闭…"
fi
