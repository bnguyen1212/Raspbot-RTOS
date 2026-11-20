RASPBOT V2 RTOS SIMULATION
CE 6308 / CS 6396 / EEDG 6308 - Project 1
==========================================================================

TEAM MEMBERS
------------
  Arjun Junghare        - scheduling layer (scheduler/, main.py)
  Bao Nguyen            - motion layer (motion/)
  Zahaab Naseem Khawaja - vision layer (vision/)


OVERVIEW
--------
A round-robin cooperative task scheduler for the Yahboom RASPBOT V2
(Raspberry Pi, four mecanum wheels, USB camera). It is not real
multithreading: each task is a plain function that runs to completion and
returns before the next one gets a turn. All data passed between tasks
(frame, color counts, winning color, target position, red-turn state) is
passed as arguments and return values, never through global variables.

Program flow:

  1. StartupAction  - one-time motor setup, then a timed 360-degree spin.
  2. Round-robin loop, repeated until the safety timeout:
       TimerCheck     - stop the loop once TIMEOUT_SECONDS have passed.
       capture frame  - read one 640x480 frame from the camera.
       ColorCounter   - count the pixels of each tracked color (HSV masks).
       ColorLocator   - pick the dominant color and its centroid (x, y),
                        or report "nothing detected".
       dispatch       - run the action for that color:
         green   GreenAction: rotate in place toward the target, stop
                 once it is centered.
         blue    BlueAction: strafe sideways toward the target, stop once
                 it is centered.
         red     RedAction: a timed 180-degree turn. It is non-blocking
                 (advanced one step per loop pass), and red must leave the
                 view before it can trigger another turn.
         none    IdleAction: stop the wheels.
  3. ShutdownAction - stop all wheels and release the camera, however the
     run ends (timeout, error, Ctrl-C, kill, or the SSH session closing).

A color only counts as detected when it has at least MIN_PIXEL_THRESHOLD
pixels. When two colors tie, the order green, blue, red breaks the tie.


FILES
-----
  main.py        Entry point. Parses the command line, chooses the real or
                 dry-run motion actions and the frame source, and starts
                 the loop.
  config.py      Every shared constant: HSV color ranges, pixel threshold,
                 image size, centering deadband, timeout, wheel speeds and
                 turn timings. No other file hardcodes these values.
  scheduler/
    loop.py      run_loop (the control flow above), TimerCheck and a
                 generic round_robin helper. Every task is passed in, so it
                 imports nothing from vision/ or motion/.
    camera.py    Frame sources: Camera (live camera) and StaticImage
                 (one image file used as every frame).
    dry_run.py   Stand-in actions that print instead of driving motors.
    signals.py   SIGINT/SIGTERM/SIGHUP handlers that stop the motors and
                 exit.
  vision/
    hsv_mask.py      HSV conversion, color masks with noise removal, and
                     the centroid helper.
    color_counter.py ColorCounter: pixel count per tracked color.
    color_locator.py ColorLocator: dominant color and its position.
  motion/
    actions.py     Startup, Idle, Green, Blue, Red and Shutdown actions.
                   This is the only motion module main.py calls.
    kinematics.py  Mecanum wheel speeds for rotating and strafing.
    centering.py   Left / right / centered decision from the target's x.
    driver.py      MotorDriver interface and the default (real) driver.
    mecanum.py     The real driver. The only file that imports the Yahboom
                   Raspbot_Lib motor library.


REQUIREMENTS
------------
  - Python 3.9 or newer
  - opencv-python
  - numpy
  - On the robot only: Yahboom's Raspbot_Lib (the RASPBOT V2 motor
    library). It is not on PyPI. Install it on the Pi with Yahboom's setup
    instructions. A dry run never imports it.

  Install the Python packages with:
      pip install opencv-python numpy


HOW TO RUN
----------
Run every command from the folder that contains main.py.

  On the robot (drives the motors):
      python3 main.py

  Without the robot (prints the actions instead of driving motors; uses
  the computer's webcam):
      python main.py --dry-run

  Dry run on a still image instead of a live camera:
      python main.py --dry-run --image path/to/picture.png

  Options:
      --dry-run          Print each action instead of driving the motors.
                         motion/ and the motor library are never loaded,
                         so this works on any computer.
      --image PATH       Use this image as every frame.
      --camera INDEX     Camera device index (default: CAMERA_INDEX in
                         config.py, 0).
      --timeout SECONDS  Safety cutoff in seconds (default: TIMEOUT_SECONDS
                         in config.py, 30). Must be greater than 0.

A normal run ends at the timeout and prints
"Timeout reached: motors stopped, camera released."


STOPPING AND SAFETY
-------------------
  - The motors stop and the camera is released however the run ends: the
    timeout, an error, Ctrl-C (exit code 130), kill / SIGTERM (exit code
    143), or the SSH session closing (SIGHUP, exit code 129).
  - The signal handlers stop the motors directly, so the motor library
    cannot swallow the interrupt.
  - kill -9 cannot be caught. The motor board keeps running its last
    command, so switch the robot off if the process is killed that way.
  - Every wheel speed is clamped to MAX_SPEED (config.py) before it is
    sent to the motor board.


CONFIGURATION AND CALIBRATION
-----------------------------
All tuning lives in config.py:
  COMMAND_COLORS       HSV ranges for green, blue and red (OpenCV scale:
                       H 0-179, S 0-255, V 0-255; red uses two ranges
                       because its hue wraps around 0).
  MIN_PIXEL_THRESHOLD  Pixels a color needs to count as detected.
  CENTER_DEADBAND_PX   How far (in pixels) from the image center a target
                       may be and still count as centered.
  TIMEOUT_SECONDS      Safety cutoff for the loop.
  MAX_SPEED, ROTATE_SPEED, STRAFE_SPEED
                       Wheel speeds, normalized to -1.0 .. 1.0.
  SECONDS_PER_360, SECONDS_PER_180
                       Open-loop turn timings. The robot has no gyro, so
                       turns are timed: recalibrate on the actual floor
                       whenever ROTATE_SPEED changes.
  CAMERA_INDEX, CAMERA_BUFFER_SIZE, CAMERA_FLUSH_FRAMES
                       Camera device, driver queue length, and frames thrown
                       away after the startup spin so the loop starts on a
                       fresh frame.
