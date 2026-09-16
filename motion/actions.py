"""Task-level robot actions dispatched from main.py's round-robin loop.

All hardware access is routed through motion.mecanum -- this module and
mecanum.py together are the only place the real robot is needed to test.
"""

from motion import mecanum


def StartupAction():
    """One-time initialization run before the round-robin loop starts.

    Sets up whatever the robot/motor library needs before any per-cycle
    action can run (e.g. I2C bus init, camera warm-up, homing wheels).

    Args:
        None

    Returns:
        None
    """
    raise NotImplementedError


def IdleAction():
    """Action taken when no tracked color is detected in the current frame.

    Args:
        None

    Returns:
        None
    """
    raise NotImplementedError


def GreenAction(p_vector):
    """Respond to the green target: rotate in place toward it.

    Args:
        p_vector: tuple[float, float], the (x, y) position vector returned by
            vision.color_locator.ColorLocator for the current frame.

    Returns:
        None
    """
    raise NotImplementedError


def BlueAction(p_vector):
    """Respond to the blue target: strafe sideways toward it.

    Args:
        p_vector: tuple[float, float], the (x, y) position vector returned by
            vision.color_locator.ColorLocator for the current frame.

    Returns:
        None
    """
    raise NotImplementedError


def RedAction(p_vector):
    """Respond to the red target: rotate in place toward it.

    Args:
        p_vector: tuple[float, float], the (x, y) position vector returned by
            vision.color_locator.ColorLocator for the current frame.

    Returns:
        None
    """
    raise NotImplementedError
