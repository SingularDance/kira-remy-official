#!/bin/zsh
# ============================================================
# 把 pack.command 打出的 .app 打包成 Remy_v{版本}_Mac.zip，
# 供 GitHub Releases 上传（与 Windows 的 Remy_v{版本}.zip 同挂一个 release）。
#
# 用系统自带的 ditto 而非 Python zipfile：ditto 能正确处理 .app 里的
# 代码签名、符号链接、资源分支——这些是 .app 分发必须保留的，
# zipfile 打符号链接会报错，打出来解压后签名也没了。
#
# 用法：
#   1. 先改 version.py 的 VERSION，再双击 pack.command 打出 dist/MACPetRemy.app
#   2. 双击本脚本，产出 dist/Remy_v{版本}_Mac.zip
#   3. 上传到 GitHub Releases，tag 与 VERSION 一致
#
# 版本号从 version.py 动态读取，不在这里硬编码。
# ============================================================

cd "$(dirname "$0")" || exit 1

APP_NAME="MACPetRemy"
APP="dist/${APP_NAME}.app"
VERSION_PY="version.py"

# 从 version.py 读 VERSION，避免版本号写死
V="$(sed -n 's/^VERSION = "\([^"]*\)".*/\1/p' "$VERSION_PY")"
if [ -z "$V" ]; then
  echo "读不到 $VERSION_PY 里的 VERSION，停止。"
  read "?按回车关闭…"; exit 1
fi

if [ ! -d "$APP" ]; then
  echo "找不到 $APP"
  echo "先双击一次 pack.command 把 .app 打出来。"
  read "?按回车关闭…"; exit 1
fi

ZIP="dist/Remy_v${V}_Mac.zip"

echo "========================================"
echo " 蕾咪桌宠 —— 生成 macOS 发布 zip"
echo "========================================"
echo "[1/2] 打包 $APP -> $ZIP ..."

# ditto -c -k 打 zip，--keepParent 让 zip 顶层是 MACPetRemy.app（而非散开）
# 先删旧 zip——ditto 不会覆盖已存在的文件
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP" || {
  echo "打包失败，看上面的报错。"
  read "?按回车关闭…"; exit 1
}

echo "[2/2] 校验 ..."
unzip -l "$ZIP" | grep -q "${APP_NAME}.app" || {
  echo "校验失败：zip 里找不到 ${APP_NAME}.app"
  read "?按回车关闭…"; exit 1
}

size_mb=$(du -m "$ZIP" | awk '{print $1}')
echo "[√] 生成完成：$ZIP（${size_mb} MB）"
echo ""
echo "下一步：把它和 Windows 的 Remy_v${V}.zip 一起上传到 GitHub Releases，"
echo "tag 用 v${V}。两个包同名不同平台后缀，客户端会各自下对。"
echo "========================================"
read "?按回车关闭…"
