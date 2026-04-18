"""Voice activity detection wrapper around webrtcvad.

Attributes exposed for the main recorder loop:

* ``frame_ms`` — frame duration in milliseconds (must be 10, 20, or 30).
* ``frame_samples`` — samples per frame at ``sample_rate``.
* ``frame_bytes`` — bytes per frame (``frame_samples * 2`` for int16).
* ``silence_frames_needed`` — consecutive non-speech frames that signal EoS.
"""

from __future__ import annotations

import webrtcvad


class VAD:
    def __init__(
        self,
        aggressiveness: int = 2,
        frame_ms: int = 30,
        sample_rate: int = 16000,
        silence_ms: int = 800,
    ) -> None:
        if frame_ms not in (10, 20, 30):
            raise ValueError("webrtcvad only supports 10/20/30 ms frames")
        self._vad = webrtcvad.Vad(aggressiveness)
        self.sample_rate = sample_rate
        self.frame_ms = frame_ms
        self.frame_samples = int(sample_rate * frame_ms / 1000)
        self.frame_bytes = self.frame_samples * 2
        self.silence_frames_needed = silence_ms // frame_ms

    def is_speech(self, frame: bytes) -> bool:
        return self._vad.is_speech(frame, self.sample_rate)
