# IME event probe record

This record defines the initial browser/IME profile for the browser review shortcuts. It is intentionally narrower than a promise to support every operating-system input method.

## Initial profile

| Platform | Browser | IME/layout | Result |
| --- | --- | --- | --- |
| macOS 26.6.2 | Google Chrome 153.0.8010.53 | Apple Traditional Chinese Zhuyin (Bopomofo) | Existing event trace informs the composition guard; a live interaction was not repeated in this PR. |
| macOS 26.6.2 | Codex in-app Chromium browser | ABC keyboard layout | The local app loaded successfully; code routing is covered by synthetic regression tests, with no IME composition exercised. |

The Bopomofo event trace used by the regression fixture was captured in the title rename field. Its relevant sequence was:

1. An IME-owned `keydown` arrived with `keyCode === 229` and `isComposing === true`.
2. Composition updates and `beforeinput` ran, followed by a non-empty `compositionend`.
3. After `keyup`, Chrome replayed a new `keydown` object for the same IME boundary with `isComposing === false`, `keyCode === 27`, and the original event timestamp.

The composition tracker retains ownership for both event objects when the target, key, code, and timestamp match. That prevents candidate cancellation from bubbling into editor blur or dialog close. A later Escape press with a different event timestamp is treated as the user's ordinary text-editing Escape.

## Dispatch rule

Outside editable controls, review and export shortcuts use `KeyboardEvent.code` (`KeyJ`, `KeyK`, `Digit1`, `KeyE`, and so on). This keeps the physical key position stable when an IME changes `event.key` to a locale-specific character or `Process`. Inside editable controls, composition and native text editing take priority; Enter and Escape are only handled after composition has ended.

The code-level tests model the locale-transformed `key` values because synthetic browser events cannot prove an OS IME integration. The current probe session did not switch the active system input source, so a live Bopomofo interaction should still be repeated by a reviewer before broadening the support matrix. Unknown browsers or IMEs that do not provide a usable physical `code` remain outside the supported profile.
