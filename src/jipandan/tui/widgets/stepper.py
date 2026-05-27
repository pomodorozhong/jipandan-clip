"""Numeric input that nudges its value with arrow keys.

Subclasses can tune two knobs:

* :py:attr:`MIN_STEP` -- the small step applied to ``up`` / ``down``.
* :py:attr:`MAGNIFICATION` -- how many ``MIN_STEP`` units ``right`` / ``left``
  jump by (so the coarse step is ``MIN_STEP * MAGNIFICATION``).

Override :py:meth:`_parse`, :py:meth:`_clamp`, or :py:meth:`_format` to
customise parsing, range clamping, or output formatting.
"""

from textual.binding import Binding
from textual.widgets import Input


class SteppedNumberInput(Input):
    """Input that adjusts its numeric value via arrow keys."""

    MIN_STEP: float = 1.0
    MAGNIFICATION: float = 10.0

    BINDINGS = [
        Binding("up", "step(1)", show=False),
        Binding("down", "step(-1)", show=False),
        Binding("right", "step_large(1)", show=False),
        Binding("left", "step_large(-1)", show=False),
    ]

    def action_step(self, direction: int) -> None:
        self._apply_step(direction * self.MIN_STEP)

    def action_step_large(self, direction: int) -> None:
        self._apply_step(direction * self.MIN_STEP * self.MAGNIFICATION)

    def _apply_step(self, delta: float) -> None:
        try:
            current = self._parse(self.value)
        except ValueError:
            return
        self.value = self._format(self._clamp(current + delta))

    def _parse(self, raw: str) -> float:
        return float(raw.strip())

    def _clamp(self, value: float) -> float:
        return value

    def _format(self, value: float) -> str:
        if value.is_integer():
            return str(int(value))
        return f"{value:g}"
