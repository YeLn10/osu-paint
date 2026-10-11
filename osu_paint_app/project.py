"""Portable project data and v1-v3 JSON conversion, without Tk or file I/O."""

import base64
from dataclasses import dataclass
import math

from osu_paint import CLIENTS, parse_frames
from osu_paint_audio import validate_audio_settings
from osu_paint_video import resolve_video_options


PROJECT_SETTINGS = ("start_ms", "end_ms", "transition_ms", "scroll_speed")


@dataclass
class Project:
    frames: list[list[str]]
    frame_times: list[list[str]]
    timing_mode: str
    settings: dict[str, str]
    fast_clear: bool
    merge_holds: bool
    target_client: str = "lazer"
    video: dict | None = None
    audio_data: bytes | None = None
    audio_source: bytes | None = None
    audio_track: dict | None = None

    def to_data(self):
        """Encode editable state; unfinished drafts do not need to compile."""
        data = {"format": "osu-paint", "version": 1, "target_client": self.target_client, "frames": self.frames,
                "frame_times": self.frame_times, "timing_mode": self.timing_mode,
                "settings": self.settings, "fast_clear": self.fast_clear,
                "merge_holds": self.merge_holds}
        if self.video is not None:
            data.update(version=2, video=self.video.copy(),
                        audio=base64.b64encode(self.audio_data).decode("ascii") if self.audio_data is not None else None)
        if self.audio_track is not None:
            data.update(version=3, video=self.video.copy() if self.video is not None else None,
                        audio=base64.b64encode(self.audio_data).decode("ascii"),
                        audio_track=dict(self.audio_track, source=base64.b64encode(self.audio_source).decode("ascii")))
        return data

    @classmethod
    def from_data(cls, data):
        """Validate the entire document before the editor replaces any state."""
        try:
            if data["format"] != "osu-paint" or data["version"] not in (1, 2, 3):
                raise ValueError("不支持的项目版本。")
            target_client = data.get("target_client", "lazer")
            if target_client not in CLIENTS:
                raise ValueError("项目中的客户端须为 stable 或 lazer。")
            video, audio = None, None
            audio_track, audio_source = None, None
            merge_holds = data.get("merge_holds", False)
            if not isinstance(merge_holds, bool):
                raise ValueError("项目中的长条开关无效。")
            if data["version"] == 2 or (data["version"] == 3 and data["video"] is not None):
                video = data["video"]
                if not isinstance(video, dict) or not isinstance(video["filename"], str):
                    raise ValueError("项目中的视频信息无效。")
                if video.get("reference_animation"):
                    raise ValueError("此项目使用已撤销的参考动画模式，请从原视频重新导入。")
                # Keep the explicit project client, but discard obsolete scheduling controls.
                video = {key: value for key, value in video.items() if key not in ("game_fps", "frame_fps", "refresh_phase_ms")}
                effective = resolve_video_options(fps=video["fps"], width=video["width"], height=video["height"],
                                                  start_ms=video["start_ms"], scroll_speed=float(data["settings"]["scroll_speed"]),
                                                  refresh_hz=video.get("refresh_hz"),
                                                  merge_holds=merge_holds, target_client=target_client)
                if video.get("refresh_hz") is not None and (
                        effective["height"] != video["height"] or not math.isclose(effective["fps"], video["fps"], abs_tol=1e-9)):
                    raise ValueError("项目中的刷新率排帧参数与实际画面不一致，请从原视频重新导入。")
                if not math.isfinite(video["duration_ms"]) or video["duration_ms"] <= 0:
                    raise ValueError("项目中的视频时长无效。")
                if data["audio"] is not None:
                    audio = base64.b64decode(data["audio"], validate=True)
                    if not audio.startswith(b"OggS"):
                        raise ValueError("项目中的音轨无效。")
                video = video.copy()
            if data["version"] == 3:
                audio = base64.b64decode(data["audio"], validate=True)
                if not isinstance(data["audio_track"], dict):
                    raise ValueError("项目中的音频信息无效。")
                audio_track = data["audio_track"].copy()
                audio_source = base64.b64decode(audio_track.pop("source"), validate=True)
                if not audio.startswith(b"OggS") or not audio_source.startswith(b"OggS"):
                    raise ValueError("项目中的音轨无效。")
                validate_audio_settings(**{key: audio_track[key] for key in ("speed", "start_ms", "trim_start_ms")})
                if (not isinstance(audio_track["filename"], str) or
                        not math.isfinite(audio_track["leading_ms"]) or audio_track["leading_ms"] < 0 or
                        not math.isfinite(audio_track["duration_ms"]) or audio_track["duration_ms"] <= 0):
                    raise ValueError("项目中的音频信息无效。")
            frames = parse_frames("\n---\n".join("\n".join(frame) for frame in data["frames"]), allow_empty=True)
            if video is not None and (len(frames[0]), len(frames[0][0])) != (video["height"], video["width"]):
                raise ValueError("视频分辨率与项目画面不一致。")
            windows = data["frame_times"]
            if len(windows) != len(frames) or any(len(w) != 2 for w in windows):
                raise ValueError("项目中的帧时间不完整。")
            windows = [[str(value) for value in window] for window in windows]
            settings = {key: str(data["settings"][key]) for key in PROJECT_SETTINGS}
            mode = data["timing_mode"]
            if mode not in ("均分模式", "自由模式") or not isinstance(data["fast_clear"], bool):
                raise ValueError("项目中的模式设置无效。")
        except (KeyError, TypeError) as error:
            raise ValueError("无法识别此项目文件。") from error
        return cls(frames=frames, frame_times=windows, timing_mode=mode, settings=settings,
                   fast_clear=data["fast_clear"], merge_holds=merge_holds, target_client=target_client,
                   video=video, audio_data=audio, audio_source=audio_source, audio_track=audio_track)
