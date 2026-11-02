"""Offline demo audio.

Sarvam Bulbul is used whenever an API key is configured. Without a key the app
still returns a valid WAV file so the waveform player, scrubbing, and speed
controls can be demonstrated. This is deliberately a soft spoken-cadence tone,
not a fake claim of speech synthesis. The UI labels it as a demo and offers the
device's own text-to-speech voice for actual listening.
"""

from __future__ import annotations

import hashlib
import io
import math
import random
import sys
import wave
from array import array

SAMPLE_RATE = 22_050
MAX_DURATION = 8.0
MIN_DURATION = 2.8


def _duration_for_text(text: str) -> float:
    estimate = 2.4 + len(text) / 70.0
    return max(MIN_DURATION, min(MAX_DURATION, estimate))


def _tone(
    frames: array,
    frequency: float,
    seconds: float,
    amplitude: float,
) -> None:
    count = max(1, int(seconds * SAMPLE_RATE))
    for index in range(count):
        t = index / SAMPLE_RATE
        progress = index / count
        # A rounded envelope avoids clicks at the start and end of each syllable.
        envelope = math.sin(math.pi * progress) ** 0.75
        sample = (
            math.sin(2 * math.pi * frequency * t)
            + 0.32 * math.sin(2 * math.pi * frequency * 2.01 * t)
            + 0.14 * math.sin(2 * math.pi * frequency * 3.02 * t)
        )
        value = amplitude * envelope * sample
        frames.append(int(max(-1.0, min(1.0, value)) * 32767))


def _silence(frames: array, seconds: float) -> None:
    frames.extend([0] * max(0, int(seconds * SAMPLE_RATE)))


def generate_demo_wav(text: str, language: str) -> tuple[bytes, float]:
    seed_bytes = hashlib.sha256(f"{language}|{text}".encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(seed_bytes[:8], "big"))
    duration = _duration_for_text(text)
    base_frequency = {
        "hi": 205.0,
        "mr": 198.0,
        "gu": 210.0,
        "ta": 190.0,
        "te": 195.0,
        "bn": 200.0,
        "en": 185.0,
    }.get(language, 195.0)

    frames = array("h")
    _silence(frames, 0.12)
    target_frames = int(duration * SAMPLE_RATE)
    while len(frames) < target_frames:
        syllable = rng.uniform(0.12, 0.23)
        gap = rng.uniform(0.035, 0.085)
        frequency = base_frequency + rng.uniform(-16.0, 28.0)
        # A gentle rising/falling contour makes the cadence feel less mechanical.
        contour = 1.0 + 0.035 * math.sin(len(frames) / SAMPLE_RATE * 2.0)
        _tone(frames, frequency * contour, syllable, 0.18)
        _silence(frames, gap)

    if len(frames) > target_frames:
        del frames[target_frames:]
    _silence(frames, 0.12)

    if sys.byteorder != "little":
        frames.byteswap()

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(frames.tobytes())

    return buffer.getvalue(), len(frames) / SAMPLE_RATE
