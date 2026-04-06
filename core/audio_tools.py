"""
core/audio_tools.py
-------------------
Audio utility suite for the orchestrator agent.

Provides six tools:
  1. transcribe_audio  — Speech-to-text (STT) from audio files / URLs
  2. text_to_speech    — Generate audio from text (TTS)
  3. save_audio        — Download/copy audio files to disk
  4. record_audio      — Record from microphone
  5. play_audio        — Play an audio file through speakers
  6. speak             — TTS + play in one step (agent voice output)

Supports both local file paths AND HTTP/HTTPS URLs.
Supported formats: MP3, WAV, OGG, FLAC, M4A, AAC, AIFF, WMA, WEBM
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import shutil
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

SUPPORTED_AUDIO_TYPES: dict[str, str] = {
    ".mp3":  "audio/mpeg",
    ".wav":  "audio/wav",
    ".ogg":  "audio/ogg",
    ".flac": "audio/flac",
    ".m4a":  "audio/mp4",
    ".aac":  "audio/aac",
    ".aiff": "audio/aiff",
    ".aif":  "audio/aiff",
    ".wma":  "audio/x-ms-wma",
    ".webm": "audio/webm",
    ".opus": "audio/opus",
}

DEFAULT_MAX_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB (audio files can be larger)
DEFAULT_TIMEOUT_SECONDS = 60


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_url(path: str) -> bool:
    """Check if the given path is an HTTP/HTTPS URL."""
    try:
        parsed = urlparse(path)
        return parsed.scheme in ("http", "https")
    except Exception:
        return False


def _resolve_audio_mime(*, ext: str = "", content_type: str = "") -> str | None:
    """Determine MIME type for audio from extension or Content-Type."""
    if ext:
        mime = SUPPORTED_AUDIO_TYPES.get(ext.lower())
        if mime:
            return mime
    if content_type:
        ct = content_type.split(";")[0].strip().lower()
        if ct.startswith("audio/"):
            return ct
    if ext:
        guessed, _ = mimetypes.guess_type(f"file{ext}")
        if guessed and guessed.startswith("audio/"):
            return guessed
    return None


def _download_audio(url: str, max_size: int = DEFAULT_MAX_SIZE_BYTES,
                    timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[bytes, str, str]:
    """Download audio bytes from a URL. Returns (raw_bytes, content_type, file_name)."""
    import urllib.request
    import urllib.error

    parsed = urlparse(url)
    url_path = parsed.path.rstrip("/")
    file_name = url_path.split("/")[-1] if url_path else "audio"

    req = urllib.request.Request(url, headers={"User-Agent": "Agent_head/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cl = resp.headers.get("Content-Length")
            if cl and int(cl) > max_size:
                raise ValueError(
                    f"Remote audio too large: {int(cl)/(1024*1024):.1f} MB "
                    f"(max {max_size/(1024*1024):.1f} MB)"
                )
            raw = resp.read(max_size + 1)
            if len(raw) > max_size:
                raise ValueError(f"Remote audio exceeded {max_size/(1024*1024):.1f} MB limit")
            ct = resp.headers.get("Content-Type", "")
            return raw, ct, file_name
    except urllib.error.HTTPError as e:
        raise ValueError(f"HTTP {e.code} fetching {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise ConnectionError(f"Cannot reach {url}: {e.reason}") from e


# ─────────────────────────────────────────────────────────────────────────────
# 1. transcribe_audio_file  (Speech-to-Text)
# ─────────────────────────────────────────────────────────────────────────────

def transcribe_audio_file(file_path: str) -> str:
    """
    Transcribe speech from an audio file to text using SpeechRecognition.

    Uses Google's free Speech Recognition API by default.
    Supports local paths and HTTP/HTTPS URLs.

    Requires: pip install SpeechRecognition pydub
    Also requires ffmpeg for non-WAV formats.

    Returns the transcribed text.
    """
    try:
        import speech_recognition as sr
    except ImportError:
        raise ImportError(
            "Speech-to-text requires 'SpeechRecognition'. Install with:\n"
            "  pip install SpeechRecognition pydub\n"
            "For non-WAV formats, also install ffmpeg:\n"
            "  Windows: choco install ffmpeg  OR  download from https://ffmpeg.org\n"
            "  Linux:   sudo apt install ffmpeg\n"
            "  macOS:   brew install ffmpeg"
        )

    import tempfile
    import os

    # If URL, download first
    if _is_url(file_path):
        raw, ct, fname = _download_audio(file_path)
        ext = Path(fname).suffix or ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(raw)
        tmp.close()
        audio_path = tmp.name
        cleanup = True
    else:
        audio_path = str(Path(file_path).resolve())
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        cleanup = False

    try:
        ext = Path(audio_path).suffix.lower()

        # For non-WAV formats, convert to WAV using pydub
        if ext != ".wav":
            try:
                from pydub import AudioSegment
            except ImportError:
                raise ImportError(
                    "Non-WAV audio requires 'pydub' for conversion. Install with:\n"
                    "  pip install pydub\n"
                    "Also requires ffmpeg installed on system."
                )
            audio_seg = AudioSegment.from_file(audio_path)
            wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            wav_tmp.close()
            audio_seg.export(wav_tmp.name, format="wav")
            wav_path = wav_tmp.name
            cleanup_wav = True
        else:
            wav_path = audio_path
            cleanup_wav = False

        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)

            try:
                text = recognizer.recognize_google(audio_data)
                logger.info("Transcribed %d chars from %s", len(text), file_path)
                return text
            except sr.UnknownValueError:
                return "(Could not understand audio — no speech detected or audio is unclear)"
            except sr.RequestError as e:
                return f"(Speech recognition service error: {e})"
        finally:
            if cleanup_wav and wav_path != audio_path:
                os.unlink(wav_path)
    finally:
        if cleanup:
            os.unlink(audio_path)


# ─────────────────────────────────────────────────────────────────────────────
# 2. text_to_speech_generate  (TTS)
# ─────────────────────────────────────────────────────────────────────────────

def text_to_speech_generate(
    text: str,
    output_path: str,
    language: str = "en",
) -> dict:
    """
    Generate speech audio from text using Google TTS.

    Requires: pip install gTTS

    Args:
        text: The text to convert to speech.
        output_path: File path to save the audio (MP3 format).
        language: Language code (default "en"). Examples: "en", "es", "fr", "de", "ja".

    Returns dict: saved_to, file_size_bytes, file_name, language.
    """
    try:
        from gtts import gTTS
    except ImportError:
        raise ImportError(
            "Text-to-speech requires 'gTTS'. Install with:\n"
            "  pip install gTTS"
        )

    out = Path(output_path).resolve()
    # Ensure .mp3 extension
    if out.suffix.lower() != ".mp3":
        out = out.with_suffix(".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)

    tts = gTTS(text=text, lang=language)
    tts.save(str(out))

    logger.info("TTS saved to %s (%d bytes, lang=%s)", out, out.stat().st_size, language)

    return {
        "saved_to": str(out),
        "file_name": out.name,
        "file_size_bytes": out.stat().st_size,
        "language": language,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 3. save_audio_to_disk
# ─────────────────────────────────────────────────────────────────────────────

def save_audio_to_disk(source: str, destination: str) -> dict:
    """
    Save an audio file from URL or local path to a destination on disk.

    Args:
        source: HTTP/HTTPS URL or local file path.
        destination: Target file path.

    Returns dict: saved_to, file_name, file_size_bytes.
    """
    dest = Path(destination).resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)

    if _is_url(source):
        raw, ct, fname = _download_audio(source)
        dest.write_bytes(raw)
        logger.info("Saved audio from URL to %s (%d bytes)", dest, len(raw))
    else:
        src = Path(source).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Source not found: {src}")
        if not src.is_file():
            raise ValueError(f"Source is not a file: {src}")
        shutil.copy2(src, dest)
        logger.info("Copied audio %s → %s", src, dest)

    return {
        "saved_to": str(dest),
        "file_name": dest.name,
        "file_size_bytes": dest.stat().st_size,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. record_audio_clip
# ─────────────────────────────────────────────────────────────────────────────

def record_audio_clip(
    duration: float,
    output_path: str,
    sample_rate: int = 44100,
) -> dict:
    """
    Record audio from the default microphone.

    Requires: pip install sounddevice scipy

    Args:
        duration: Recording duration in seconds.
        output_path: File path to save the recording (WAV format).
        sample_rate: Sample rate in Hz (default 44100).

    Returns dict: saved_to, file_name, file_size_bytes, duration_seconds.
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise ImportError(
            "Audio recording requires 'sounddevice'. Install with:\n"
            "  pip install sounddevice"
        )
    try:
        from scipy.io import wavfile
    except ImportError:
        raise ImportError(
            "Audio recording requires 'scipy' for WAV writing. Install with:\n"
            "  pip install scipy"
        )
    import numpy as np

    out = Path(output_path).resolve()
    if out.suffix.lower() != ".wav":
        out = out.with_suffix(".wav")
    out.parent.mkdir(parents=True, exist_ok=True)

    # Cap duration for safety
    if duration > 300:
        raise ValueError("Recording duration cannot exceed 300 seconds (5 minutes)")
    if duration <= 0:
        raise ValueError("Recording duration must be positive")

    logger.info("Recording %0.1f seconds of audio at %d Hz...", duration, sample_rate)
    recording = sd.rec(
        int(duration * sample_rate),
        samplerate=sample_rate,
        channels=1,
        dtype="int16",
    )
    sd.wait()  # Block until recording is done

    wavfile.write(str(out), sample_rate, recording)

    logger.info("Recording saved to %s (%d bytes)", out, out.stat().st_size)

    return {
        "saved_to": str(out),
        "file_name": out.name,
        "file_size_bytes": out.stat().st_size,
        "duration_seconds": duration,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. play_audio_file
# ─────────────────────────────────────────────────────────────────────────────

def play_audio_file(file_path: str) -> dict:
    """
    Play an audio file through the system speakers.

    Uses pydub to decode any format and sounddevice for playback.
    Supports local paths and HTTP/HTTPS URLs.

    Returns dict: file_name, duration_seconds, played.
    """
    try:
        import sounddevice as sd
    except ImportError:
        raise ImportError(
            "Audio playback requires 'sounddevice'. Install with:\n"
            "  pip install sounddevice"
        )
    try:
        from pydub import AudioSegment
    except ImportError:
        raise ImportError(
            "Audio playback requires 'pydub'. Install with:\n"
            "  pip install pydub"
        )
    import numpy as np
    import tempfile
    import os

    # Handle URL
    if _is_url(file_path):
        raw, _, fname = _download_audio(file_path)
        ext = Path(fname).suffix or ".mp3"
        tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
        tmp.write(raw)
        tmp.close()
        audio_path = tmp.name
        cleanup = True
    else:
        audio_path = str(Path(file_path).resolve())
        if not Path(audio_path).exists():
            raise FileNotFoundError(f"Audio file not found: {audio_path}")
        cleanup = False

    try:
        audio = AudioSegment.from_file(audio_path)
        # Convert to numpy float32 array
        samples = np.array(audio.get_array_of_samples())
        if audio.channels == 2:
            samples = samples.reshape((-1, 2))
        samples = samples.astype(np.float32) / (2 ** (audio.sample_width * 8 - 1))

        logger.info("Playing audio: %s (%.1fs)", Path(audio_path).name, len(audio) / 1000)
        sd.play(samples, samplerate=audio.frame_rate)
        sd.wait()  # Block until playback finishes

        return {
            "file_name": Path(audio_path).name,
            "duration_seconds": round(len(audio) / 1000.0, 1),
            "played": True,
        }
    finally:
        if cleanup:
            os.unlink(audio_path)


# ─────────────────────────────────────────────────────────────────────────────
# 6. speak_text  (TTS + Play in one step)
# ─────────────────────────────────────────────────────────────────────────────

def speak_text(text: str, language: str = "en", audio_dir: str = "./audio") -> dict:
    """
    Convert text to speech and immediately play it through speakers.

    Combines TTS generation + playback in one call.

    Args:
        text: The text to speak.
        language: Language code (default "en").
        audio_dir: Directory to save the generated audio.

    Returns dict: saved_to, duration_seconds, played.
    """
    import time as _time

    _dir = Path(audio_dir)
    _dir.mkdir(parents=True, exist_ok=True)
    ts = _time.strftime("%Y%m%d_%H%M%S")
    save_path = str(_dir / f"speak_{ts}.mp3")

    # Generate TTS
    tts_result = text_to_speech_generate(text, save_path, language=language)

    # Play it
    play_result = play_audio_file(tts_result["saved_to"])

    return {
        "saved_to": tts_result["saved_to"],
        "file_name": tts_result["file_name"],
        "duration_seconds": play_result["duration_seconds"],
        "played": True,
        "language": language,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Tool factory — creates all LangChain audio tools
# ─────────────────────────────────────────────────────────────────────────────

def get_audio_tools(
    enabled: bool = True,
    enable_transcribe: bool = True,
    enable_tts: bool = True,
    enable_save: bool = True,
    enable_record: bool = True,
    enable_play: bool = True,
    enable_speak: bool = True,
    audio_dir: str = "./audio",
) -> list:
    """
    Create and return audio-related LangChain tools based on config flags.

    Args:
        enabled: Master switch. If False, returns empty list.
        enable_transcribe: Include the transcribe_audio tool (STT).
        enable_tts: Include the text_to_speech tool.
        enable_save: Include the save_audio tool.
        enable_record: Include the record_audio tool.
        enable_play: Include the play_audio tool.
        enable_speak: Include the speak tool (TTS + play).
        audio_dir: Directory for auto-saving audio files.

    Returns list of LangChain tools.
    """
    if not enabled:
        return []

    from langchain_core.tools import tool as lc_tool

    tools = []

    # ── 1. transcribe_audio (Speech-to-Text) ──────────────────────────────

    if enable_transcribe:
        @lc_tool
        def transcribe_audio(file_path: str) -> str:
            """
            Transcribe speech from an audio file to text.
            Use this to convert spoken words in audio files to written text.

            Supports local paths and HTTP/HTTPS URLs.
            Supported formats: MP3, WAV, OGG, FLAC, M4A, AAC, AIFF, WEBM, OPUS.
            Requires SpeechRecognition + pydub (and ffmpeg for non-WAV).

            args:
                file_path (str): Local path or URL to the audio file.
            """
            return transcribe_audio_file(file_path)

        tools.append(transcribe_audio)

    # ── 2. text_to_speech ─────────────────────────────────────────────────

    if enable_tts:
        _audio_dir = audio_dir

        @lc_tool
        def text_to_speech(
            text: str,
            output_path: str = "",
            language: str = "en",
        ) -> str:
            """
            Convert text to spoken audio (MP3 file).
            Use this to generate speech audio from written text.

            args:
                text (str): The text to convert to speech.
                output_path (str): File path to save. Leave empty to auto-save to the audio directory.
                language (str): Language code. Default "en". Examples: "en", "es", "fr", "de", "ja", "zh", "ko".
            """
            import time as _time
            save_path = output_path if output_path else None
            if not save_path:
                _dir = Path(_audio_dir)
                _dir.mkdir(parents=True, exist_ok=True)
                ts = _time.strftime("%Y%m%d_%H%M%S")
                save_path = str(_dir / f"tts_{ts}.mp3")

            result = text_to_speech_generate(text, save_path, language=language)
            return (
                f"Audio generated successfully.\n"
                f"  Path: {result['saved_to']}\n"
                f"  Size: {result['file_size_bytes']} bytes\n"
                f"  Language: {result['language']}"
            )

        tools.append(text_to_speech)

    # ── 3. save_audio ─────────────────────────────────────────────────────

    if enable_save:
        @lc_tool
        def save_audio(source: str, destination: str) -> str:
            """
            Save/download an audio file to a local file path.
            Use this to download audio from a URL or copy a local audio file to a new location.

            args:
                source (str): HTTP/HTTPS URL or local file path of the source audio.
                destination (str): Local file path to save the audio to.
            """
            result = save_audio_to_disk(source, destination)
            return (
                f"Audio saved successfully.\n"
                f"  Path: {result['saved_to']}\n"
                f"  Size: {result['file_size_bytes']} bytes"
            )

        tools.append(save_audio)

    # ── 4. record_audio ───────────────────────────────────────────────────

    if enable_record:
        _audio_dir_rec = audio_dir

        @lc_tool
        def record_audio(
            duration: float = 5.0,
            output_path: str = "",
        ) -> str:
            """
            Record audio from the microphone for a specified duration.
            Use this to capture spoken input or ambient audio.

            Maximum recording: 300 seconds (5 minutes).
            Requires sounddevice + scipy.

            args:
                duration (float): Recording duration in seconds. Default 5 seconds.
                output_path (str): File path to save. Leave empty to auto-save to the audio directory.
            """
            import time as _time
            save_path = output_path if output_path else None
            if not save_path:
                _dir = Path(_audio_dir_rec)
                _dir.mkdir(parents=True, exist_ok=True)
                ts = _time.strftime("%Y%m%d_%H%M%S")
                save_path = str(_dir / f"recording_{ts}.wav")

            result = record_audio_clip(duration, save_path)
            return (
                f"Audio recorded successfully.\n"
                f"  Path: {result['saved_to']}\n"
                f"  Duration: {result['duration_seconds']}s\n"
                f"  Size: {result['file_size_bytes']} bytes"
            )

        tools.append(record_audio)

    # ── 5. play_audio ─────────────────────────────────────────────────────

    if enable_play:
        @lc_tool
        def play_audio(file_path: str) -> str:
            """
            Play an audio file through the system speakers.
            Use this to play music, voice recordings, or any audio file out loud.

            Supports local paths and HTTP/HTTPS URLs.
            Supported formats: MP3, WAV, OGG, FLAC, M4A, and more.

            args:
                file_path (str): Local path or URL to the audio file to play.
            """
            result = play_audio_file(file_path)
            return (
                f"Audio played successfully.\n"
                f"  File: {result['file_name']}\n"
                f"  Duration: {result['duration_seconds']}s"
            )

        tools.append(play_audio)

    # ── 6. speak (TTS + play in one step) ─────────────────────────────────

    if enable_speak:
        _audio_dir_speak = audio_dir

        @lc_tool
        def speak(
            text: str,
            language: str = "en",
        ) -> str:
            """
            Speak text out loud through the system speakers.
            Converts text to speech and immediately plays it. Use this when you want to
            verbally communicate with the user — the agent's voice.

            args:
                text (str): The text to speak out loud.
                language (str): Language code. Default "en". Examples: "en", "es", "fr", "de", "ja".
            """
            result = speak_text(text, language=language, audio_dir=_audio_dir_speak)
            return (
                f"Spoke text out loud.\n"
                f"  Duration: {result['duration_seconds']}s\n"
                f"  Saved to: {result['saved_to']}"
            )

        tools.append(speak)

    return tools
