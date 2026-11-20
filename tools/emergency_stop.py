#!/usr/bin/env python3
"""Emergency stop for the RASPBOT V2: write speed 0 to motors 0-3, twice.

    python3 tools/emergency_stop.py

Run it on the robot when the wheels are still turning, for example after a
crash: the motor board keeps running the last command it received. It's
standalone on purpose. It imports only Raspbot_Lib and the standard library,
nothing from this repository, so it still works when the project code is
broken.

Raspbot_Lib swallows I2C errors: it prints a message such as
"write_array I2C error" and carries on. This script can't detect that, so it
can't confirm the wheels stopped. Watch the output for those messages, and
watch the robot.

NOT VERIFIED: this has not been run on the robot.
"""

from __future__ import annotations

import sys
import time

MOTOR_IDS = (0, 1, 2, 3)  # every motor ID in Raspbot_Lib's motor test
PASSES = 2
GAP_SECONDS = 0.005


def main() -> int:
    """Send the stop and report what was sent. Returns the exit code."""
    try:
        from Raspbot_Lib import Raspbot
    except ImportError as err:
        print(f"emergency_stop: cannot import Raspbot_Lib: {err}", file=sys.stderr)
        return 1

    bot = Raspbot()  # opens I2C bus 1, address 0x2B
    for attempt in range(1, PASSES + 1):
        for motor_id in MOTOR_IDS:
            bot.Ctrl_Muto(motor_id, 0)
            print(f"pass {attempt}: Ctrl_Muto({motor_id}, 0)")
        if attempt < PASSES:
            time.sleep(GAP_SECONDS)

    print(
        f"Sent speed 0 to motors {', '.join(map(str, MOTOR_IDS))}, {PASSES} times. "
        "Raspbot_Lib hides I2C errors: check above for 'I2C error' lines "
        "and check that the wheels have stopped."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
