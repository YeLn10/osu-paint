"""Stream the project's Ogg track from a beatmap timestamp."""

from io import BytesIO
import math
import os
from pathlib import Path
import tempfile

from osu_paint_app.ffmpeg import check_cancel, run_ffmpeg


def audio_duration_ms(data):
    from mutagen.oggvorbis import OggVorbis
    return OggVorbis(BytesIO(data)).info.length * 1000


def validate_audio_settings(*, speed=1, start_ms=0, trim_start_ms=0):
    if not all(math.isfinite(v) for v in (speed, start_ms, trim_start_ms)):
        raise ValueError("音频参数必须是有限数字。")
    if not .25 <= speed <= 4:
        raise ValueError("音频倍速须为 0.25–4。")
    if start_ms < 0 or trim_start_ms < 0:
        raise ValueError("音频开始时间与截取起点不能小于 0。")


def read_audio(path, *, cancel=None):
    with tempfile.TemporaryDirectory(prefix="osu-paint-audio-") as directory:
        output = Path(directory) / "source.ogg"
        run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:a:0", "-vn",
                     "-af", "aresample=48000,asetpts=PTS-STARTPTS", "-ac", "2", "-c:a", "libvorbis",
                     "-q:a", "5", "-map_metadata", "-1", "-map_chapters", "-1", str(output)], cancel)
        return output.read_bytes()


def render_audio(data, *, speed=1, start_ms=0, trim_start_ms=0, cancel=None):
    check_cancel(cancel)
    validate_audio_settings(speed=speed, start_ms=start_ms, trim_start_ms=trim_start_ms)
    if trim_start_ms >= audio_duration_ms(data):
        raise ValueError("截取起点必须早于原音频结束。")
    filters = [f"atrim=start={trim_start_ms / 1000}", "asetpts=PTS-STARTPTS"]
    # Keep each atempo stage within its high-quality 0.5–2 range.
    remaining = speed
    while remaining < .5 or remaining > 2:
        part = .5 if remaining < .5 else 2
        filters.append(f"atempo={part}")
        remaining /= part
    filters.extend([f"atempo={remaining}", "aresample=48000",
                    f"adelay={round(start_ms * 48)}S:all=1", "asetpts=N/SR/TB"])
    with tempfile.TemporaryDirectory(prefix="osu-paint-audio-") as directory:
        source, output = Path(directory) / "source.ogg", Path(directory) / "audio.ogg"
        source.write_bytes(data)
        run_ffmpeg(["-protocol_whitelist", "file,pipe", "-i", str(source), "-vn", "-af", ",".join(filters),
                     "-ac", "2", "-c:a", "libvorbis", "-q:a", "5", "-map_metadata", "-1",
                     "-map_chapters", "-1", str(output)], cancel)
        return output.read_bytes()


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
