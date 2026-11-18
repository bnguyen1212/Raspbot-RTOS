# Sample images

Real photos from the robot's camera, used by `tests/test_sample_images.py` to
check the vision pipeline offline. Each labeled photo becomes one test case.

## Naming

```
<expected>_<details>.png        (also .jpg, .jpeg, .bmp)
```

- `<expected>`: the color that must win (`green`, `blue`, `red`), or `none`
  for a frame where the robot must stay idle.
- `<details>`: anything, separated by `_`. If it includes `left`, `center` or
  `right`, the card's position is checked too, using the same rule as
  GreenAction/BlueAction: `center` means within `config.CENTER_DEADBAND_PX` of
  `config.IMAGE_CENTER_X`, and `left`/`right` mean outside it on that side.

Examples: `green_center_near.png`, `blue_left_far.jpg`, `red_right_glare.png`,
`none_empty_hallway.png`.

Files that don't start with a color or `none`, and `tools/vision_debug.py`
output (`*_debug.png`), are ignored by the tests.

## Tips

- Capture at the robot's resolution (640x480). Other sizes are resized to it
  first, the same way `main.py --image` does.
- Include hard cases: glare on glossy cards, dim light, a card at the edge of
  the frame, two cards at once, and background objects with similar colors.
- Check a photo with `python tools/vision_debug.py tests/sample_images/<file>`.
