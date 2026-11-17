---
title: Menu slots
description: Seven toggles and seven radials in your avatar's menu, handed out to controls on your board.
---

# Menu slots

The [avatar menu](../avatar/menu.md) has **OscGoesPurrr ▸ Avatar Remote**:
seven **Toggles** and seven **Radials**. Each is a *slot* you give a control,
or a whole category, on the My Avatar Remote page. Then you use your board
from VRChat's own menu.

## Give a control a slot

1. Click the small circle in a card's top bar (or a category's).
2. A radial opens like VRChat's: **Back** at the top, **1–7** clockwise, each
   saying what has it now. Click a number: the control takes that slot, from
   whatever had it.

The circle then shows the slot's number. Click a number it already has to
free it. A category can sit in both sets: the middle of the picker switches
between Toggles and Radials. **Back**, <kbd>Esc</kbd> or a click elsewhere
closes the picker.

- **Toggles** take toggles and hold buttons. A hold button is held while the
  toggle is on.
- **Radials** take sliders and steppers, across each one's own range.
- A slot holds one thing; one thing can take several slots.
- A category's slot drives every control in it that fits.
- The [Height box](./height.md) takes a Radial.

Slots are kept per preset. The menu drives the board of the avatar you're
wearing, and it follows the board: a toggle is on while any of its controls
is on, a radial sits where its first control is.

:::note
VRChat can't show the names (they're baked in when you upload), so the menu
says *Toggle 1*–*7* and *Radial 1*–*7*. The page shows what has each.
:::

Your own menu ignores locks: they're for friends.

| Parameter | Type | What it does |
|---|---|---|
| `OGP/Remote/Toggle1`–`7` | Bool | On / off for the slot's controls; a hold button is held while it's on. |
| `OGP/Remote/Radial1`–`7` | Float 0–1 | The slot's sliders or steppers, across each one's own range. |
