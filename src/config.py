# Loads validated translator configuration from files, environment, and CLI values.

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from languages import SUPPORTED_TRANSLATION_LANGUAGES, resolve_translation_languages

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


@dataclass(frozen=True)
class AudioConfig:
    # Defines the raw microphone stream format sent to Soniox.
    # --------------------------------------------------------------------------
    # @var sample_rate: Audio sampling frequency in Hz.
    # @var channels: Number of audio channels captured from the input device.
    # @var audio_format: Soniox raw-audio encoding identifier.
    # --------------------------------------------------------------------------
    # Default microphone sampling frequency in Hz.
    sample_rate: int = 16000
    # Default number of microphone channels.
    channels: int = 1
    # Default Soniox-compatible PCM encoding.
    audio_format: str = "pcm_s16le"


@dataclass(frozen=True)
class SonioxConfig:
    # Defines connection and recognition settings for Soniox streaming.
    # --------------------------------------------------------------------------
    # @var ws_url: Real-time WebSocket endpoint.
    # @var model: Soniox recognition model identifier.
    # @var enable_endpoint_detection: Whether pause detection finalizes speech.
    # @var api_key: Credential used to authenticate the stream.
    # --------------------------------------------------------------------------
    # Default real-time Soniox streaming endpoint.
    ws_url: str = "wss://stt-rt.soniox.com/transcribe-websocket"
    # Default Soniox model selected by the translator.
    model: str = "stt-rt-preview"
    # Default pause-based finalization behavior.
    enable_endpoint_detection: bool = True
    # API key supplied by configuration rather than source control.
    api_key: str = ""


@dataclass(frozen=True)
class TranslationConfig:
    # Defines the accepted source and displayed target translation languages.
    # --------------------------------------------------------------------------
    # @var source_language: Spoken language whose translations are accepted.
    # @var target_language: Language rendered in the subtitle window.
    # @var display_only_final_translations: Whether provisional tokens are hidden.
    # --------------------------------------------------------------------------
    # Expected language of original speech tokens, supplied at startup.
    source_language: str
    # Desired language of generated translation tokens, resolved at startup.
    target_language: str
    # Avoid displaying tokens that Soniox can still revise.
    display_only_final_translations: bool = True


@dataclass(frozen=True)
class TriggerConfig:
    # Defines retained text and reset behavior for trigger processing.
    # --------------------------------------------------------------------------
    # @var magic_phrase: Final spoken phrase that activates the response.
    # @var magic_phrase_case_insensitive: Whether phrase matching ignores case.
    # @var audio_file: MP3 played after the phrase is recognized.
    # @var message: Subtitle message shown after the phrase is recognized.
    # @var termination_phrases: Spoken phrases that stop the application.
    # @var detection_buffer_chars: Maximum retained trigger-search text length.
    # @var clear_buffers_on_trigger: Whether a trigger resets prior display state.
    # --------------------------------------------------------------------------
    # Spoken phrase that activates the Iris response.
    magic_phrase: str = "Iris?"
    # Whether trigger matching ignores capitalization.
    magic_phrase_case_insensitive: bool = True
    # MP3 path, relative to the application root unless absolute.
    audio_file: str = "assets/iris.mp3"
    # Subtitle response shown when the magic phrase is recognized.
    message: str = "At your service, Mr. Director"
    # Bilingual commands that terminate the presentation application.
    termination_phrases: tuple[str, ...] = (
        "Iris, end the presentation",
    )
    # Maximum number of characters retained for trigger matching.
    detection_buffer_chars: int = 600
    # Whether a successful trigger discards buffered content.
    clear_buffers_on_trigger: bool = True


@dataclass(frozen=True)
class UiConfig:
    # Defines subtitle-window appearance and display capacity.
    # --------------------------------------------------------------------------
    # @var max_lines_on_screen: Maximum wrapped lines retained in the window.
    # @var max_line_chars_approx: Approximate width used for text wrapping.
    # @var window_resizable: Whether the user may resize the window.
    # @var window_zoomed: Whether the window starts maximized.
    # @var window_keep_on_top: Whether the subtitle window stays above others.
    # @var window_borderless: Whether the native title bar is removed.
    # @var window_height_fraction: Fraction of screen height used by the overlay.
    # @var window_alpha: Whole-window opacity from 0.0 through 1.0.
    # @var window_background_color: Tk background color.
    # @var window_text_color: Tk foreground color.
    # @var window_new_text_color: Color used for the newest subtitle line.
    # @var window_font_family: Preferred text font family.
    # @var window_font_size: Text size in points.
    # @var window_font_weight: Text weight passed to Tk.
    # @var window_text_padding_x: Horizontal padding in pixels.
    # @var window_text_padding_y: Vertical padding in pixels.
    # @var max_display_chars: Maximum characters retained before clipping.
    # --------------------------------------------------------------------------
    # Maximum wrapped subtitle lines displayed at once.
    max_lines_on_screen: int = 2
    # Approximate character width used for subtitle wrapping.
    max_line_chars_approx: int = 42
    # Whether the user can resize the subtitle window.
    window_resizable: bool = True
    # Whether the subtitle window opens maximized.
    window_zoomed: bool = False
    # Whether the subtitle window remains on top of other windows.
    window_keep_on_top: bool = True
    # Whether the subtitle overlay hides the native Windows title bar.
    window_borderless: bool = True
    # Fraction of the screen height used by the bottom subtitle stripe.
    window_height_fraction: float = 0.20
    # Whole-window opacity, where 1.0 is opaque and 0.0 is invisible.
    window_alpha: float = 0.50
    # Background color passed to Tk.
    window_background_color: str = "black"
    # Foreground text color passed to Tk.
    window_text_color: str = "white"
    # Foreground color used to highlight the newest subtitle line.
    window_new_text_color: str = "yellow"
    # Preferred subtitle font family.
    window_font_family: str = "Segoe UI"
    # Subtitle font size in points.
    window_font_size: int = 36
    # Subtitle font weight passed to Tk.
    window_font_weight: str = "bold"
    # Horizontal subtitle padding in pixels.
    window_text_padding_x: int = 70
    # Vertical subtitle padding in pixels.
    window_text_padding_y: int = 8
    # Maximum characters retained in the subtitle buffer.
    max_display_chars: int = 1200


@dataclass(frozen=True)
class PerformanceConfig:
    # Defines queueing and refresh limits for the real-time application.
    # --------------------------------------------------------------------------
    # @var ui_tick_ms: Subtitle UI refresh interval in milliseconds.
    # @var audio_queue_max_chunks: Maximum queued microphone frame count.
    # @var clear_subtitles_after_seconds: Subtitle idle-timeout configuration.
    # --------------------------------------------------------------------------
    # Interval between Tk UI refresh callbacks in milliseconds.
    ui_tick_ms: int = 60
    # Bounded microphone frame queue capacity.
    audio_queue_max_chunks: int = 300
    # Idle duration before subtitle content is eligible for clearing.
    clear_subtitles_after_seconds: float = 5.0


@dataclass(frozen=True)
class Settings:
    # Aggregates all validated application configuration sections.
    # --------------------------------------------------------------------------
    # @var translation: Runtime translation direction and filtering configuration.
    # @var audio: Audio capture configuration.
    # @var soniox: Soniox connection and recognition configuration.
    # @var trigger: Trigger-buffer configuration.
    # @var ui: Subtitle-window configuration.
    # @var performance: Queue and UI timing configuration.
    # --------------------------------------------------------------------------
    # Runtime translation direction and display-filtering configuration.
    translation: TranslationConfig
    # Audio capture configuration section.
    audio: AudioConfig = AudioConfig()
    # Soniox streaming configuration section.
    soniox: SonioxConfig = SonioxConfig()
    # Trigger-processing configuration section.
    trigger: TriggerConfig = TriggerConfig()
    # Subtitle-window configuration section.
    ui: UiConfig = UiConfig()
    # Real-time performance configuration section.
    performance: PerformanceConfig = PerformanceConfig()

    def validate(self) -> None:
        # Validates cross-section settings required before starting the application.
        # --------------------------------------------------------------------------
        # @throws ValueError: If a required value is empty or a numeric limit is invalid.
        # --------------------------------------------------------------------------
        # reject invalid audio capture values before opening a device.
        if self.audio.sample_rate <= 0:
            raise ValueError("audio.sample_rate must be > 0")
        if self.audio.channels <= 0:
            raise ValueError("audio.channels must be > 0")
        if self.audio.audio_format != "pcm_s16le":
            raise ValueError("audio.audio_format must be pcm_s16le")
        if not self.soniox.ws_url:
            raise ValueError("soniox.ws_url cannot be empty")
        if not self.soniox.model:
            raise ValueError("soniox.model cannot be empty")
        if not self.soniox.api_key:
            raise ValueError("SONIOX_API_KEY is required")
        if self.translation.source_language not in SUPPORTED_TRANSLATION_LANGUAGES:
            raise ValueError("translation source language is not supported")
        if self.translation.target_language not in SUPPORTED_TRANSLATION_LANGUAGES:
            raise ValueError("translation target language is not supported")
        if self.trigger.detection_buffer_chars <= 0:
            raise ValueError("trigger.detection_buffer_chars must be > 0")
        if not self.trigger.magic_phrase:
            raise ValueError("trigger.magic_phrase cannot be empty")
        if not self.trigger.audio_file:
            raise ValueError("trigger.audio_file cannot be empty")
        if not self.trigger.message:
            raise ValueError("trigger.message cannot be empty")
        if not self.trigger.termination_phrases:
            raise ValueError("trigger.termination_phrases cannot be empty")
        if any(not phrase.strip() for phrase in self.trigger.termination_phrases):
            raise ValueError("trigger.termination_phrases cannot contain empty phrases")
        if self.ui.max_lines_on_screen <= 0:
            raise ValueError("ui.max_lines_on_screen must be > 0")
        if self.ui.max_line_chars_approx <= 0:
            raise ValueError("ui.max_line_chars_approx must be > 0")
        if self.ui.window_font_size <= 0:
            raise ValueError("ui.window_font_size must be > 0")
        if self.ui.window_text_padding_x < 0 or self.ui.window_text_padding_y < 0:
            raise ValueError("ui.window_text_padding values must be >= 0")
        if self.ui.max_display_chars <= 0:
            raise ValueError("ui.max_display_chars must be > 0")
        for color_name, color_value in (
            ("window_background_color", self.ui.window_background_color),
            ("window_text_color", self.ui.window_text_color),
            ("window_new_text_color", self.ui.window_new_text_color),
        ):
            if not re.fullmatch(r"(?:#[0-9a-fA-F]{6}|[A-Za-z][A-Za-z0-9 ]*)", color_value.strip()):
                raise ValueError(f"ui.{color_name} is not a valid Tk color")
        if self.performance.ui_tick_ms <= 0:
            raise ValueError("performance.ui_tick_ms must be > 0")
        if self.performance.audio_queue_max_chunks <= 0:
            raise ValueError("performance.audio_queue_max_chunks must be > 0")
        if not 0.0 < self.ui.window_height_fraction <= 1.0:
            raise ValueError("ui.window_height_fraction must be > 0 and <= 1")
        if not 0.0 < self.ui.window_alpha <= 1.0:
            raise ValueError("ui.window_alpha must be > 0 and <= 1")
        if self.performance.clear_subtitles_after_seconds < 0:
            raise ValueError("performance.clear_subtitles_after_seconds must be >= 0")


def _to_bool(value: str, *, default: bool) -> bool:
    # Parses a human-friendly boolean value with a safe fallback.
    # --------------------------------------------------------------------------
    # @param value: Raw configuration value to interpret.
    # @param default: Value used when the input is not recognized.
    # @return: Parsed boolean or the supplied fallback.
    # --------------------------------------------------------------------------
    # normalize whitespace and case before comparing supported spellings.
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y", "on"}:
        return True
    if lowered in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _to_int(value: str, *, default: int) -> int:
    # Parses an integer configuration value without propagating invalid input.
    # --------------------------------------------------------------------------
    # @param value: Raw configuration value to parse.
    # @param default: Value used when parsing fails.
    # @return: Parsed integer or the supplied fallback.
    # --------------------------------------------------------------------------
    # preserve startup resilience when environment values are malformed.
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return default


def _to_float(value: str, *, default: float) -> float:
    # Parses a floating-point configuration value with a fallback.
    # --------------------------------------------------------------------------
    # @param value: Raw configuration value to parse.
    # @param default: Value used when parsing fails.
    # @return: Parsed float or the supplied fallback.
    # --------------------------------------------------------------------------
    # preserve startup resilience when environment values are malformed.
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return default


def read_dotenv(path: Path) -> dict[str, str]:
    # Reads a minimal dotenv file without overriding process environment values.
    # --------------------------------------------------------------------------
    # @param path: Candidate dotenv file path.
    # @return: Parsed key-value pairs, or an empty mapping when absent.
    # --------------------------------------------------------------------------
    # treat an absent dotenv file as an optional configuration source.
    if not path.exists():
        return {}

    out: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            out[key] = value
    return out


def application_root() -> Path:
    # Returns the directory containing bundled runtime assets.
    # --------------------------------------------------------------------------
    # Packaged one-file applications unpack bundled assets into their runtime
    # directory; normal source execution resolves assets from the project root.
    # @return: Runtime directory containing packaged or source assets.
    # --------------------------------------------------------------------------
    bundled_root = getattr(sys, "_MEIPASS", None)
    if bundled_root:
        return Path(bundled_root)
    return Path(__file__).resolve().parent.parent


def _load_config_file(path: Path) -> dict[str, Any]:
    # Loads JSON or TOML configuration data from a selected file.
    # --------------------------------------------------------------------------
    # @param path: Configuration file path.
    # @return: Parsed configuration mapping, or an empty mapping when absent.
    # @throws RuntimeError: If TOML support is unavailable.
    # @throws ValueError: If the file extension is unsupported.
    # --------------------------------------------------------------------------
    # treat a missing optional configuration file as empty configuration.
    if not path.exists():
        return {}

    if path.suffix.lower() == ".json":
        return json.loads(path.read_text(encoding="utf-8"))

    if path.suffix.lower() == ".toml":
        if tomllib is None:
            raise RuntimeError("TOML config requires Python 3.11+ or tomllib availability")
        return tomllib.loads(path.read_text(encoding="utf-8"))

    raise ValueError(f"Unsupported config file extension: {path.suffix}")


def _pick(m: Mapping[str, Any], key: str, default: Any) -> Any:
    # Selects a mapping value while treating explicit null as unspecified.
    # --------------------------------------------------------------------------
    # @param m: Source mapping.
    # @param key: Mapping key to read.
    # @param default: Value used when the key is absent or null.
    # @return: Mapping value or the supplied default.
    # --------------------------------------------------------------------------
    # preserve defaults when file configuration explicitly contains null.
    value = m.get(key, default)
    return default if value is None else value


def load_settings(
    *,
    source_language: str | None = None,
    target_language: str | None = None,
) -> Settings:
    # Loads, overlays, and validates all application settings.
    # --------------------------------------------------------------------------
    # Environment values override dotenv values, which override the optional config file.
    # Command-line language values override the config file when supplied.
    # @param source_language: Optional source-language override from the CLI.
    # @param target_language: Optional target-language override from the CLI.
    # @return: Fully validated immutable settings object.
    # @throws ValueError: If resulting settings fail validation.
    # --------------------------------------------------------------------------
    # resolve user-owned configuration from the process launch directory.
    root = Path.cwd()

    # merge dotenv defaults with process values so process configuration wins.
    dotenv_values = read_dotenv(root / ".env")
    env = {**dotenv_values, **os.environ}

    # load the selected file before resolving each typed configuration section.
    config_path = env.get("IRIS_CONFIG_FILE", "config.toml")
    config_file_data = _load_config_file(root / config_path)

    audio_cfg = dict(config_file_data.get("audio", {}))
    soniox_cfg = dict(config_file_data.get("soniox", {}))
    translation_cfg = dict(config_file_data.get("translation", {}))
    trigger_cfg = dict(config_file_data.get("trigger", {}))
    ui_cfg = dict(config_file_data.get("ui", {}))
    performance_cfg = dict(config_file_data.get("performance", {}))

    # construct the audio section from environment overrides and file defaults.
    audio = AudioConfig(
        sample_rate=_to_int(
            env.get("IRIS_AUDIO_SAMPLE_RATE", str(_pick(audio_cfg, "sample_rate", AudioConfig.sample_rate))),
            default=AudioConfig.sample_rate,
        ),
        channels=_to_int(
            env.get("IRIS_AUDIO_CHANNELS", str(_pick(audio_cfg, "channels", AudioConfig.channels))),
            default=AudioConfig.channels,
        ),
        audio_format=env.get("IRIS_AUDIO_FORMAT", str(_pick(audio_cfg, "audio_format", AudioConfig.audio_format))),
    )

    # construct the Soniox streaming section from non-language configuration.
    soniox = SonioxConfig(
        ws_url=env.get("IRIS_SONIOX_WS_URL", str(_pick(soniox_cfg, "ws_url", SonioxConfig.ws_url))),
        model=env.get("IRIS_SONIOX_MODEL", str(_pick(soniox_cfg, "model", SonioxConfig.model))),
        enable_endpoint_detection=_to_bool(
            env.get(
                "IRIS_SONIOX_ENABLE_ENDPOINT_DETECTION",
                str(_pick(soniox_cfg, "enable_endpoint_detection", SonioxConfig.enable_endpoint_detection)),
            ),
            default=SonioxConfig.enable_endpoint_detection,
        ),
        api_key=env.get("SONIOX_API_KEY", str(_pick(soniox_cfg, "api_key", SonioxConfig.api_key))).strip(),
    )

    # resolve CLI, environment, and config-file language values before validation.
    configured_source = env.get(
        "IRIS_SOURCE_LANGUAGE",
        str(_pick(translation_cfg, "source_language", "cs")),
    )
    configured_target = env.get(
        "IRIS_TARGET_LANGUAGE",
        str(_pick(translation_cfg, "target_language", "")),
    ).strip() or None
    resolved_source, resolved_target = resolve_translation_languages(
        source_language or configured_source,
        target_language if target_language is not None else configured_target,
    )

    # combine the resolved direction with the configurable token-finality policy.
    translation = TranslationConfig(
        source_language=resolved_source,
        target_language=resolved_target,
        display_only_final_translations=_to_bool(
            env.get(
                "IRIS_DISPLAY_ONLY_FINAL_TRANSLATIONS",
                str(
                    _pick(
                        translation_cfg,
                        "display_only_final_translations",
                        TranslationConfig.display_only_final_translations,
                    )
                ),
            ),
            default=TranslationConfig.display_only_final_translations,
        ),
    )

    # resolve termination phrases from an environment override or file sequence.
    termination_value = env.get("IRIS_TERMINATION_PHRASES")
    if termination_value is None:
        termination_value = _pick(
            trigger_cfg,
            "termination_phrases",
            TriggerConfig.termination_phrases,
        )
    if isinstance(termination_value, (list, tuple)):
        termination_values = termination_value
    else:
        termination_values = (str(termination_value),)

    # construct the trigger-state section from layered values.
    trigger = TriggerConfig(
        magic_phrase=env.get(
            "IRIS_MAGIC_PHRASE",
            str(_pick(trigger_cfg, "magic_phrase", TriggerConfig.magic_phrase)),
        ).strip(),
        magic_phrase_case_insensitive=_to_bool(
            env.get(
                "IRIS_MAGIC_PHRASE_CASE_INSENSITIVE",
                str(
                    _pick(
                        trigger_cfg,
                        "magic_phrase_case_insensitive",
                        TriggerConfig.magic_phrase_case_insensitive,
                    )
                ),
            ),
            default=TriggerConfig.magic_phrase_case_insensitive,
        ),
        audio_file=env.get(
            "IRIS_TRIGGER_AUDIO_FILE",
            str(_pick(trigger_cfg, "audio_file", TriggerConfig.audio_file)),
        ).strip(),
        message=env.get(
            "IRIS_TRIGGER_MESSAGE",
            str(_pick(trigger_cfg, "message", TriggerConfig.message)),
        ).strip(),
        termination_phrases=tuple(
            str(phrase).strip()
            for phrase in termination_values
            if str(phrase).strip()
        ),
        detection_buffer_chars=_to_int(
            env.get(
                "IRIS_MAGIC_DETECTION_BUFFER_CHARS",
                str(_pick(trigger_cfg, "detection_buffer_chars", TriggerConfig.detection_buffer_chars)),
            ),
            default=TriggerConfig.detection_buffer_chars,
        ),
        clear_buffers_on_trigger=_to_bool(
            env.get(
                "IRIS_CLEAR_BUFFERS_ON_TRIGGER",
                str(_pick(trigger_cfg, "clear_buffers_on_trigger", TriggerConfig.clear_buffers_on_trigger)),
            ),
            default=TriggerConfig.clear_buffers_on_trigger,
        ),
    )

    # construct the subtitle UI section from layered values.
    ui = UiConfig(
        max_lines_on_screen=_to_int(
            env.get("IRIS_MAX_LINES_ON_SCREEN", str(_pick(ui_cfg, "max_lines_on_screen", UiConfig.max_lines_on_screen))),
            default=UiConfig.max_lines_on_screen,
        ),
        max_line_chars_approx=_to_int(
            env.get(
                "IRIS_MAX_LINE_CHARS_APPROX",
                str(_pick(ui_cfg, "max_line_chars_approx", UiConfig.max_line_chars_approx)),
            ),
            default=UiConfig.max_line_chars_approx,
        ),
        window_resizable=_to_bool(
            env.get("IRIS_WINDOW_RESIZABLE", str(_pick(ui_cfg, "window_resizable", UiConfig.window_resizable))),
            default=UiConfig.window_resizable,
        ),
        window_zoomed=_to_bool(
            env.get("IRIS_WINDOW_ZOOMED", str(_pick(ui_cfg, "window_zoomed", UiConfig.window_zoomed))),
            default=UiConfig.window_zoomed,
        ),
        window_keep_on_top=_to_bool(
            env.get(
                "IRIS_WINDOW_KEEP_ON_TOP",
                str(_pick(ui_cfg, "window_keep_on_top", UiConfig.window_keep_on_top)),
            ),
            default=UiConfig.window_keep_on_top,
        ),
        window_borderless=_to_bool(
            env.get(
                "IRIS_WINDOW_BORDERLESS",
                str(_pick(ui_cfg, "window_borderless", UiConfig.window_borderless)),
            ),
            default=UiConfig.window_borderless,
        ),
        window_height_fraction=_to_float(
            env.get(
                "IRIS_WINDOW_HEIGHT_FRACTION",
                str(_pick(ui_cfg, "window_height_fraction", UiConfig.window_height_fraction)),
            ),
            default=UiConfig.window_height_fraction,
        ),
        window_alpha=_to_float(
            env.get(
                "IRIS_WINDOW_ALPHA",
                str(_pick(ui_cfg, "window_alpha", UiConfig.window_alpha)),
            ),
            default=UiConfig.window_alpha,
        ),
        window_background_color=env.get(
            "IRIS_WINDOW_BACKGROUND_COLOR",
            str(_pick(ui_cfg, "window_background_color", UiConfig.window_background_color)),
        ),
        window_text_color=env.get(
            "IRIS_WINDOW_TEXT_COLOR",
            str(_pick(ui_cfg, "window_text_color", UiConfig.window_text_color)),
        ),
        window_new_text_color=env.get(
            "IRIS_WINDOW_NEW_TEXT_COLOR",
            str(_pick(ui_cfg, "window_new_text_color", UiConfig.window_new_text_color)),
        ),
        window_font_family=env.get(
            "IRIS_WINDOW_FONT_FAMILY",
            str(_pick(ui_cfg, "window_font_family", UiConfig.window_font_family)),
        ),
        window_font_size=_to_int(
            env.get("IRIS_WINDOW_FONT_SIZE", str(_pick(ui_cfg, "window_font_size", UiConfig.window_font_size))),
            default=UiConfig.window_font_size,
        ),
        window_font_weight=env.get(
            "IRIS_WINDOW_FONT_WEIGHT",
            str(_pick(ui_cfg, "window_font_weight", UiConfig.window_font_weight)),
        ),
        window_text_padding_x=_to_int(
            env.get(
                "IRIS_WINDOW_TEXT_PADDING_X",
                str(_pick(ui_cfg, "window_text_padding_x", UiConfig.window_text_padding_x)),
            ),
            default=UiConfig.window_text_padding_x,
        ),
        window_text_padding_y=_to_int(
            env.get(
                "IRIS_WINDOW_TEXT_PADDING_Y",
                str(_pick(ui_cfg, "window_text_padding_y", UiConfig.window_text_padding_y)),
            ),
            default=UiConfig.window_text_padding_y,
        ),
        max_display_chars=_to_int(
            env.get("IRIS_MAX_DISPLAY_CHARS", str(_pick(ui_cfg, "max_display_chars", UiConfig.max_display_chars))),
            default=UiConfig.max_display_chars,
        ),
    )

    # construct the queueing and timing section from layered values.
    performance = PerformanceConfig(
        ui_tick_ms=_to_int(
            env.get("IRIS_UI_TICK_MS", str(_pick(performance_cfg, "ui_tick_ms", PerformanceConfig.ui_tick_ms))),
            default=PerformanceConfig.ui_tick_ms,
        ),
        audio_queue_max_chunks=_to_int(
            env.get(
                "IRIS_AUDIO_QUEUE_MAX_CHUNKS",
                str(_pick(performance_cfg, "audio_queue_max_chunks", PerformanceConfig.audio_queue_max_chunks)),
            ),
            default=PerformanceConfig.audio_queue_max_chunks,
        ),
        clear_subtitles_after_seconds=_to_float(
            env.get(
                "IRIS_CLEAR_SUBTITLES_AFTER_SECONDS",
                str(
                    _pick(
                        performance_cfg,
                        "clear_subtitles_after_seconds",
                        PerformanceConfig.clear_subtitles_after_seconds,
                    )
                ),
            ),
            default=PerformanceConfig.clear_subtitles_after_seconds,
        ),
    )

    # aggregate sections, then reject invalid combinations before returning them.
    settings = Settings(
        audio=audio,
        soniox=soniox,
        translation=translation,
        trigger=trigger,
        ui=ui,
        performance=performance,
    )
    settings.validate()
    return settings
