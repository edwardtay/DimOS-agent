"""CLI: python -m dimos_proto.main "find alice and say hi"."""
from __future__ import annotations

import sys

from .agent import run
from .go2_sim import Go2Sim


def main() -> int:
    if len(sys.argv) < 2:
        print('usage: python -m dimos_proto.main "<natural language goal>"')
        return 1
    goal = " ".join(sys.argv[1:])
    robot = Go2Sim()
    for line in run(goal, robot):
        print(line, flush=True)
    print("\n--- robot log ---")
    for entry in robot.log:
        print(entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
