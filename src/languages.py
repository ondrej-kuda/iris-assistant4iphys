# Provides shared language-code normalization and translation-direction defaults.

from __future__ import annotations

import threading


# Language aliases that Soniox should receive as the ISO 639-1 Czech code.
# @var frozenset[str]
CZECH_LANGUAGE_CODES = frozenset({"cs", "cz"})

# Languages exposed by the runtime subtitle direction controls.
# @var tuple[str, ...]
SUPPORTED_TRANSLATION_LANGUAGES = ("cs", "en", "de", "es", "pt", "pl", "fr", "sk")


class TranslationDirection:
    # Stores the active source and target languages shared by Tk and Soniox.
    # --------------------------------------------------------------------------
    # The lock protects direction updates while the worker snapshots a complete
    # pair before opening a new streaming session.
    # --------------------------------------------------------------------------

    def __init__(self, source_language: str, target_language: str) -> None:
        # Initializes a thread-safe runtime language selection.
        # ----------------------------------------------------------------------
        # @param source_language: Initial spoken-language code.
        # @param target_language: Initial translated-language code.
        # @return: None.
        # ----------------------------------------------------------------------
        self._lock = threading.Lock()
        self._source_language = normalize_language_code(source_language)
        self._target_language = normalize_language_code(target_language)
        self._version = 0
    #end def

    def set(self, source_language: str, target_language: str) -> None:
        # Updates the direction and marks a new Soniox session as necessary.
        # ----------------------------------------------------------------------
        # @param source_language: New spoken-language code.
        # @param target_language: New translated-language code.
        # @return: None.
        # @throws ValueError: If either language code is empty.
        # ----------------------------------------------------------------------
        source = normalize_language_code(source_language)
        target = normalize_language_code(target_language)
        with self._lock:
            if (source, target) != (self._source_language, self._target_language):
                self._source_language = source
                self._target_language = target
                self._version += 1
    #end def

    def snapshot(self) -> tuple[str, str, int]:
        # Returns one consistent direction snapshot for a streaming session.
        # ----------------------------------------------------------------------
        # @return: Source language, target language, and change version.
        # ----------------------------------------------------------------------
        with self._lock:
            return self._source_language, self._target_language, self._version
    #end def
#end class


def normalize_language_code(value: str) -> str:
    # Normalizes a command-line language code for Soniox requests.
    # --------------------------------------------------------------------------
    # @param value: User-supplied language code.
    # @return: Lower-case language code, with Czech aliases normalized to `cs`.
    # @throws ValueError: If the supplied value is empty.
    # --------------------------------------------------------------------------
    # reject empty arguments before constructing a remote session configuration.
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError("language code cannot be empty")

    # use Soniox's canonical Czech language code for either common spelling.
    if normalized in CZECH_LANGUAGE_CODES:
        return "cs"
    return normalized
#end def


def resolve_translation_languages(
    source_language: str,
    target_language: str | None,
) -> tuple[str, str]:
    # Resolves a normalized source and explicit or inferred target language pair.
    # --------------------------------------------------------------------------
    # Czech speech defaults to English; every other source defaults to Czech.
    # @param source_language: Required source language supplied by the user.
    # @param target_language: Optional target language supplied by the user.
    # @return: Normalized `(source_language, target_language)` pair.
    # @throws ValueError: If either supplied language code is empty.
    # --------------------------------------------------------------------------
    # normalize the source before selecting its complementary default target.
    source = normalize_language_code(source_language)
    if target_language is None:
        return source, "en" if source == "cs" else "cs"

    # preserve an explicit direction while applying the same alias normalization.
    return source, normalize_language_code(target_language)
#end def
