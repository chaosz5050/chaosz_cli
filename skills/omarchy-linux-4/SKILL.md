---
name: omarchy-linux-4
description: Manage and configure Omarchy Quattro (4.x), Hyprland Lua overrides, the Omarchy shell, themes, keybindings, window rules, monitors, and terminal settings. Use for Omarchy, Hyprland, Quickshell, window gaps, Waybar migration, or omarchy commands.
compatibility: Omarchy Quattro (4.x) on Linux; inspect the installed version before making version-sensitive changes.
---

# Omarchy Quattro

Work safely with Omarchy 4.x (Quattro). It changed the active Hyprland user configuration from `.conf` files to Lua and replaced the default Waybar setup with the Omarchy shell (Quickshell). Never apply pre-4 `.conf` instructions to a Quattro installation.

## Safety and discovery

1. Start version-sensitive work with `omarchy version`, then inspect the relevant user file before editing it.
2. Do **not** edit `/usr/share/omarchy/` (or a legacy `~/.local/share/omarchy/`) because those are package-owned defaults. Put customizations in `~/.config/`.
3. Discover available commands with `omarchy commands` or `omarchy <group> --help`; do not invent `omarchy-*` command names.
4. Use read-only inspection before proposing a change. Preserve existing user customizations and explain any conflict with an existing binding or setting.

## Quattro configuration map

```text
~/.config/hypr/
├── hyprland.lua       # Entry point: loads defaults, then the user files below
├── bindings.lua       # Personal keybindings and binding overrides
├── monitors.lua       # Monitors, modes, positions, scales
├── input.lua          # Keyboard, mouse, and touchpad
├── looknfeel.lua      # Gaps, borders, rounding, animations, layout appearance
└── autostart.lua      # Extra session processes

~/.config/omarchy/shell.json  # Omarchy shell/bar position, widgets, lock and idle settings
~/.config/foot/foot.ini       # Default terminal
```

`hyprland.lua` already loads the user Lua files after Omarchy defaults. Do not modify its bootstrap/default `require(...)` lines unless diagnosing a documented migration problem.

## Hyprland Lua rules

- User configuration uses the helpers already loaded by Omarchy: `hl.config({...})`, `hl.monitor({...})`, `o.bind(...)`, `o.unbind(...)`, and `o.window(...)`.
- Read the existing file and copy its Lua style. Do not write legacy `key = value` Hyprland `.conf` syntax into a `.lua` file.
- After **every** Hyprland change, run `hyprctl reload` and then `hyprctl configerrors`. If either reports an error, fix it and validate again before declaring success.
- Before adding or changing a window rule, fetch the current official Hyprland Window Rules documentation. Syntax changes across Hyprland versions. Prefer Omarchy’s `o.window(match, rules)` helper and inspect `/usr/share/omarchy/default/hypr/windows.lua` or `helpers.lua` for current local examples.

## Window gaps and borders

For a question about current margins/gaps, inspect the active user override first:

```bash
rg -n -C 3 'gaps_in|gaps_out|border_size' ~/.config/hypr/looknfeel.lua
hyprctl getoption general:gaps_in
hyprctl getoption general:gaps_out
```

`gaps_in` is the space between tiled windows. `gaps_out` is the space from windows to screen edges. `border_size` controls the border width. In a stock Quattro setup the default look-and-feel uses `gaps_in = 5`, `gaps_out = 10`, and `border_size = 2`, but the live user file and `hyprctl getoption` output are authoritative.

To change these values, edit the existing `hl.config` table in `~/.config/hypr/looknfeel.lua`; do not create or read `looknfeel.conf`.

## Keybindings, monitors, and shell

- Bindings belong in `~/.config/hypr/bindings.lua`. Check existing bindings first; use `o.unbind("SUPER + KEY")` before intentionally overriding a default, and tell the user what was replaced.
- Monitors belong in `~/.config/hypr/monitors.lua`. Use `hyprctl monitors all` before choosing an output name or mode. Use `hl.monitor({ output = "…", mode = "…", position = "…", scale = 1 })`.
- Omarchy’s default bar/shell is no longer Waybar. For bar layout, widgets, screensaver, lock, or idle behavior, inspect `~/.config/omarchy/shell.json`. Do not assume `~/.config/waybar/` controls the active shell.
- Use Omarchy commands for themes, fonts, refreshes, and system actions when available; check `--help` before executing a command whose spelling or arguments are uncertain.

## Completion report

State the exact user-owned file changed, the behavior affected, whether an existing setting was overridden, and the result of `hyprctl reload` plus `hyprctl configerrors`. For read-only questions, report the live values and the file/line they came from.
