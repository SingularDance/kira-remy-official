# -*- coding: utf-8 -*-
"""macOS：现在**哪个 App 真的在出声**。

## 这个模块解决什么问题

`music_mac.py` 判断「在放音乐」的依据原本只有一条：某个标签的网址像不像
音乐站。于是一个暂停的 B 站标签、甚至 B 站首页，都会被当成正在播放；
播放停了但标签还开着，就会一直误报那一首。

根因是 **URL 命中 ≠ 正在播放**，而 Chrome 的 AppleScript 词典里
tab 只有 `URL` / `name` / `loading` / `id`（实测
`get properties of active tab` 确认），**没有任何「是否在出声」的属性**。

CoreAudio 从 macOS 14.4 起提供了进程级的音频状态：
`kAudioHardwarePropertyProcessObjectList` 列出所有音频进程，
`kAudioProcessPropertyIsRunningOutput` 告诉你它此刻是不是在输出音频。

实测（macOS 26.3.1）：

- **不需要任何权限，不弹任何授权框**
- 一次查询 **约 6 毫秒**（对比 osascript 问一遍浏览器要 280 毫秒）
- 播放时正确置位，停止后正确清空

所以它当「闸门」用：**没有任何 App 在出声时，一个 osascript 都不发。**
既解决误报，又顺带省掉绝大多数子进程开销和权限弹窗。

## 为什么用 ctypes 而不是编译一个探针

CoreAudio 是系统框架里的纯 C 接口，ctypes 直接就能调。
编译 ObjC/Swift 探针的话要处理架构、打包进 .app、Gatekeeper 签名，
纯属自找麻烦。这个模块**零第三方依赖、零编译步骤**。

## 已知的不精确之处（不装作能分辨）

Safari 的网页音频是 `com.apple.WebKit.GPU` 这个 XPC 服务发出的，
它的父进程是 launchd，**没有办法反查回 Safari**（实测确认），
而且所有用 WKWebView 的 App 都共用它。
所以只能做到「有 WebKit 应用在出声」，无法确定就是 Safari。
处理方式见 `playing_apps()` 里的 WEBKIT_AMBIGUOUS。

Chrome / Edge / Arc 没有这个问题：它们的 helper 进程带自己的 bundle id，
可执行文件路径也在自己的 .app 里，两条路都能认回去。
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys

logger = logging.getLogger(__name__)

# 只在 macOS 上有意义。其他平台 import 本模块不应该出错，
# 所有函数直接返回「不可用」
IS_MAC = sys.platform == "darwin"

# Safari / WKWebView 的音频都从这个共享 XPC 服务出来，无法归属到具体 App
WEBKIT_AMBIGUOUS = "com.apple.WebKit.GPU"


# ============================================================
# CoreAudio 的 ctypes 绑定
# ============================================================

def _fourcc(s: str) -> int:
    """把 'prs#' 这种四字符码转成 CoreAudio 用的 UInt32。"""
    return int.from_bytes(s.encode("ascii"), "big")


# 常量取自 SDK 的 AudioHardware.h，不是猜的
_SYSTEM_OBJECT = 1
_PROCESS_LIST = _fourcc("prs#")     # kAudioHardwarePropertyProcessObjectList
_IS_RUNNING_OUTPUT = _fourcc("piro")  # kAudioProcessPropertyIsRunningOutput
_BUNDLE_ID = _fourcc("pbid")        # kAudioProcessPropertyBundleID
_PID = _fourcc("ppid")              # kAudioProcessPropertyPID
_SCOPE_GLOBAL = _fourcc("glob")
_UTF8 = 0x08000100                  # kCFStringEncodingUTF8


class _Addr(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32),
                ("mScope", ctypes.c_uint32),
                ("mElement", ctypes.c_uint32)]


def _load():
    """加载两个系统框架。失败返回 (None, None)，调用方据此降级。"""
    if not IS_MAC:
        return None, None
    try:
        ca = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError as exc:
        logger.debug("加载 CoreAudio 失败: %s", exc)
        return None, None

    ca.AudioObjectGetPropertyDataSize.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(_Addr), ctypes.c_uint32,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    ca.AudioObjectGetPropertyData.argtypes = [
        ctypes.c_uint32, ctypes.POINTER(_Addr), ctypes.c_uint32,
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    cf.CFStringGetCString.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    return ca, cf


_CA, _CF = _load()


def available() -> bool:
    """这台机器上能不能用这套接口。

    macOS 14.4 以下没有进程级音频属性，会在第一次查询时失败。
    不可用时**不要闸门化**——宁可退回原来的行为（可能误报），
    也不能因为拿不到信号就永远说「没在放」。
    """
    return _CA is not None and _CF is not None


def _cfstring(ref) -> str:
    """CFStringRef → str，并释放引用。"""
    if not ref:
        return ""
    buf = ctypes.create_string_buffer(512)
    ok = _CF.CFStringGetCString(ref, buf, 512, _UTF8)
    _CF.CFRelease(ref)
    return buf.value.decode("utf-8", "replace") if ok else ""


def _get(obj: int, selector: int, ctype):
    """读一个标量属性。失败返回 None。"""
    val = ctype()
    size = ctypes.c_uint32(ctypes.sizeof(val))
    addr = _Addr(selector, _SCOPE_GLOBAL, 0)
    st = _CA.AudioObjectGetPropertyData(
        obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(val))
    return val.value if st == 0 else None


def audio_processes():
    """→ [(bundle_id, pid, 是否在输出音频)]，不可用时返回 None。

    **不可用（None）和「没人在放」（空列表）必须分开**：
    前者要放行，后者要拦住。
    """
    if not available():
        return None
    try:
        addr = _Addr(_PROCESS_LIST, _SCOPE_GLOBAL, 0)
        size = ctypes.c_uint32(0)
        if _CA.AudioObjectGetPropertyDataSize(
                _SYSTEM_OBJECT, ctypes.byref(addr), 0, None,
                ctypes.byref(size)) != 0:
            return None

        n = size.value // ctypes.sizeof(ctypes.c_uint32)
        if n <= 0:
            return []
        arr = (ctypes.c_uint32 * n)()
        if _CA.AudioObjectGetPropertyData(
                _SYSTEM_OBJECT, ctypes.byref(addr), 0, None,
                ctypes.byref(size), arr) != 0:
            return None

        out = []
        for obj in arr:
            running = _get(obj, _IS_RUNNING_OUTPUT, ctypes.c_uint32)
            if not running:
                # 绝大多数进程都不在放，先短路掉，省下取 bundle id 的开销
                continue
            bref = ctypes.c_void_p()
            s = ctypes.c_uint32(ctypes.sizeof(bref))
            ab = _Addr(_BUNDLE_ID, _SCOPE_GLOBAL, 0)
            _CA.AudioObjectGetPropertyData(
                obj, ctypes.byref(ab), 0, None, ctypes.byref(s), ctypes.byref(bref))
            out.append((_cfstring(bref.value),
                        _get(obj, _PID, ctypes.c_int32) or 0,
                        True))
        return out
    except Exception as exc:              # 增强功能，绝不能拖垮桌宠
        logger.debug("查询音频进程出错: %s", exc)
        return None


# ============================================================
# 进程 → 它属于哪个 App
# ============================================================

def _app_bundle_from_pid(pid: int) -> str:
    """从可执行文件路径里找出最外层的 .app 名字。

    Chrome 的音频由 helper 进程发出，路径形如

        /Applications/Google Chrome.app/Contents/Frameworks/.../Google Chrome Helper

    取最外层的 `Google Chrome.app` 就能认回去。
    拿不到返回空串。
    """
    if pid <= 0:
        return ""
    try:
        path = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=1).stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return ""
    if not path:
        return ""
    # 最外层的 .app —— 用 find 而不是 rfind
    low = path.lower()
    i = low.find(".app/")
    if i < 0:
        return ""
    return os.path.basename(path[:i])     # 'Google Chrome'


def playing_apps():
    """现在正在出声的 App 集合，不可用时返回 None。

    集合里放的是**小写的标识串**，既有 bundle id 也有 .app 名，
    调用方用 `is_playing()` 匹配，不要自己比字符串。
    """
    procs = audio_processes()
    if procs is None:
        return None

    ids = set()
    for bundle_id, pid, _ in procs:
        if bundle_id:
            ids.add(bundle_id.lower())
            # com.google.Chrome.helper → 也登记 com.google.Chrome
            if bundle_id.lower().endswith(".helper"):
                ids.add(bundle_id[:-len(".helper")].lower())
        app = _app_bundle_from_pid(pid)
        if app:
            ids.add(app.lower())
    return ids


def is_playing(app_name: str, bundle_ids=(), webkit_counts=False) -> bool:
    """这个 App 现在在出声吗。

    参数：
        app_name      .app 的名字，例如 "Google Chrome"
        bundle_ids    该 App 可能的 bundle id 前缀
        webkit_counts 该 App 的网页音频是否走共享的 WebKit GPU 服务
                      （只有 Safari 需要，见模块文档）

    **接口不可用时返回 True**（放行），而不是 False。
    拿不到信号只说明我们不知道，不代表没在放；
    返回 False 会让功能在老系统上彻底哑掉。
    """
    ids = playing_apps()
    if ids is None:
        return True

    if app_name.lower() in ids:
        return True
    for b in bundle_ids:
        b = b.lower()
        if any(i == b or i.startswith(b + ".") for i in ids):
            return True
    if webkit_counts and WEBKIT_AMBIGUOUS.lower() in ids:
        # 只能说明「某个 WebKit 应用在出声」，不能断定是 Safari。
        # 由调用方再用 pgrep 确认 Safari 确实在跑，两个条件都满足才算
        return True
    return False


def anything_playing() -> bool:
    """现在有没有任何进程在输出音频。

    这是最外层的闸门：为 False 时 `music_mac.now_playing()` 直接返回空，
    **一次 osascript 都不发**。

    注意这里看的是**进程列表**，不是 `playing_apps()` 的标识集合——
    命令行工具（afplay 之类）既没有 bundle id 也没有 .app 路径，
    标识集合会是空的，但它确实在出声。用标识集合判断会漏掉这种情况。
    """
    procs = audio_processes()
    if procs is None:
        return True            # 不可用 → 放行，退回原来的行为
    return len(procs) > 0


if __name__ == "__main__":
    if not available():
        print("这台机器上拿不到进程级音频状态（需要 macOS 14.4 以上）")
        raise SystemExit(0)
    procs = audio_processes()
    print(f"正在输出音频的进程：{len(procs)} 个")
    for bid, pid, _ in procs:
        print(f"  {bid or '(无 bundle id)':36s} pid={pid:<8d} "
              f"app={_app_bundle_from_pid(pid) or '?'}")
    print()
    print("归一化后的标识集合：", playing_apps() or "（无）")
