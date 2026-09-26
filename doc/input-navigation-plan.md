# Browser input navigation plan

Status: implementation in progress. Issues #7 and #8 are complete; the gamepad controls and controller mapping remain proposals until validated.

## Outcome and scope

Make the browser review workflow usable with an Asian IME selected and with a gamepad. The target session is: navigate → replay → classify → trim → rename with IME → export. Text entry continues to use the keyboard and IME.

Scope is the React browser GUI, including a follow-up screen for configuring standard-mapped gamepad controls. TUI/browser-terminal controls, OS-level input-method switching, virtual keyboards, support for nonstandard controller layouts, and application storage changes are separate work. The storage follow-up is [#5](https://github.com/pomodorozhong/jipandan-clip/issues/5).

## Starting point

The shared action and input policy introduced by #7 lives in [inputActions.ts](../frontend/src/inputActions.ts), with interaction tests in [inputActions.test.ts](../frontend/src/inputActions.test.ts). [App.tsx](../frontend/src/App.tsx), [WaveformEditor.tsx](../frontend/src/WaveformEditor.tsx), and [ExportPreview.tsx](../frontend/src/ExportPreview.tsx) use that policy. Issue #8 added IME-friendly keyboard navigation; gamepad support remains to be implemented.

## Shared action design

Introduce a small shared action layer for operations such as next/previous clip, replay, classification, boundary nudging, undo, and opening export preview. Keyboard and gamepad adapters translate input into these actions; existing buttons invoke the same operations directly. Do not synthesize keyboard events to implement controller input.

Keep action availability and repeat behavior in one place. Navigation and nudges may repeat under a controlled policy; export, duplicate, and other one-shot actions must not repeat simply because a control is held. Reuse existing persistence and audio behavior.

Resolve input against the active context:

| Context | Input behavior |
| --- | --- |
| Review | Navigate, replay, classify, and trim the selected clip. |
| Active dialog | Route only to that dialog; background review shortcuts are inactive. |
| Text editing/composition | Preserve text entry and candidate selection; suppress unrelated review actions. |
| Busy/saving | Disable conflicting actions consistently across pointer, keyboard, and controller. |

Busy state can overlay other contexts. Preserve native keyboard activation and browser modifier shortcuts. Focus changes, dialog transitions, and controller reconnection must not reinterpret an existing held press as a new action.

## IME-friendly navigation

Before changing dispatch rules, perform a small event probe with the owner's actual browser and IME. Record `key`, `code`, composition state, focused target, and composition start/end behavior. Identify the initial supported OS/browser/IME combinations from this evidence.

Outside editable controls, prefer physical bindings such as `KeyJ` and `KeyK` so navigation can work while an IME is selected. Explain physical-key positions in shortcut help, including the consequence for non-QWERTY layouts. This is application shortcut handling, not a guarantee that a webpage can bypass every OS/IME combination.

Inside title, search, and other editable controls, preserve normal composition. Enter confirming an IME candidate must not also save or export. Escape dismissing candidates must not also close an editor or dialog. Check composition boundary events, not just the middle of a composition session; do not remove guards globally to make navigation work. Define the outside-editor dispatch rule from the probe results.

Validate leaving and re-entering editing, rapid candidate confirmation, cancellation, dialog close, and export-title shortcuts. Synthetic events provide regression coverage but cannot replace real IME testing.

## Gamepad behavior

Start with the browser Gamepad API and controllers reporting a standard mapping. Show connection/activation guidance and an unsupported-mapping state instead of guessing bindings for unknown layouts. Select one active controller deterministically for the initial version.

Poll only while the page is active. Detect press/release transitions and implement a deliberate initial delay and repeat rate for repeatable controls. If analog axes are enabled, use dead zones and hysteresis. Clear held/repeat state on blur, visibility changes, disconnect, and context changes; require release before recognizing a new action after those transitions.

The following mapping is a proposal to validate with an actual controller, not a fixed specification:

| Control | Review action |
| --- | --- |
| D-pad up/down | Previous/next clip |
| Primary face button | Replay |
| Other face buttons | Group 1, Group 2, skip |
| Shoulder buttons | Select start/end boundary |
| D-pad left/right | Nudge selected boundary |
| Modifier, to be selected | Switch fine/coarse nudge step |
| Menu button | Open export preview |

Use contextual hints and visible boundary/step feedback. Controller brand labels and confirm/back conventions must be checked against the actual device. In dialogs, directional controls move visible focus, confirm activates an enabled control, and back leaves the current context. Define how to return from keyboard/IME text entry to controller navigation without cancelling composition.

Export must require a fresh confirmation press after opening its dialog. Rendering, publication, disabled controls, and failures must all obey the same action availability rules. Closing a dialog restores appropriate focus.

## Gamepad mapping settings

After the core review controls in #9, add a **Gamepad mapping** screen opened from the existing Settings screen. Make the available review actions configurable early so the controller can be adjusted for comfort during real-device testing. Show the active controller and the current bindings for each implemented action. Let the user capture a control for an action, detect conflicting assignments, reset to the validated defaults, and save or cancel changes. Add trimming bindings with #10 and dialog/export bindings with #11 as those actions become available. Store preferences in this browser alongside the existing UI settings; application-level storage belongs to the separate storage follow-up only if a later requirement calls for it.

The gamepad adapter must use the configured bindings without changing action availability, repeat rules, or dialog priority. Keep the standard-mapping requirement and unsupported-mapping guidance until nonstandard layouts are designed and validated separately. Prevent a control press used to open the screen or capture a binding from triggering a review action. Restore appropriate focus when leaving the mapping screen.

## Implementation issues and proposed PRs

Each issue is intended to become one focused implementation PR. Update the split if implementation evidence warrants it; keep this table current rather than opening empty draft PRs.

| Order | Issue | Dependency | Acceptance / review point | Implementation PR |
| --- | --- | --- | --- | --- |
| 1 | [#7 Shared actions and contexts](https://github.com/pomodorozhong/jipandan-clip/issues/7) | None | Existing browser behavior preserved; dialog priority, editing guards, and repeat rules covered. | [#13](https://github.com/pomodorozhong/jipandan-clip/pull/13) (merged) |
| 2 | [#8 IME-friendly navigation](https://github.com/pomodorozhong/jipandan-clip/issues/8) | #7 | Owner's agreed IME/browser combinations navigate without switching language; candidate confirmation/cancellation does not trigger unrelated actions. | [#14](https://github.com/pomodorozhong/jipandan-clip/pull/14) (merged) |
| 3 | [#9 Gamepad foundation and review](https://github.com/pomodorozhong/jipandan-clip/issues/9) | #7 | Browse, replay, and classify on a real controller; disconnect/focus/context transitions cannot produce stale actions. | Not opened |
| 4 | [#15 Gamepad mapping settings](https://github.com/pomodorozhong/jipandan-clip/issues/15) | #9 | Open from Settings; inspect, change, save, and reset bindings for available review actions. Conflicts and held/captured presses are handled safely. | Not opened |
| 5 | [#10 Gamepad trimming](https://github.com/pomodorozhong/jipandan-clip/issues/10) | #9, #15 | Accurate start/end edits with visible step/boundary; add trim actions to mapping settings; held input cannot leak into another clip or conflict with saves. | Not opened |
| 6 | [#11 Gamepad dialogs and export](https://github.com/pomodorozhong/jipandan-clip/issues/11) | #9, #15 | Reach enabled dialog controls, compare previews, export once per fresh press, and restore focus; add dialog/export actions to mapping settings. | Not opened |

Recommended landing order: **#7 → #8 → #9 → #15 → #10/#11**. Issues #8 and #9 can proceed independently after #7; #10 and #11 can proceed independently after #15. Mapping review actions before trimming and export lets the owner tune controls while testing those later features. Full workflow acceptance waits for all six issues. The initial IME probe is investigation within this work, not an additional PR.

Implementation PRs should close their respective issues only when their acceptance criteria are met. The planning PR references the issues without closing them. Repository cleanup is a separate PR: [#6](https://github.com/pomodorozhong/jipandan-clip/pull/6).

## Validation

- Run the existing frontend type and production build checks for implementation changes: `npm --prefix frontend run check` and `npm --prefix frontend run build`.
- Extend the frontend interaction tests introduced by #7 with meaningful regression cases for controller transitions, mapping changes, dialog focus, and slow saves/publication as those features land.
- Exercise real IME candidate entry/confirmation/cancellation on the agreed browser combinations. Record versions, observations, and limitations in the implementing PR.
- Exercise the actual controller, including held buttons, unplug/reconnect, background/foreground changes, and unsupported mappings. Record device, transport, and browser.
- For mapping settings, verify capture and conflict handling, reset, persistence across reload, dialog focus, and that changed bindings still obey hold-repeat and action-availability rules.
- Validate the final session on disposable data: navigate, replay, classify, trim, rename with IME, export, reload, and compare saved bounds/output with what was reviewed.

## Decisions to settle during implementation

- Initial OS/browser/IME coverage, based on the owner's setup and the event probe.
- Initial controller and browser coverage; physical button labels and confirm/back conventions.
- Fine/coarse trim modifier, repeat delay/rate, and whether analog navigation is useful in the initial release.
- Which actions may share a control in separate contexts, and how the mapping screen explains or resolves conflicts.
- Physical-key shortcut behavior across keyboard layouts and whether an explicit preference is needed.
- Focus order and text-entry handoff for each dialog in the review/export workflow.

These decisions do not block the shared action refactor. Resolve each before locking in the corresponding user-facing behavior.

## Technical references

- [KeyboardEvent.code](https://developer.mozilla.org/en-US/docs/Web/API/KeyboardEvent/code): physical-key bindings.
- [keydown and IME composition caveats](https://developer.mozilla.org/en-US/docs/Web/API/Element/keydown_event): composition boundaries need special handling.
- [Using the Gamepad API](https://developer.mozilla.org/en-US/docs/Web/API/Gamepad_API/Using_the_Gamepad_API): device discovery, polling, and standard mapping.
