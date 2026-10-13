# Agent guide

Jipandan turns long gaming-stream recordings into short soundboard MP3 clips. See the [README](README.md) for setup, commands, and tests.

## Start of a session

1. Read [.agents/progress.md](.agents/progress.md) for the current state and recent sessions.
2. Resolve any items parked in `.agents/pending.md` (see the `wrap-up` skill), then read [.agents/next-steps.md](.agents/next-steps.md), check the top issue is still open (`gh issue view`), and propose it.

## Where things live

- `.agents/`: session-to-session progress and the ranked next steps; work items live in GitHub issues.
- `doc/`: long-term knowledge: plans, decisions, and reviews ([index](doc/README.md)).

## End of a session

Run the `wrap-up` skill to save progress, update the plan, move lasting knowledge into `doc/`, and commit. Use the `commit` skill for any other commit.
