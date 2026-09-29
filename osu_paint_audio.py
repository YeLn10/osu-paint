"""Stream the project's Ogg track from a beatmap timestamp."""

from io import BytesIO
import os


class AudioPreview:
    def __init__(self):
        self.mixer = None
        self.stream = None
        self.start_ms = 0

    def play(self, data, start_ms):
        self.stop()
        if data is None:
            return
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        try:
            import pygame
            from mutagen.oggvorbis import OggVorbis
        except ImportError as error:
            raise RuntimeError("缺少音乐播放组件，请执行 python -m pip install -r requirements.txt，"
                               "或使用新版 EXE。") from error
        try:
            # Read duration without decoding the whole track into PCM memory.
            duration_ms = OggVorbis(BytesIO(data)).info.length * 1000
            self.start_ms = max(0, start_ms)
            if self.start_ms >= duration_ms:
                return
            self.mixer = pygame.mixer
            if not self.mixer.get_init():
                self.mixer.init(frequency=48000, buffer=512)
            self.stream = BytesIO(data)
            self.mixer.music.load(self.stream, "ogg")
            # Imported audio already contains the video's leading offset silence.
            self.mixer.music.play(start=self.start_ms / 1000)
        except Exception as error:
            self.stop()
            raise RuntimeError(f"音乐播放失败，请检查音频输出设备或音轨：{error}") from error

    def position_ms(self):
        if self.mixer is not None and self.mixer.get_init() and self.mixer.music.get_busy():
            elapsed = self.mixer.music.get_pos()
            if elapsed >= 0:
                return self.start_ms + elapsed
        return None

    def stop(self):
        if self.mixer is not None and self.mixer.get_init():
            self.mixer.music.stop()
            self.mixer.music.unload()
        if self.stream is not None:
            self.stream.close()
            self.stream = None

    def close(self):
        self.stop()
        if self.mixer is not None:
            self.mixer.quit()
            self.mixer = None
