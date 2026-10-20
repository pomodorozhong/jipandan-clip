# Handoff

## Ranked work

Step 3 candidate generation (milestone), in dependency order:

1. #49 Decide how to evaluate generated candidates (needs-decision: owner answers only; unblocks the rest of step 3)
2. #47 Generate candidates from voice activity and word timings (blocked by #49; can use the snap points stored by #58; Silero VAD recommended in its comments)
3. #50 Create new sessions from generated candidates (blocked by #47)

App fixes left from step 2 (no milestone; independent of step 3, so they can run while #49 waits on the owner):

4. #70 Publish preview loses its trim overlay (a bug on `main`, gets its own `fix/` branch)
