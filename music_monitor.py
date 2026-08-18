# -*- coding: utf-8 -*-
"""听歌监听。

Windows 走 SMTC（`winrt`），系统级接口，一次拿到所有播放器。
macOS 没有可用的对应物（MediaRemote 被苹果加了权限门），只能逐个应用问，
实现在 `music_mac.py`，那个文件顶部有完整的实测记录。

两条分支发出的信号完全一样，`desktop_pet.py` 不需要知道自己在哪个平台上。
"""
import asyncio
import sys
import time

from PyQt5.QtCore import QThread, pyqtSignal

IS_MAC = sys.platform == "darwin"

# mac 上不能 import winrt，所以这里要先分platform。
# Windows 分支保持原样：winrt 装没装都不该让程序起不来
if IS_MAC:
    import music_mac
    WINRT_AVAILABLE = False
else:
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        WINRT_AVAILABLE = True
    except ImportError:
        WINRT_AVAILABLE = False

# ============================================================
# 纯逻辑：提示词拼装 + 防抖判定 + 稳定计时
#
# 这一块不依赖 PyQt / winrt，只做字符串拼装与布尔判定，`now` /
# `last_react_time` 从外部注入，方便用 tests/test_music.py 直接单测。
# 提示词正文与 desktop_pet.py 里原来硬编码的完全一致，别随意改动。
# ============================================================

# 切歌主动反应的冷却时间（秒）：快速切歌时避免频繁打 API
MUSIC_REACT_COOLDOWN = 60

# 切歌后需持续播放满该秒数，蕾咪才主动回应
MUSIC_STABLE_SECONDS = 30

# 媒体类型（对应 Windows.Media.MediaPlaybackType）
MEDIA_UNKNOWN = 0
MEDIA_MUSIC = 1
MEDIA_VIDEO = 2
MEDIA_IMAGE = 3

# 轮询参数：每 2 秒问一次 Windows，拆成 10 × 0.2s 分段 sleep 以便 stop() 快速退出
POLL_SLICES = 10
POLL_SLICE_SECONDS = 0.2

# macOS 专用的轮询片数。**上面那两个常量是 Windows 分支在用的，不动。**
#
# 为什么 mac 不能跟 Windows 用同一个间隔：
#   Windows 的 SMTC 是内存里的系统接口，查一次几毫秒，2 秒毫无压力。
#   macOS 每轮要起 osascript 子进程去问浏览器，实测约 0.28 秒——
#   还按 2 秒轮，这个线程有 14% 的时间在 fork 子进程，
#   笔记本的电池和风扇都不好受。歌一首三四分钟，5 秒的延迟没人察觉。
# 25 × 0.2s = 5 秒
MAC_POLL_SLICES = 25


def build_music_context(title, artist, media_type=MEDIA_UNKNOWN):
    """平时聊天时注入的系统背景。空标题返回 ''。media_type 决定「音乐/视频/通用」措辞。"""
    if not title:
        return ""
    if media_type == MEDIA_VIDEO:
        kind = "用户当前正在观看视频"
    elif media_type == MEDIA_MUSIC:
        kind = "用户当前正在播放音乐"
    else:
        kind = "用户当前正在播放"
    s = f"（系统后台备注：{kind}《{title}》"
    if artist:
        s += f" - {artist}"
    s += "如果用户的话题与此相关，请自然地给出评价或反馈，不要生硬地强调是你监测到的。）"
    return s


def build_music_event_prompt(title, artist, media_type=MEDIA_UNKNOWN):
    """媒体稳定播放时的「隐形提示词」：根据 media_type 让蕾咪评论歌曲或视频。"""
    if media_type == MEDIA_VIDEO:
        verb, noun, focus, act = "观看视频", "视频标题", "这个视频的内容、类型", "假装你也在看"
    elif media_type == MEDIA_MUSIC:
        verb, noun, focus, act = "播放音乐", "歌名", "这首歌的旋律、品味", "假装你也在跟着听"
    else:
        verb, noun, focus, act = "播放", "标题", "这个内容", "自然地参与"
    s = f"（系统事件通知：调查员刚刚开始{verb}《{title}》"
    if artist:
        s += f" - {artist}"
    s += (f"请你作为蕾咪，给出简短的口语化反应，严格遵守37字以内的要求，自然地带上合适的emoji。"
          f"绝对不要机械地复述{noun}，而是{act}，或者对{focus}进行符合你傲娇人设的评论，禁止贬低。）")
    return s


def should_react(title, now, last_react_time, busy):
    """切歌后是否该主动反应。now/last_react_time 为秒级时间戳（注入），busy 由调用方算好。"""
    if now - last_react_time < MUSIC_REACT_COOLDOWN:
        return False
    if not title:
        return False
    if busy:
        return False
    return True


class MusicStabilityTracker:
    """跟踪当前媒体是否已稳定播放满 MUSIC_STABLE_SECONDS。

    纯逻辑：`now` 从外部注入，状态只在这个类内部，便于 tests/test_music.py 直接单测。
    语义：媒体切换 → 重新计时；同一媒体持续满 30 秒 → 返回一次 (title, artist)；
    此后同一媒体持续播放不再重复返回，直到媒体再次变化。
    """
    def __init__(self):
        self.current = None      # 当前等待/已处理的 (title, artist)；None 表示无
        self.started_at = 0.0    # current 首次出现的时间戳
        self.emitted = False     # 是否已为 current 发过稳定信号

    def update(self, title, artist, now):
        if not title:
            self.current = None
            self.started_at = 0.0
            self.emitted = False
            return None
        current = (title, artist)
        if current != self.current:
            self.current = current
            self.started_at = now
            self.emitted = False
            return None
        if self.emitted:
            return None
        if now - self.started_at >= MUSIC_STABLE_SECONDS:
            self.emitted = True
            return current
        return None


class MusicMonitorThread(QThread):
    # 定义信号，传递 标题、作者/歌手、媒体类型（MEDIA_*）
    music_changed = pyqtSignal(str, str, int)
    # 媒体稳定播放满 MUSIC_STABLE_SECONDS 后发出的信号，用于主动回应
    music_stable = pyqtSignal(str, str, int)

    def __init__(self):
        super().__init__()
        self.running = True
        self.current_music = ("", "")
        self.tracker = MusicStabilityTracker()

    def run(self):
        # macOS 走另一条分支，下面的 winrt / asyncio 那套在 mac 上都用不上
        if IS_MAC:
            self._run_mac()
            return

        if not WINRT_AVAILABLE:
            print("[Remy Debug] winrt 未安装，音乐监听功能已禁用。")
            return
        
        # 为该子线程创建一个新的 asyncio 事件循环
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self.monitor())
        loop.close()

    async def monitor(self):
        while self.running:
            try:
                # 获取系统级媒体控制管理器
                manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
                session = manager.get_current_session()
                now = time.time()

                if session:
                    # 获取当前媒体属性
                    props = await session.try_get_media_properties_async()
                    title = props.title or ""
                    artist = props.artist or ""
                    # 媒体类型：区分音乐/视频；部分应用不写则回退 Unknown
                    try:
                        media_type = int(props.playback_type) if props.playback_type is not None else MEDIA_UNKNOWN
                    except Exception:
                        media_type = MEDIA_UNKNOWN

                    # 如果媒体发生变化，立即发射信号（用于更新标题/聊天背景）
                    if (title, artist) != self.current_music:
                        self.current_music = (title, artist)
                        self.music_changed.emit(title, artist, media_type)

                    # 稳定计时：同一媒体持续播放满 MUSIC_STABLE_SECONDS 才触发主动回应
                    stable = self.tracker.update(title, artist, now)
                    if stable is not None:
                        self.music_stable.emit(stable[0], stable[1], media_type)
                else:
                    # 没有音乐在播放
                    if self.current_music != ("", ""):
                        self.current_music = ("", "")
                        self.music_changed.emit("", "", MEDIA_UNKNOWN)
                    # 重置稳定计时，避免暂停/停止后残留旧 pending
                    self.tracker.update("", "", now)

            except Exception as e:
                print(f"[Remy Debug] 音乐监听器异常: {e}")

            # 每 2 秒轮询一次。细分 sleep 以便能够快速响应 stop() 停止线程
            for _ in range(POLL_SLICES):
                if not self.running:
                    break
                await asyncio.sleep(POLL_SLICE_SECONDS)

    # ------------------------------------------------------------
    # macOS 分支
    #
    # 和上面的 monitor() 平行，互不影响。这里是同步实现，
    # 不需要 asyncio——osascript 是子进程调用，用不上事件循环
    # ------------------------------------------------------------

    def _run_mac(self):
        # 结构与 monitor() 一一对应：先发变化信号更新聊天背景，
        # 再走同一个 MusicStabilityTracker 决定要不要主动开口。
        #
        # media_type 恒为 MEDIA_UNKNOWN：那是 SMTC 的
        # Windows.Media.MediaPlaybackType，macOS 这边没有对等物——
        # AppleScript 只给歌名歌手，浏览器只给标签标题，都不带媒体类型。
        # 报 UNKNOWN 而不是猜一个 MUSIC，是因为猜错的代价很实在：
        # 用户在看 B 站教程，蕾咪却按「音乐」的话术说「这旋律不错」。
        # UNKNOWN 会落到 build_music_event_prompt 的通用分支，措辞不预设是歌。
        while self.running:
            try:
                title, artist = music_mac.now_playing()
                now = time.time()

                if (title, artist) != self.current_music:
                    self.current_music = (title, artist)
                    self.music_changed.emit(title, artist, MEDIA_UNKNOWN)

                # 稳定计时：同一内容连续放满 MUSIC_STABLE_SECONDS 才主动开口。
                # 这一层同时解决了「开机就冒气泡」——启动时正在放的东西
                # 也要先满 30 秒，而不是第一次轮询就触发
                stable = self.tracker.update(title, artist, now)
                if stable is not None:
                    self.music_stable.emit(stable[0], stable[1], MEDIA_UNKNOWN)

            except Exception as e:
                print(f"[Remy Debug] 音乐监听器异常: {e}")

            # 每 5 秒轮询一次。同样细分 sleep 以便快速响应 stop()，
            # 但用 QThread.msleep 而不是 asyncio.sleep——这条分支没有事件循环
            for _ in range(MAC_POLL_SLICES):
                if not self.running:
                    break
                self.msleep(int(POLL_SLICE_SECONDS * 1000))

    def stop(self):
        """安全停止线程"""
        self.running = False
        self.wait()