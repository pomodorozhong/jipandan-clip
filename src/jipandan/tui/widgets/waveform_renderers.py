"""Waveform image backends for terminal emulators and textual-serve-asgi."""

from __future__ import annotations

from typing import Type

from textual_image.widget import Image as TerminalWaveformImage, SixelImage, SixelOptions
from textual_image.widget._base import Image as BaseWaveformImage

# Sixel for textual-serve-asgi's xterm.js (Kitty/iTerm/Sixel image support).
# textual-image auto-selects UnicodeImage when stdout is not a TTY, which
# renders grayscale block characters that look broken in the browser.
_BROWSER_SIXEL_OPTIONS = SixelOptions(colors=256, quantize="maxcoverage")


def browser_waveform_image(**kwargs) -> SixelImage:
    kwargs.setdefault("sixel_options", _BROWSER_SIXEL_OPTIONS)
    return SixelImage(**kwargs)


def waveform_image_class(*, is_web: bool) -> Type[BaseWaveformImage]:
    if is_web:
        return browser_waveform_image  # type: ignore[return-value]
    return TerminalWaveformImage
