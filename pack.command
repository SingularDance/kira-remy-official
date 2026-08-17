#!/bin/zsh
# ============================================================
# 打包成 macOS 的 .app —— pack.bat 的 macOS 对应物
#
# 双击运行，产物在 dist/MACPetRemy.app，可以直接拖进「应用程序」。
#
# 与 pack.bat 的两处**必须不同**：
#
# 1. `--add-data` 的分隔符。Windows 用 `;`，macOS/Linux 用 `:`。
#    照抄 Windows 的写法在 mac 上会被解析成一个不存在的路径，
#    结果就是**数据文件一个都没打进去，程序起来看不到立绘**。
#    之前那个 MyApp.spec 就是 `datas=[]`，正是漏了这一步。
#
# 2. `--windowed` 在 macOS 上会生成 .app 包；Windows 上只是隐藏控制台。
# ============================================================

cd "$(dirname "$0")" || exit 1

APP_NAME="MACPetRemy"

echo "========================================"
echo " 蕾咪桌宠 —— 打包 macOS 应用"
echo "========================================"

# ---------- 环境 ----------
VENV=".venv"
PY="$VENV/bin/python3"
if [ ! -x "$PY" ]; then
  echo "还没有虚拟环境。先双击一次 run.command 把环境准备好。"
  read "?按回车关闭…"
  exit 1
fi

if ! "$PY" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "[1/3] 安装 PyInstaller…"
  "$PY" -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple || exit 1
else
  echo "[1/3] PyInstaller 已就绪"
fi

# ---------- 图标 ----------
# macOS 只认 .icns，直接拿 .ico 会报
# 「only ('icns',) images may be used as icons」，所以要先转一道。
#
# **图标源必须是 Remybaby.ico**，也就是 pack.bat 里 `--icon` 用的那个、
# 以及 desktop_pet.py 给托盘用的那个。三处用同一张图，
# Windows 和 macOS 才是同一个品牌形象。
# （曾经拿 Remy_Open.png 当过图标源——那是桌宠的立绘，不是应用图标，
#   Dock 里出现的是半身像而不是 logo。）
#
# 转换走系统自带的 sips + iconutil，不引入 Pillow 依赖。
ICON_SRC="Remybaby.ico"

if [ ! -f "$ICON_SRC" ]; then
  echo "找不到 $ICON_SRC，没法生成应用图标。"
  read "?按回车关闭…"; exit 1
fi

if [ ! -f "Remybaby.icns" ] || [ "$ICON_SRC" -nt "Remybaby.icns" ]; then
  echo "[1.5/3] 从 $ICON_SRC 生成 macOS 图标…"
  TMPDIR_ICON="$(mktemp -d)"
  ICONSET="$TMPDIR_ICON/remy.iconset"
  mkdir -p "$ICONSET"

  # sips 能直接读 .ico，但缩放时以 .ico 为源每次都要重新解码，
  # 而且多尺寸 .ico 取哪一层不受控。先定格成一张 PNG 再缩，结果可预期
  BASE="$TMPDIR_ICON/base.png"
  sips -s format png "$ICON_SRC" --out "$BASE" >/dev/null 2>&1 || {
    echo "读取 $ICON_SRC 失败"; read "?按回车关闭…"; exit 1; }

  SRC_PX=$(sips -g pixelWidth "$BASE" | awk '/pixelWidth/{print $2}')
  echo "      源图 ${SRC_PX}×${SRC_PX}"

  # iconset 的完整规格要到 1024（icon_512x512@2x）。
  # Remybaby.ico 只有 256px，超过就是放大，反而糊。
  # 所以**只生成源图撑得住的尺寸**——缺档时 macOS 会自己拿最大的那张缩放，
  # 效果好过我们先放大一遍再让它缩。
  # Dock 常规显示是 128pt@2x = 256px，正好落在真实分辨率上，不受影响
  for s in 16 32 128 256 512; do
    [ "$s" -le "$SRC_PX" ] && \
      sips -z $s $s "$BASE" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
    [ $((s*2)) -le "$SRC_PX" ] && \
      sips -z $((s*2)) $((s*2)) "$BASE" \
           --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
  done

  iconutil -c icns "$ICONSET" -o Remybaby.icns || {
    echo "图标生成失败"; read "?按回车关闭…"; exit 1; }
  rm -rf "$TMPDIR_ICON"
fi

# ---------- 清理 ----------
echo "[2/3] 清理旧产物…"
rm -rf build dist "MyApp.spec" "${APP_NAME}.spec"

# ---------- 打包 ----------
echo "[3/3] 开始打包（要几分钟）…"

# 与 pack.bat 打进去的是同一批文件。**注意分隔符是冒号。**
"$PY" -m PyInstaller --windowed --noconfirm --clean \
  --name "$APP_NAME" \
  --icon "Remybaby.icns" \
  --add-data "Remy_Shut.png:." \
  --add-data "Remy_Open.png:." \
  --add-data "Remy_Angry.png:." \
  --add-data "Remy_Expect.png:." \
  --add-data "Remy_Wronged.png:." \
  --add-data "Remy_Happy.png:." \
  --add-data "Remy_Sleep.png:." \
  --add-data "Remy_Dangle.png:." \
  --add-data "shortcuts.json:." \
  --add-data "help.md:." \
  --add-data "config.example.json:." \
  --add-data "Remybaby.ico:." \
  Remy.py

if [ $? -ne 0 ]; then
  echo ""
  echo "打包失败，看上面的报错。"
  read "?按回车关闭…"
  exit 1
fi

APP="dist/${APP_NAME}.app"

# ---------- 自检 ----------
# 打完就当成功是不够的：漏了数据文件时打包一样「成功」，
# 只是运行起来看不到立绘。这里逐个确认
echo ""
echo "自检打进去的资源…"
MISSING=0
for f in Remy_Shut.png Remy_Open.png Remy_Angry.png Remy_Expect.png \
         Remy_Wronged.png Remy_Happy.png Remy_Sleep.png Remy_Dangle.png \
         config.example.json help.md shortcuts.json; do
  if find "$APP" -name "$f" | grep -q .; then
    printf '  ok   %s\n' "$f"
  else
    printf '  缺   %s\n' "$f"
    MISSING=$((MISSING+1))
  fi
done

if [ $MISSING -gt 0 ]; then
  echo ""
  echo "有 $MISSING 个资源没打进去，程序跑起来会缺图。"
  read "?按回车关闭…"
  exit 1
fi

# ---------- 去掉隔离标记 ----------
# 自己打的包没有开发者签名，Gatekeeper 会拦。
# 本机自用去掉隔离属性即可；发给别人的话对方要在
# 「系统设置 → 隐私与安全性」里点「仍要打开」
xattr -cr "$APP" 2>/dev/null

echo ""
echo "========================================"
echo " 打包完成"
echo " $APP"
echo ""
echo " 配置和聊天记录存在："
echo " ~/Library/Application Support/${APP_NAME}/"
echo ""
echo " 发给别人时提醒一句：第一次打开要右键 →「打开」，"
echo " 因为这个包没有苹果开发者签名。"
echo "========================================"
read "?按回车关闭…"
