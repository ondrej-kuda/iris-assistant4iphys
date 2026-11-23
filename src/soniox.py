# Provides reusable Soniox streaming and token-processing components.

from __future__ import annotations

import json
import queue
import re
import sys
import threading
import textwrap
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from websockets.sync.client import ClientConnection, connect

from config import Settings, application_root
from languages import TranslationDirection
from subtitles import SubtitleState


# Callback invoked with each ordered batch of Soniox tokens.
# @type Callable[[list[dict[str, Any]]], None]
TokenHandler = Callable[[list[dict[str, Any]]], None]


class SonioxStreamError(RuntimeError):
    # Represents an error response returned by a Soniox real-time session.
    # --------------------------------------------------------------------------
    # The message contains Soniox's human-readable error detail for display by the
    # application boundary.
    # --------------------------------------------------------------------------
    pass
#end class


def format_for_screen(raw: str, settings: Settings) -> list[str]:
    # Wraps recent text into the configured subtitle-window capacity.
    # --------------------------------------------------------------------------
    # @param raw: Unformatted text buffer to render.
    # @param settings: Validated UI display limits.
    # @return: Most recent wrapped lines, or an empty list when text is blank.
    # --------------------------------------------------------------------------
    # normalize empty input before applying display limits.
    raw = raw.strip()
    if not raw:
        return []

    # retain only recent content so stale subtitles cannot dominate the display.
    if len(raw) > settings.ui.max_display_chars:
        raw = raw[-settings.ui.max_display_chars:].lstrip()

    # wrap and retain only lines that fit the configured subtitle window.
    wrapped_lines = textwrap.wrap(
        raw,
        width=settings.ui.max_line_chars_approx,
        break_long_words=False,
    )
    if len(wrapped_lines) > settings.ui.max_lines_on_screen:
        wrapped_lines = wrapped_lines[-settings.ui.max_lines_on_screen:]
    return wrapped_lines
#end def


def normalize_for_search(value: str) -> str:
    # Normalizes whitespace for reliable text comparison.
    # --------------------------------------------------------------------------
    # @param value: Source text to normalize.
    # @return: Trimmed text with internal whitespace collapsed.
    # --------------------------------------------------------------------------
    return " ".join(value.strip().split())
#end def


def normalize_trigger_text(value: str) -> str:
    # Normalizes trigger speech while ignoring punctuation and capitalization.
    # --------------------------------------------------------------------------
    # @param value: Recognized original-speech text.
    # @return: Lowercase word sequence suitable for phrase matching.
    # --------------------------------------------------------------------------
    return " ".join(re.findall(r"[^\W_]+", value.casefold(), flags=re.UNICODE))
#end def


def build_realtime_config(
    *,
    api_key: str,
    model: str,
    audio_format: str,
    sample_rate: int,
    channels: int,
    language_hints: Iterable[str] = (),
    enable_endpoint_detection: bool = False,
    context: Mapping[str, Any] | None = None,
    translation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    # Builds a Soniox real-time session configuration.
    # --------------------------------------------------------------------------
    # This builder keeps raw-audio metadata consistent for the translator.
    # @param api_key: Soniox credential used to authenticate the stream.
    # @param model: Soniox real-time model identifier.
    # @param audio_format: Soniox raw-audio encoding identifier.
    # @param sample_rate: Audio sampling frequency in Hz.
    # @param channels: Number of audio channels.
    # @param language_hints: Preferred recognition languages.
    # @param enable_endpoint_detection: Whether pauses force early finalization.
    # @param context: Optional Soniox context object containing glossary terms.
    # @param translation: Optional Soniox translation configuration block.
    # @return: JSON-serializable Soniox session configuration.
    # --------------------------------------------------------------------------
    # include common authentication, model, and raw-audio fields for every session.
    config: dict[str, Any] = {
        "api_key": api_key,
        "model": model,
        "audio_format": audio_format,
        "sample_rate": sample_rate,
        "num_channels": channels,
        "language_hints": list(language_hints),
        "enable_endpoint_detection": enable_endpoint_detection,
    }

    # add translation only for consumers that request translated tokens.
    if translation is not None:
        config["translation"] = dict(translation)
    # add the glossary once at session start so it guides the complete stream.
    if context is not None:
        config["context"] = dict(context)
    return config
#end def


def load_soniox_context() -> dict[str, Any]:
    # Loads and validates the bundled Soniox glossary context.
    # --------------------------------------------------------------------------
    # The JSON file is bundled as a runtime asset and resolved through the same
    # application-root helper used by the greeting and watermark assets.
    # @return: Soniox-compatible context object loaded from the glossary file.
    # @throws RuntimeError: If the bundled glossary is missing, invalid, or too large.
    # --------------------------------------------------------------------------
    # resolve the bundled glossary beside the other packaged runtime assets.
    context_path = application_root() / "soniox_context_cs_en.json"

    # fail early when a build omitted the glossary asset instead of opening a
    # session that cannot apply the requested terminology.
    if not context_path.exists():
        raise RuntimeError(f"Missing Soniox glossary file: {context_path}")

    try:
        raw_context = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cannot load Soniox glossary file: {context_path}") from error

    # accept either the documented context object itself or a wrapper containing
    # a `context` property, which makes the asset convenient to edit and reuse.
    if isinstance(raw_context, dict) and isinstance(raw_context.get("context"), dict):
        context = raw_context["context"]
    elif isinstance(raw_context, dict):
        context = raw_context
    else:
        raise RuntimeError("Soniox glossary must contain a JSON object")

    # serialize compactly because Soniox measures the context payload rather than
    # the source file's whitespace-padded representation.
    compact_context = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    if len(compact_context) > 10_000:
        print(
            "Warning: Soniox glossary is larger than the documented ~10,000-character "
            f"guideline ({len(compact_context)} characters): {context_path}"
        )
    return context
#end def


def build_soniox_config(settings: Settings) -> dict[str, Any]:
    # Builds the translator's Soniox real-time session configuration.
    # --------------------------------------------------------------------------
    # @param settings: Validated translator application settings.
    # @return: JSON-serializable Soniox session configuration.
    # --------------------------------------------------------------------------
    return build_realtime_config(
        api_key=settings.soniox.api_key,
        model=settings.soniox.model,
        audio_format=settings.audio.audio_format,
        sample_rate=settings.audio.sample_rate,
        channels=settings.audio.channels,
        language_hints=(settings.translation.source_language,),
        enable_endpoint_detection=settings.soniox.enable_endpoint_detection,
        context=load_soniox_context(),
        translation={
            "type": "one_way",
            "target_language": settings.translation.target_language,
        },
    )
#end def


def stream_realtime(
    *,
    ws_url: str,
    config: Mapping[str, Any],
    audio_q: "queue.Queue[bytes]",
    stop_evt: threading.Event,
    on_tokens: TokenHandler,
    should_restart: Callable[[], bool] | None = None,
) -> None:
    # Runs a reusable Soniox real-time audio session.
    # --------------------------------------------------------------------------
    # A sender thread forwards queued PCM frames while the calling thread receives
    # ordered token batches. Setting stop_evt sends Soniox's end-of-stream marker.
    # @param ws_url: Soniox real-time WebSocket endpoint.
    # @param config: JSON-serializable session configuration.
    # @param audio_q: Bounded queue of audio frame bytes.
    # @param stop_evt: Shared event that requests graceful stream shutdown.
    # @param on_tokens: Consumer invoked for every non-empty token batch.
    # @param should_restart: Optional callback requesting a direction restart.
    # @return: None.
    # @throws SonioxStreamError: If Soniox returns an error response.
    # --------------------------------------------------------------------------
    # use a session-local stop event so a direction change can restart only the
    # network session while leaving microphone capture and the UI running.
    session_stop_evt = threading.Event()

    # establish and configure the session before starting the audio sender.
    with connect(ws_url, ping_interval=20) as websocket:
        websocket.send(json.dumps(dict(config)))
        sender = threading.Thread(
            target=_send_audio,
            args=(websocket, audio_q, session_stop_evt),
            name="soniox-audio-sender",
            daemon=True,
        )
        sender.start()

        try:
            # receive JSON results until local shutdown or remote completion.
            while not stop_evt.is_set() and not (
                should_restart is not None and should_restart()
            ):
                # poll briefly so a language selection can restart a silent session.
                try:
                    message = websocket.recv(timeout=0.2)
                except TimeoutError:
                    continue
                if message is None or isinstance(message, bytes):
                    continue

                # reject malformed server data and surface structured API errors.
                try:
                    response = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if response.get("error_code") is not None:
                    raise SonioxStreamError(
                        response.get("error_message", response.get("error_type", "Soniox error"))
                    )

                # deliver each token batch once before honoring remote completion.
                tokens = response.get("tokens") or []
                if tokens:
                    on_tokens(tokens)
                if response.get("finished"):
                    break
        finally:
            # ask the sender to emit the end marker while the socket remains open.
            session_stop_evt.set()
            sender.join(timeout=2)
#end def


def token_is_original_spoken(token: Mapping[str, Any]) -> bool:
    # Identifies tokens that represent original speech rather than translation.
    # --------------------------------------------------------------------------
    # @param token: Soniox token payload.
    # @return: True when the token belongs to the spoken transcript.
    # --------------------------------------------------------------------------
    return token.get("translation_status", "none") in ("none", "original")
#end def


def token_is_translation(token: Mapping[str, Any]) -> bool:
    # Identifies tokens emitted by Soniox's translation pipeline.
    # --------------------------------------------------------------------------
    # @param token: Soniox token payload.
    # @return: True when the token is translated text.
    # --------------------------------------------------------------------------
    return token.get("translation_status") == "translation"
#end def


def token_is_final(token: Mapping[str, Any]) -> bool:
    # Identifies tokens that Soniox will not revise later.
    # --------------------------------------------------------------------------
    # @param token: Soniox token payload.
    # @return: True when the token is final.
    # --------------------------------------------------------------------------
    return bool(token.get("is_final", False))
#end def


def append_final_translation(
    subtitles: SubtitleState,
    translated_piece: str,
    settings: Settings,
) -> None:
    # Formats final translated text and appends it to shared subtitle state.
    # --------------------------------------------------------------------------
    # @param subtitles: Thread-safe subtitle state updated for the UI.
    # @param translated_piece: Final Soniox translation text.
    # @param settings: Validated subtitle display settings.
    # @return: None.
    # --------------------------------------------------------------------------
    # avoid updating UI state for empty finalization events.
    if not translated_piece:
        return
    subtitles.add(format_for_screen(translated_piece, settings))
#end def


def play_trigger_audio(audio_file: str) -> None:
    # Starts the configured trigger MP3 without blocking translation processing.
    # --------------------------------------------------------------------------
    # Windows Media Control Interface (MCI) is used through the standard library
    # so the packaged translator does not need a separate multimedia runtime.
    # @param audio_file: Absolute path or repository-relative MP3 path.
    # @return: None.
    # --------------------------------------------------------------------------
    try:
        # resolve bundled assets first, then allow a launch-directory override.
        path = Path(audio_file).expanduser()
        if not path.is_absolute():
            bundled_path = application_root() / path
            launch_path = Path.cwd() / path
            path = bundled_path if bundled_path.exists() else launch_path
        if not path.exists():
            raise FileNotFoundError(f"Trigger audio file not found: {path}")

        # use the Windows multimedia subsystem so MP3 playback stays asynchronous.
        if sys.platform != "win32":
            raise OSError("trigger audio playback requires Windows MCI")
        import ctypes

        mci_send_string = ctypes.windll.winmm.mciSendStringW
        mci_send_string("close iris_trigger", None, 0, 0)
        open_result = mci_send_string(
            f'open "{path}" type mpegvideo alias iris_trigger',
            None,
            0,
            0,
        )
        if open_result:
            raise OSError(f"Windows MCI could not open {path}")
        print(f"Playing trigger audio: {path}")
        play_result = mci_send_string("play iris_trigger", None, 0, 0)
        if play_result:
            mci_send_string("close iris_trigger", None, 0, 0)
            raise OSError(f"Windows MCI could not play {path}")
    except Exception as error:
        print(f"Trigger audio failed: {error}")
#end def


def soniox_worker(
    audio_q: "queue.Queue[bytes]",
    subtitles: SubtitleState,
    stop_evt: threading.Event,
    settings: Settings,
    direction: TranslationDirection,
) -> None:
    # Streams microphone frames and applies matching translations to subtitles.
    # --------------------------------------------------------------------------
    # @param audio_q: Bounded queue of microphone PCM frame bytes.
    # @param subtitles: Shared subtitle state consumed by the UI thread.
    # @param stop_evt: Event requesting graceful stream shutdown.
    # @param settings: Validated Soniox, audio, and translation settings.
    # @param direction: Thread-safe runtime source and target language selection.
    # @return: None.
    # @throws RuntimeError: If the Soniox API key is missing.
    # --------------------------------------------------------------------------
    # reject missing credentials before establishing the remote connection.
    if not settings.soniox.api_key:
        raise RuntimeError("Missing SONIOX_API_KEY environment variable.")

    # retain a bounded normalized original-speech buffer for magic-phrase matching.
    trigger_buffer = ""
    trigger_armed = True
    termination_buffer = ""
    termination_phrases = tuple(
        normalize_trigger_text(phrase)
        for phrase in settings.trigger.termination_phrases
        if normalize_trigger_text(phrase)
    )
    trigger_phrase = normalize_trigger_text(settings.trigger.magic_phrase)
    if not settings.trigger.magic_phrase_case_insensitive:
        trigger_phrase = settings.trigger.magic_phrase.strip()

    def check_magic_phrase_text(text: str) -> None:
        # Detects the spoken trigger in either original or accepted translated text.
        # ----------------------------------------------------------------------
        # @param text: Text fragment emitted by the current Soniox response.
        # @return: None.
        # ----------------------------------------------------------------------
        nonlocal trigger_buffer, trigger_armed

        # ignore empty/control fragments and avoid retriggering repeated interim
        # translation updates for the same short phrase.
        if not text or text == "<end>":
            return
        normalized_text = normalize_trigger_text(text)
        if not normalized_text:
            return
        if not trigger_armed:
            if normalized_text != trigger_phrase:
                trigger_armed = True
            else:
                return

        # keep enough recent speech to match phrases split across responses.
        trigger_buffer = f"{trigger_buffer} {text}".strip()
        trigger_buffer = trigger_buffer[-settings.trigger.detection_buffer_chars :]
        haystack = (
            normalize_trigger_text(trigger_buffer)
            if settings.trigger.magic_phrase_case_insensitive
            else trigger_buffer
        )
        if trigger_phrase not in haystack:
            return

        # reset old subtitle rows before showing the dedicated response.
        if settings.trigger.clear_buffers_on_trigger:
            subtitles.clear()
        subtitles.add(format_for_screen(settings.trigger.message, settings))
        print(f"Magic phrase recognized: {settings.trigger.magic_phrase}")
        play_trigger_audio(settings.trigger.audio_file)

        # remove the matched phrase so unrelated later tokens cannot retrigger it.
        trigger_buffer = ""
        trigger_armed = False
    #end def

    def check_termination_phrase_text(text: str) -> None:
        # Requests application shutdown when an original speech phrase matches.
        # ----------------------------------------------------------------------
        # Keep termination matching separate from the magic phrase buffer so the
        # configured shutdown phrases are not affected by translation tokens.
        # @param text: Original-speech text fragment from Soniox.
        # @return: None.
        # ----------------------------------------------------------------------
        nonlocal termination_buffer

        # ignore empty/control fragments and preserve a bounded rolling buffer.
        if not text or text == "<end>" or not termination_phrases:
            return
        termination_buffer = f"{termination_buffer} {text}".strip()
        termination_buffer = termination_buffer[-settings.trigger.detection_buffer_chars :]
        normalized_buffer = normalize_trigger_text(termination_buffer)
        if not any(phrase in normalized_buffer for phrase in termination_phrases):
            return

        # let the UI close itself and the application boundary release resources.
        print("Termination phrase recognized.")
        stop_evt.set()
        subtitles.clear()
    #end def

    def check_magic_phrase(tokens: list[dict[str, Any]]) -> None:
        # Checks original-speech tokens for the configured magic phrase.
        # ----------------------------------------------------------------------
        # @param tokens: Ordered Soniox token payloads from one response.
        # @return: None.
        # ----------------------------------------------------------------------
        for token in tokens:
            if not token_is_original_spoken(token):
                continue
            original_text = str(token.get("text", ""))
            check_termination_phrase_text(original_text)
            if stop_evt.is_set():
                return
            check_magic_phrase_text(original_text)
    #end def

    def handle_tokens(tokens: list[dict[str, Any]]) -> None:
        # Filters one token batch into displayable translation text.
        # ----------------------------------------------------------------------
        # @param tokens: Ordered Soniox token payloads from one response.
        # @return: None.
        # ----------------------------------------------------------------------
        # process original speech independently so the trigger does not interrupt
        # the normal translation-token path below.
        check_magic_phrase(tokens)

        # select translated tokens matching the configured language pair and finality.
        translated_parts: list[str] = []
        for token in tokens:
            if not token_is_translation(token):
                continue
            if token.get("source_language") != session_settings.translation.source_language:
                continue
            if token.get("language") != session_settings.translation.target_language:
                continue
            if session_settings.translation.display_only_final_translations and not token_is_final(token):
                continue
            translated_parts.append(str(token.get("text", "")))

        # update shared subtitle state only when the response adds visible text.
        translated_piece = "".join(translated_parts)
        if translated_piece:
            print(">>>", translated_piece)
            # Some Soniox translation responses expose the spoken phrase only as
            # an accepted translation token, so check it as a fallback as well.
            check_magic_phrase_text(translated_piece)
            append_final_translation(subtitles, translated_piece, session_settings)
    #end def

    # restart the network session whenever the UI changes language direction.
    session_settings = settings
    session_version = -1
    while not stop_evt.is_set():
        source_language, target_language, current_version = direction.snapshot()
        session_settings = replace(
            settings,
            translation=replace(
                settings.translation,
                source_language=source_language,
                target_language=target_language,
            ),
        )
        session_version = current_version

        # discard old subtitle rows so a direction change cannot mix languages.
        subtitles.clear()

        # compose translator-specific token handling with the current stream.
        stream_realtime(
            ws_url=session_settings.soniox.ws_url,
            config=build_soniox_config(session_settings),
            audio_q=audio_q,
            stop_evt=stop_evt,
            on_tokens=handle_tokens,
            should_restart=lambda: direction.snapshot()[2] != session_version,
        )

        # a normal remote completion should not spin reconnects during shutdown.
        if stop_evt.is_set():
            break
#end def


def _send_audio(
    websocket: ClientConnection,
    audio_q: "queue.Queue[bytes]",
    stop_evt: threading.Event,
) -> None:
    # Sends queued audio frames and finalizes the Soniox stream on shutdown.
    # --------------------------------------------------------------------------
    # @param websocket: Connected Soniox WebSocket.
    # @param audio_q: Bounded queue of audio frame bytes.
    # @param stop_evt: Event requesting graceful stream shutdown.
    # @return: None.
    # --------------------------------------------------------------------------
    try:
        # wait briefly for frames so shutdown remains responsive during silence.
        while not stop_evt.is_set():
            try:
                websocket.send(audio_q.get(timeout=0.1))
            except queue.Empty:
                continue

        # send the documented empty binary frame to finalize pending tokens.
        websocket.send(b"")
    except Exception:
        # leave connection errors to the receiver and ensure all workers stop.
        stop_evt.set()
#end def
