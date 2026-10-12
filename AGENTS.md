# Agent guide

Jipandan turns long gaming-stream recordings into short soundboard MP3 clips. See the [README](README.md) for setup, commands, and tests.

## Start of a session

1. Read [.agents/progress.md](.agents/progress.md) for the current state and recent sessions.
2. Read [.agents/plan.md](.agents/plan.md) and work from its first item. If it starts with **Clarify it**, ask those questions before anything else.

## Where things live

- `.agents/`: session-to-session progress and the working plan.
- `doc/`: long-term knowledge: plans, decisions, and reviews ([index](doc/README.md)).

## End of a session

Run the `wrap-up` skill to save progress, update the plan, move lasting knowledge into `doc/`, and commit. Use the `commit` skill for any other commit.
