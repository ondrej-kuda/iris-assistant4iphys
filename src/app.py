# Composes the translator application components.

from __future__ import annotations

import argparse
import queue
import threading
from collections.abc import Sequence

import microphone
import soniox
import subtitles
import window
from config import Settings, load_settings
from languages import TranslationDirection


def translator_main(argv: Sequence[str] | None = None) -> int:
    # Starts microphone translation, Soniox streaming, and the subtitle UI.
    # --------------------------------------------------------------------------
    # The UI owns the foreground thread while the reusable Soniox worker runs in a
    # daemon thread and consumes frames from the shared microphone component.
    # @param argv: Optional command-line arguments; None reads the process arguments.
    # @return: Process exit code.
    # --------------------------------------------------------------------------
    # require a per-run source while allowing the target to follow direction defaults.
    parser = argparse.ArgumentParser(
        description="Translate microphone audio with Soniox real-time translation."
    )
    parser.add_argument(
        "--source-lang",
        default=None,
        metavar="LANG",
        help="Spoken source language (default: translation.source_language from config.toml).",
    )
    parser.add_argument(
        "--target-lang",
        metavar="LANG",
        help="Translation target (default: translation.target_language from config.toml).",
    )
    # parse the complete direction before any configuration or hardware work.
    args = parser.parse_args(argv)

    # load the configured direction and apply optional command-line overrides.
    try:
        settings = load_settings(
            source_language=args.source_lang,
            target_language=args.target_lang,
        )
    except ValueError as error:
        parser.error(str(error))

    # print the effective direction after all configuration precedence is applied.
    print(_safe_settings_summary(settings))

    # create shared transport and display state for the application components.
    audio_q: "queue.Queue[bytes]" = queue.Queue(
        maxsize=settings.performance.audio_queue_max_chunks
    )
    stop_evt = threading.Event()
    state = subtitles.SubtitleState(max_lines=settings.ui.max_lines_on_screen)
    direction = TranslationDirection(
        settings.translation.source_language,
        settings.translation.target_language,
    )

    # start the common microphone producer and translator-specific Soniox consumer.
    mic_stream = microphone.start_microphone(audio_q, stop_evt, settings)
    worker = threading.Thread(
        target=soniox.soniox_worker,
        args=(audio_q, state, stop_evt, settings, direction),
        name="soniox-translation-worker",
        daemon=True,
    )
    worker.start()

    # run the subtitle UI until the user closes its foreground event loop.
    subtitle_window = window.SubtitleWindow(
        settings,
        on_language_change=direction.set,
    )
    try:
        subtitle_window.run(
            state,
            settings.performance.ui_tick_ms,
            stop_evt=stop_evt,
            clear_after_seconds=settings.performance.clear_subtitles_after_seconds,
        )
    finally:
        # signal streaming shutdown before releasing the shared microphone device.
        stop_evt.set()
        microphone.stop_input_stream(mic_stream)
    return 0
#end def


def _safe_settings_summary(settings: Settings) -> str:
    # Builds a log-safe summary of the active translator configuration.
    # --------------------------------------------------------------------------
    # The API key is represented only by presence so startup logs do not disclose it.
    # @param settings: Validated application configuration.
    # @return: Human-readable configuration summary safe for console output.
    # --------------------------------------------------------------------------
    return (
        "Loaded settings: "
        f"sample_rate={settings.audio.sample_rate}, "
        f"channels={settings.audio.channels}, "
        f"source_language={settings.translation.source_language}, "
        f"target_language={settings.translation.target_language}, "
        f"ws_url={settings.soniox.ws_url}, "
        f"api_key={'set' if settings.soniox.api_key else 'missing'}"
    )
#end def


def main(argv: Sequence[str] | None = None) -> int:
    # Preserves the original translator entry-point name for existing callers.
    # --------------------------------------------------------------------------
    # @param argv: Optional command-line arguments; None reads the process arguments.
    # @return: Process exit code from the translator application.
    # --------------------------------------------------------------------------
    return translator_main(argv)
#end def
