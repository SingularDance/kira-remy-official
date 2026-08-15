# -*- coding: utf-8 -*-
import asyncio
import time
from PyQt5.QtCore import QThread, pyqtSignal

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
                        self.music_changed.emit("", "")
                    # 重置稳定计时，避免暂停/停止后残留旧 pending
                    self.tracker.update("", "", now)

            except Exception as e:
                print(f"[Remy Debug] 音乐监听器异常: {e}")

            # 每 2 秒轮询一次。细分 sleep 以便能够快速响应 stop() 停止线程
            for _ in range(POLL_SLICES):
                if not self.running:
                    break
                await asyncio.sleep(POLL_SLICE_SECONDS)

    def stop(self):
        """安全停止线程"""
        self.running = False
        self.wait()