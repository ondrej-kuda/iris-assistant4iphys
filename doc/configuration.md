# Configuration Reference

This document lists all active configuration options loaded by the app from [src/config.py](../src/config.py).

Translation language defaults are stored in `config.toml` and can be overridden
by command-line arguments or the runtime menus. The translator accepts optional
`--source-lang` and `--target-lang` arguments.
`cz` is accepted as an alias and normalized to `cs`.

## Load Order

Configuration precedence (last wins):

1. Built-in defaults in code
2. Config file (`config.toml` by default, or `IRIS_CONFIG_FILE`)
3. `.env`
4. Process environment variables

## Required Setting

- `SONIOX_API_KEY` (no default): Soniox API key used for authentication.

## Config File Path

- `IRIS_CONFIG_FILE` (default: `config.toml`): relative path from the process launch directory to the config file.

The `.env` file is also read from the process launch directory. These files are
not read from the packaged application's temporary extraction directory.

## Audio Options

- `audio.sample_rate` (env: `IRIS_AUDIO_SAMPLE_RATE`, default: `16000`)
: Microphone sample rate in Hz.

- `audio.channels` (env: `IRIS_AUDIO_CHANNELS`, default: `1`)
: Number of microphone channels.

- `audio.audio_format` (env: `IRIS_AUDIO_FORMAT`, default: `pcm_s16le`)
: Audio frame format sent to Soniox. The current microphone implementation supports only `pcm_s16le`.

## Soniox Options

- `soniox.ws_url` (env: `IRIS_SONIOX_WS_URL`, default: `wss://stt-rt.soniox.com/transcribe-websocket`)
: Soniox realtime websocket endpoint.

- `soniox.model` (env: `IRIS_SONIOX_MODEL`, default: `stt-rt-preview`)
: Soniox realtime model name.

- `soniox.enable_endpoint_detection` (env: `IRIS_SONIOX_ENABLE_ENDPOINT_DETECTION`, default: `true`)
: Enables endpoint detection to help finalize utterances.

- `soniox.api_key` (env: `SONIOX_API_KEY`, default: empty)
: API key used by Soniox client auth.

## Translation Options

- `translation.source_language` (env: `IRIS_SOURCE_LANGUAGE`, default: `cs`)
: Spoken input language. The runtime language menu can change this without restarting the application.

- `translation.target_language` (env: `IRIS_TARGET_LANGUAGE`, default: `en`)
: Subtitle output language. The runtime language menu can change this without restarting the application.

- `translation.display_only_final_translations` (env: `IRIS_DISPLAY_ONLY_FINAL_TRANSLATIONS`, default: `true`)
: If enabled, only final translation tokens are shown.

## Trigger Options

- `trigger.magic_phrase` (env: `IRIS_MAGIC_PHRASE`, default: `Iris?`)
: Spoken phrase that triggers the configured greeting response.

- `trigger.magic_phrase_case_insensitive` (env: `IRIS_MAGIC_PHRASE_CASE_INSENSITIVE`, default: `true`)
: Whether magic-phrase matching ignores case and punctuation.

- `trigger.detection_buffer_chars` (env: `IRIS_MAGIC_DETECTION_BUFFER_CHARS`, default: `600`)
: Rolling text buffer size used for trigger detection logic.

- `trigger.clear_buffers_on_trigger` (env: `IRIS_CLEAR_BUFFERS_ON_TRIGGER`, default: `true`)
: Clears subtitle buffers when trigger behavior fires.

- `trigger.audio_file` (env: `IRIS_TRIGGER_AUDIO_FILE`, default: `assets/iris.mp3`)
: Greeting audio asset played after the magic phrase.

- `trigger.message` (env: `IRIS_TRIGGER_MESSAGE`, default: `At your service, Mr. Director`)
: Subtitle message shown after the magic phrase.

- `trigger.termination_phrases` (env: `IRIS_TERMINATION_PHRASES`, default: `Iris, end the presentation`)
: Original-speech phrases that stop the worker and close the subtitle window.

## UI Options

- `ui.max_lines_on_screen` (env: `IRIS_MAX_LINES_ON_SCREEN`, default: `2`)
: Maximum number of wrapped subtitle lines kept on screen.

- `ui.max_line_chars_approx` (env: `IRIS_MAX_LINE_CHARS_APPROX`, default: `42`)
: Approximate wrap width in characters.

- `ui.window_resizable` (env: `IRIS_WINDOW_RESIZABLE`, default: `true`)
: Allows manual window resize.

- `ui.window_zoomed` (env: `IRIS_WINDOW_ZOOMED`, default: `false`)
: Starts a non-borderless window in zoomed/maximized state when supported.

- `ui.window_keep_on_top` (env: `IRIS_WINDOW_KEEP_ON_TOP`, default: `true`)
: Keeps subtitle window above other windows.

- `ui.window_background_color` (env: `IRIS_WINDOW_BACKGROUND_COLOR`, default: `black`)
: Window background color.

- `ui.window_text_color` (env: `IRIS_WINDOW_TEXT_COLOR`, default: `white`)
: Subtitle text color.

- `ui.window_new_text_color` (env: `IRIS_WINDOW_NEW_TEXT_COLOR`, default: `yellow`)
: Color of the newest subtitle line; it can also be changed interactively in the window.

- `ui.window_borderless` (env: `IRIS_WINDOW_BORDERLESS`, default: `true`)
: Removes the native title bar and displays the subtitle stripe.

- `ui.window_height_fraction` (env: `IRIS_WINDOW_HEIGHT_FRACTION`, default: `0.20`)
: Fraction of screen height used by the borderless subtitle stripe.

- `ui.window_alpha` (env: `IRIS_WINDOW_ALPHA`, default: `0.50`)
: Whole-window opacity from 0.0 through 1.0.

- `ui.window_font_family` (env: `IRIS_WINDOW_FONT_FAMILY`, default: `Segoe UI`)
: Subtitle font family.

- `ui.window_font_size` (env: `IRIS_WINDOW_FONT_SIZE`, default: `36`)
: Subtitle font size.

- `ui.window_font_weight` (env: `IRIS_WINDOW_FONT_WEIGHT`, default: `bold`)
: Subtitle font weight.

- `ui.window_text_padding_x` (env: `IRIS_WINDOW_TEXT_PADDING_X`, default: `70`)
: Horizontal text padding.

- `ui.window_text_padding_y` (env: `IRIS_WINDOW_TEXT_PADDING_Y`, default: `8`)
: Vertical text padding.

- `ui.max_display_chars` (env: `IRIS_MAX_DISPLAY_CHARS`, default: `1200`)
: Max subtitle buffer characters kept before clipping.

## Performance Options

- `performance.ui_tick_ms` (env: `IRIS_UI_TICK_MS`, default: `60`)
: UI refresh interval in milliseconds.

- `performance.audio_queue_max_chunks` (env: `IRIS_AUDIO_QUEUE_MAX_CHUNKS`, default: `300`)
: Max queued microphone audio chunks.

- `performance.clear_subtitles_after_seconds` (env: `IRIS_CLEAR_SUBTITLES_AFTER_SECONDS`, default: `5.0`)
: Clears subtitle lines after this many seconds without a new translation; `0` disables automatic clearing.

## Boolean Value Formats

For env vars parsed as booleans, accepted true values are:

- `1`, `true`, `yes`, `y`, `on`

Accepted false values are:

- `0`, `false`, `no`, `n`, `off`

Any other value falls back to that option's default.

