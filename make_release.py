# -*- coding: utf-8 -*-
"""
Remy 桌宠 - 发布 zip 打包脚本

把 pack.bat 生成的 exe 打包成 `Remy_v{版本}.zip`，供 GitHub Releases 上传。

为什么用 Python 的 zipfile，而不是 Windows「发送到压缩文件夹」：
后者在中文 Windows 上会用 GBK 存中文文件名、且不设 UTF-8 标志，解压时
`星夜颂歌-蕾咪！.exe` 会被 downloader 当成乱码（见 downloader._decode_name）。
zipfile 写出的非 ASCII 名自动带 UTF-8 标志，从源头杜绝这个问题。

用法：
    1. 先改 version.py 的 VERSION，再跑 pack.bat 生成 exe
    2. python make_release.py
    3. 把 dist\\Remy_v{版本}.zip 上传到 GitHub Releases，tag 与 VERSION 一致

发版三件套必须一致：version.py 的 VERSION、exe 名、GitHub tag。
"""

import os
import sys
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import version

# pack.bat 里 --name 指定的产物名，二者必须同步
EXE_NAME = "星夜颂歌-蕾咪！.exe"


def exe_path():
    return os.path.join(BASE, "dist", EXE_NAME)


def zip_path(v):
    return os.path.join(BASE, "dist", f"Remy_v{v}.zip")


def build_release_zip():
    v = version.VERSION
    exe = exe_path()
    if not os.path.exists(exe):
        sys.exit(f"未找到 {exe}\n请先运行 pack.bat 生成 exe，再跑本脚本")

    out = zip_path(v)
    top = f"Remy_v{v}"              # 顶层目录，safe_extract 会自动剥掉
    arcname = f"{top}/{EXE_NAME}"

    print("========================================")
    print("  Remy 桌宠 - 生成发布 zip")
    print("========================================")
    print(f"[1/2] 打包 {arcname} ...")
    with zipfile.ZipFile(out, "w") as zf:
        zf.write(exe, arcname)

    print("[2/2] 校验 ...")
    _verify(out, arcname)

    size_mb = os.path.getsize(out) / 1024 / 1024
    print(f"[√] 生成完成：{out}（{size_mb:.1f} MB）")
    print("下一步：把该 zip 上传到 GitHub Releases，tag 与 version.py 的 VERSION 一致")


def _verify(path, arcname):
    """回读校验：确认 exe 名以 UTF-8 标志正确存储，不会再解出乱码。"""
    with zipfile.ZipFile(path) as zf:
        infos = zf.infolist()
        exe = [i for i in infos if i.filename.endswith(EXE_NAME)]
        if len(exe) != 1:
            sys.exit(f"校验失败：zip 里应恰好有一个 exe，实际 {len(exe)} 个")
        info = exe[0]
        if info.filename != arcname:
            sys.exit(f"校验失败：exe 名在 zip 里读回异常：{info.filename!r}")
        if not (info.flag_bits & 0x800):
            sys.exit("校验失败：exe 文件名未带 UTF-8 标志（会再次触发乱码 bug）")
    print("    校验通过：exe 名以 UTF-8 标志正确存储")


if __name__ == "__main__":
    build_release_zip()
