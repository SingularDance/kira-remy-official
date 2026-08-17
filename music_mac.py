# -*- coding: utf-8 -*-
"""macOS 上的「现在在播什么」。

## 为什么不能照搬 Windows 那套

Windows 用的是 SMTC（`GlobalSystemMediaTransportControlsSessionManager`），
系统级接口，一次拿到所有播放器。**macOS 没有可用的对应物。**

系统里确实有个私有框架 `MediaRemote`，符号也都在，但**已经被权限门挡住了**。
在这台 macOS 26.3.1 上实测（写了个 ObjC 探针直接调）：

    MRMediaRemoteGetNowPlayingApplicationIsPlaying → 正在播放: 否
    MRMediaRemoteGetNowPlayingInfo                 → 回调收到 NULL

苹果从 15.4 起给这套接口加了 entitlement，没签名没授权的程序拿不到东西。
这不是代码写错，是这条路在系统层面已经关了。

所以 macOS 只能**逐个应用去问**。

## 各条路的实测结果

| 来源 | 能不能拿到 | 靠什么 |
|---|---|---|
| Apple Music | 能，而且是结构化的 | AppleScript 词典 |
| Spotify | 能，而且是结构化的 | AppleScript 词典 |
| 浏览器网页播放（B站/YouTube 等） | 能，拿到的是标签标题 | AppleScript 读标签 |
| **网易云音乐客户端** | **不能** | 它**没有 AppleScript 词典**，Info.plist 里也没声明脚本支持 |
| QQ 音乐客户端 | 同上，多半也不行 | |

网易云拿不到这一条，和 Windows 那边的结论是一致的——
当时也是发现网易云客户端不注册 SMTC。**两个平台都拿不到它。**

窗口标题这条路试过：`System Events` 要「辅助功能」权限，
`CGWindowList` 的窗口名要「屏幕录制」权限。为了读个歌名
去要屏幕录制权限，代价太大，没做。

## 两条必须守住的规矩

**一、只问正在运行的应用。**
向一个没在跑的 App 发 AppleScript 会**把它启动起来**——实测过，
一条 `tell application "Spotify"` 就把 Spotify 拉起来了。
用户打开桌宠结果 Spotify 自己弹出来，这是不能接受的。
所以每次都先用 `pgrep` 确认在跑。

**二、浏览器只看白名单站点的标签。**
读浏览器标签能把用户**所有**标签页的标题和网址都拿到——
实测一次返回了七十多个标签，里面有邮箱、网盘、公司文档。
桌宠会把听歌信息发给 AI 接口，所以这里只匹配音乐/视频站点，
其余标签一律不读、不记、不外传。

筛选是交给浏览器自己做的（AppleScript 的 `whose` 子句），
不匹配的标题**根本不会离开浏览器**。顺带还快了 5 倍多：
拿回来再筛 1.4 秒，让浏览器筛 0.25 秒。

## 已知问题（浏览器这条路目前不准，别当它可靠）

**根因：URL 命中 ≠ 正在播放。** 这条路只检查「有没有一个标签的网址
像是音乐/视频站」，完全不知道它是不是在出声。于是：

- 一个暂停的 B 站标签、甚至 B 站**首页**，都会被当成「正在播放」
- YouTube Studio 后台管理页也会命中 youtube.com
- 关掉播放但没关标签页 → 一直误报那首
- 同时命中多个标签时取第一个，顺序由窗口/标签排列决定，
  跟哪个真的在放毫无关系

Chrome 的 AppleScript 词典里 tab 只有 `URL` / `name` / `loading` / `id`
（实测 `get properties of active tab` 确认），**没有 audible 之类的属性**，
所以这条路在现有实现下**没有办法**判断是否在播放。

真正能解决的办法是用 `execute javascript` 读页面里的
`navigator.mediaSession.metadata`（能直接拿到结构化的歌名+歌手，
和 Windows 的 SMTC 是同一档）以及 `<video>/<audio>` 的 paused 状态。
代价是用户要在 Chrome 里手动打开
「查看 → 开发者 → 允许 Apple 事件中的 JavaScript」，默认是关的。
还没做，等确认要不要走这条路。

Apple Music / Spotify 那两条不受影响——它们有 `player state`，
是真的知道在不在播放。
"""

from __future__ import annotations

import re
import subprocess
import sys

import mac_audio

# osascript 偶尔会卡住（比如目标 App 正忙、或者权限弹窗还没被处理）。
# 不设超时的话监听线程会一直挂在那儿，桌宠看起来就像死了
TIMEOUT = 3.0


def _run_osascript(script: str) -> tuple[bool, str]:
    """跑一段 AppleScript。返回 (成功, 输出或错误)。"""
    try:
        p = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except OSError as exc:
        return False, str(exc)

    if p.returncode != 0:
        return False, (p.stderr or "").strip()
    return True, (p.stdout or "").strip()


def is_running(process_name: str) -> bool:
    """这个应用在跑吗。

    用 `pgrep` 而不是 pyobjc 的 NSWorkspace：少一个依赖，
    macOS 自带，也不需要任何权限。
    """
    try:
        return subprocess.run(
            ["pgrep", "-x", process_name],
            capture_output=True, timeout=2,
        ).returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


# ------------------------------------------------------------
# 权限
# ------------------------------------------------------------

# 首次向别的 App 发 AppleScript 时，macOS 会弹一个
# 「"MACPetRemy" 想要控制 "Google Chrome"」的对话框。
# 用户点了「不允许」之后，之后每次都会直接报 -1743，而且**不再弹窗**——
# 用户只会觉得「音乐识别坏了」，完全不知道是自己当初点了拒绝。
# 所以这里要认出这个错误码，并给一句能照着做的话。
_DENIED = re.compile(r"-1743|not authoriz|不允许|没有权限")

_denied_notified: set[str] = set()


def _note_denied(app: str) -> None:
    """权限被拒时提示一次。**只提示一次**，不要每 2 秒刷一条。"""
    if app in _denied_notified:
        return
    _denied_notified.add(app)
    print(
        f"[Remy] 没有控制「{app}」的权限，识别不了它在放什么。\n"
        f"       打开「系统设置 → 隐私与安全性 → 自动化」，"
        f"找到「MACPetRemy」，把「{app}」勾上。"
    )


# ------------------------------------------------------------
# Apple Music / Spotify —— 结构化数据，最好的一档
# ------------------------------------------------------------

def _player_track(app_name: str) -> tuple[str, str] | None:
    """问 Apple Music 或 Spotify 当前在放什么。

    两者的 AppleScript 词典在这几个属性上是一致的：
    `player state` / `name of current track` / `artist of current track`。
    """
    if not is_running(app_name):
        return None

    script = f'''
    tell application "{app_name}"
        if player state is playing then
            set t to name of current track
            set a to artist of current track
            return t & "\\n" & a
        else
            return ""
        end if
    end tell
    '''
    ok, out = _run_osascript(script)
    if not ok:
        if _DENIED.search(out):
            _note_denied(app_name)
        return None

    if not out:
        return ("", "")          # 应用在跑，但暂停了

    parts = out.split("\n")
    title = parts[0].strip() if parts else ""
    artist = parts[1].strip() if len(parts) > 1 else ""
    return (title, artist) if title else ("", "")


# ------------------------------------------------------------
# 浏览器 —— 只看白名单站点
# ------------------------------------------------------------

# 只有这些站点的标签才会被读取。**不在名单里的标签不看、不记。**
# 读浏览器标签本质上能看到用户所有的浏览内容，
# 而桌宠会把结果发给 AI，所以这里必须收得很紧。
MUSIC_SITES = (
    "bilibili.com",
    "youtube.com",
    "music.163.com",
    "y.qq.com",
    "kugou.com",
    "kuwo.cn",
    "open.spotify.com",
    "music.apple.com",
    "soundcloud.com",
    "music.youtube.com",
)

# 进程名 → (AppleScript 应用名, .app 名, 可能的 bundle id, 音频是否走共享 WebKit)
#
# 后三项是给 mac_audio 的音频闸门用的：要判断「这个浏览器此刻在不在出声」，
# 得知道它的音频可能挂在哪些标识下。Chrome 系的音频由 helper 进程发出，
# bundle id 是 com.google.Chrome.helper，路径在 Google Chrome.app 里，
# 两条都能认。Safari 的网页音频走系统共享的 WebKit GPU 服务，认不回来，
# 只能靠最后那个标志放宽（详见 mac_audio 模块文档）。
BROWSERS = {
    "Google Chrome":  ("Google Chrome",  "Google Chrome",  ("com.google.Chrome",), False),
    "Microsoft Edge": ("Microsoft Edge", "Microsoft Edge", ("com.microsoft.edgemac",), False),
    "Safari":         ("Safari",         "Safari",         ("com.apple.Safari",), True),
    "Arc":            ("Arc",            "Arc",            ("company.thebrowser.Browser",), False),
}

# 桌面播放器同样按「在不在出声」过滤。
# Apple Music / Spotify 本来就有 player state，这一层是为了省掉
# 「没在放的时候还去发 osascript」——顺带避免无谓的自动化权限弹窗
PLAYERS = {
    "Music":   ("Music",   ("com.apple.Music",)),
    "Spotify": ("Spotify", ("com.spotify.client",)),
}


def _url_filter_clause(prop: str = "URL") -> str:
    """拼一个 AppleScript 的 `whose` 条件，让浏览器**自己**筛。

    这一步既是性能也是隐私：

    - 性能：让 Python 拿回全部标签再筛，实测 **1.4 秒**（七十多个标签）；
      交给 Chrome 用 `whose` 筛，**0.25 秒**，快 5 倍多
    - 隐私：不匹配的标签标题**根本不会离开浏览器**。
      原来那种写法会把用户所有标签的标题都读进内存，
      哪怕之后扔掉，也已经读过了
    """
    return " or ".join(f'{prop} contains "{site}"' for site in MUSIC_SITES)


def _browser_tab(proc_name: str, app_name: str) -> tuple[str, str] | None:
    """在浏览器里找一个 URL 命中白名单的标签。

    **调用方必须先确认这个浏览器真的在出声**（见 `now_playing()` 的音频闸门），
    否则一个暂停的标签、甚至站点首页都会被当成正在播放。
    这个函数本身没有办法判断——Chrome 的 AppleScript 词典里 tab 只有
    URL / name / loading / id，没有任何「是否在出声」的属性（实测确认）。

    还剩两个已知的不精确之处（见文件头「已知问题」）：

    1. **命中多个标签时取第一个**，顺序由窗口和标签的排列决定。
       闸门只能保证「这个浏览器在出声」，不能指出是哪个标签在响。
    2. **拿不到艺术家**，只有一个脏标题（「xxx-哔哩哔哩_bilibili」）。
       没有任何地方清洗它——原来这里写着「清洗交给上层统一做」，
       那是假的，上层直接把原始标题塞进提示词。现在改为在 prompt 里
       要求模型忽略网站后缀（见 music_monitor.build_music_event_prompt）。
    """
    if not is_running(proc_name):
        return None

    if app_name == "Safari":
        # Safari 的词典和 Chrome 系不一样：标题是 name，不是 title
        cond = _url_filter_clause("URL")
        script = f'''
        tell application "Safari"
            set out to ""
            repeat with w in windows
                repeat with t in (tabs of w whose {cond})
                    set out to out & (URL of t) & "\t" & (name of t) & "\n"
                end repeat
            end repeat
            return out
        end tell
        '''
    else:
        cond = _url_filter_clause("URL")
        script = f'''
        tell application "{app_name}"
            set out to ""
            repeat with w in windows
                repeat with t in (tabs of w whose {cond})
                    set out to out & (URL of t) & "\t" & (title of t) & "\n"
                end repeat
            end repeat
            return out
        end tell
        '''

    ok, out = _run_osascript(script)
    if not ok:
        if _DENIED.search(out):
            _note_denied(app_name)
        return None

    for line in out.splitlines():
        if "\t" not in line:
            continue
        _url, _, title = line.partition("\t")
        title = clean_title(title.strip())
        if title:
            return (title, "")
    return None


# ------------------------------------------------------------
# 标题清洗
# ------------------------------------------------------------

# 平台后缀与推广词。浏览器给的是网页标题，夹着一堆噪音：
#
#     longchain-哔哩哔哩_bilibili
#     【4K修复】千本樱_哔哩哔哩_bilibili
#     千本桜 - 単曲 - 网易云音乐
#     线条小人看世界 - YouTube
#
# **在这里洗，而不是在 prompt 里求模型忽略。**
# 脏数据应该在源头处理掉：一来提示词是 Windows / macOS 共用的，
# 不该为了 mac 特有的脏数据去改它；二来「让模型忽略噪音」本身
# 就占用它有限的注意力，还不一定听话。
# 平台后缀**锚定在结尾**，反复剥，直到剥不动为止。
# 不锚定的话「Channel dashboard - YouTube Studio」里的
# 「- YouTube」会被从中间挖掉，剩下「Channel dashboard Studio」
_SUFFIX = re.compile(
    # B 站的后缀有好几种写法：`_哔哩哔哩_bilibili`、`-哔哩哔哩`、`-bilibili`，
    # 分隔符可能是下划线也可能是连字符，所以这里放宽而不是逐个列举
    r"([_\-]\s?哔哩哔哩(_bilibili)?|[_\-]\s?bilibili"
    r"|-\s?YouTube\s?Music|-\s?YouTube"
    r"|-\s?网易云音乐|-\s?单曲|-\s?単曲"
    r"|-\s?QQ音乐|-\s?酷狗音乐|-\s?酷我音乐|\|\s?SoundCloud)"
    r"\s*$",
    re.IGNORECASE,
)

# 推广词，出现在哪儿都是噪音
_PROMO = re.compile(
    r"(official\s*(music\s*)?(video|audio|mv)|lyric\s*video)",
    re.IGNORECASE,
)

# 整块丢弃的方括号内容：【4K修复】千本樱 → 千本樱。
# 只处理方括号类，不动圆括号——圆括号里常有正经信息
# （「Bad Apple!! (feat. nomico)」的 feat 是歌手，扔了可惜）
_BRACKETS = re.compile(r"[【〔\[]([^】〕\]]*)[】〕\]]")


def clean_title(title: str) -> str:
    """把网页标题洗成人能念的样子。洗没了就退回原文。"""
    if not title:
        return ""
    s = _BRACKETS.sub("", title)
    s = _PROMO.sub("", s)
    # 后缀可能叠着好几层（「千本桜 - 単曲 - 网易云音乐」），
    # 一次只剥最外层，所以循环。设上限防止正则写错时空转
    for _ in range(5):
        stripped = _SUFFIX.sub("", s).rstrip(" -_|·—–\t")
        if stripped == s:
            break
        s = stripped
    # 收尾：连续空白压成一个，去掉两端残留的分隔符
    s = re.sub(r"\s{2,}", " ", s).strip(" -_|·—–\t")
    # 全被洗掉说明标题本身就只有噪音（比如 B 站首页），
    # 这时候退回原文，让上层看到真实内容而不是空串
    return s or title.strip()


# ------------------------------------------------------------
# 对外
# ------------------------------------------------------------

def _sources():
    """按优先级列出候选来源：(名字, 是否在出声, 取数函数)。

    结构化数据的应用排前面——浏览器给的只有一个脏标题，
    能拿到干净的歌名歌手就不用脏的。
    """
    out = []
    for proc, (app, bundles) in PLAYERS.items():
        out.append((proc,
                    lambda p=proc, b=bundles: mac_audio.is_playing(p, b),
                    lambda a=app: _player_track(a)))
    for proc, (app, appname, bundles, webkit) in BROWSERS.items():
        out.append((proc,
                    lambda a=appname, b=bundles, w=webkit:
                        mac_audio.is_playing(a, b, webkit_counts=w),
                    lambda p=proc, a=app: _browser_tab(p, a)))
    return tuple(out)


SOURCES = _sources()


def now_playing() -> tuple[str, str]:
    """当前在放什么。返回 (标题, 艺术家)，都没有就是 ("", "")。

    ## 两道闸门，都在发 osascript 之前

    **第一道：系统里有没有任何进程在出声。**
    没有就直接返回空，一次 osascript 都不发。绝大多数时候走的是这条，
    所以这个函数的常态开销是 6 毫秒而不是 280 毫秒。

    **第二道：这个来源自己在不在出声。**
    浏览器那条路只能看到「标签开着」，看不到「在播放」——
    一个暂停的 B 站标签、甚至 B 站首页都会命中白名单。
    实测过：一个标签都没在放的时候，它照样报了
    `longchain-哔哩哔哩_bilibili`。闸门就是为了掐掉这种误报。

    拿不到音频状态时（macOS 14.4 以下）两道闸门都放行，
    退回原来的行为——宁可误报，也不要因为拿不到信号就彻底哑掉。
    """
    if sys.platform != "darwin":
        return ("", "")

    # 第一道闸门
    try:
        if not mac_audio.anything_playing():
            return ("", "")
    except Exception as exc:
        # 闸门本身出问题不该让功能失效，放行走原来的逻辑
        print(f"[Remy Debug] 音频状态查询出错，跳过闸门: {exc}")

    for name, is_audible, probe in SOURCES:
        try:
            # 第二道闸门
            if not is_audible():
                continue
            got = probe()
        except Exception as exc:            # 单个来源出问题不该拖垮整个监听
            print(f"[Remy Debug] 探测 {name} 出错: {exc}")
            continue
        if got and got[0]:
            return got
    return ("", "")


def diagnose() -> str:
    """给用户看的自检报告。

    音乐识别在 macOS 上有太多「静默失败」的可能（权限没给、
    应用没开、客户端根本不支持），一句「识别不出来」帮不上忙。
    这个函数把每一项分别说清楚。
    """
    lines = ["macOS 音乐识别自检", "=" * 34]

    # 系统级接口
    lines.append("系统级 now-playing（MediaRemote）：不可用")
    lines.append("  苹果从 macOS 15.4 起加了权限门，未签名的程序拿不到数据。")
    lines.append("  这条路对我们是关死的，只能逐个应用去问。")
    lines.append("")

    # 音频闸门 —— 先说这个，因为它决定了下面的探测发不发
    lines.append("音频闸门（CoreAudio 进程级状态）：")
    if not mac_audio.available():
        lines.append("  不可用（需要 macOS 14.4 以上）。")
        lines.append("  会退回「只看标签网址」的老行为——暂停的标签可能被误报。")
    else:
        procs = mac_audio.audio_processes() or []
        if not procs:
            lines.append("  当前没有任何进程在输出音频。")
            lines.append("  这种情况下识别直接返回空，不会去猜标签页。")
        else:
            lines.append(f"  当前有 {len(procs)} 个进程在输出音频：")
            for bundle_id, pid, _ in procs:
                app = mac_audio._app_bundle_from_pid(pid)
                lines.append(f"    {app or bundle_id or '(未知进程)'}  pid={pid}")
    lines.append("")

    lines.append("逐个应用：")
    for proc, (app, bundles) in PLAYERS.items():
        if not is_running(proc):
            lines.append(f"  {proc}：没运行")
            continue
        if not mac_audio.is_playing(proc, bundles):
            lines.append(f"  {proc}：在运行，但没在出声")
            continue
        got = _player_track(app)
        if got is None:
            lines.append(f"  {proc}：在运行，但问不到（多半是没给自动化权限）")
        elif got[0]:
            lines.append(f"  {proc}：正在播放《{got[0]}》— {got[1]}")
        else:
            lines.append(f"  {proc}：在运行，当前没在播")

    for proc, (app, appname, bundles, webkit) in BROWSERS.items():
        if not is_running(proc):
            continue
        if not mac_audio.is_playing(appname, bundles, webkit_counts=webkit):
            lines.append(f"  {proc}：在运行，但没在出声（不会去读它的标签）")
            continue
        got = _browser_tab(proc, app)
        if got is None:
            lines.append(f"  {proc}：在运行，但问不到（多半是没给自动化权限）")
        elif got[0]:
            lines.append(f"  {proc}：在出声，找到音乐标签「{got[0]}」")
        else:
            lines.append(f"  {proc}：在出声，但没有命中白名单的标签")

    if is_running("NeteaseMusic"):
        lines.append("  网易云音乐：在运行，但**拿不到歌名**")
        lines.append("    它没有提供 AppleScript 接口，macOS 上没有办法读取。")
        lines.append("    （能知道它在不在出声，但知道歌名是另一回事。）")
        lines.append("    想让蕾咪知道你在听什么，可以改用网页版（music.163.com）。")

    lines.append("")
    lines.append("如果上面有「没给自动化权限」：")
    lines.append("  系统设置 → 隐私与安全性 → 自动化 → 找到「MACPetRemy」并勾选")
    return "\n".join(lines)


if __name__ == "__main__":
    print(diagnose())
