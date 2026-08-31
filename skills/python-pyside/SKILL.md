---
name: python-pyside
description: Build and improve Python desktop GUI applications with PySide6, PyQt, Qt Widgets, Qt Quick, and QML. Use for Python GUI, desktop app, Qt UI, dialogs, forms, layouts, and PySide6.
globs: **/*.py
---

# Python Desktop UI: PySide6

Build complete, maintainable desktop applications—not static mockups. First inspect the existing project, its dependencies, and its UI approach; extend the established approach unless the user requests a migration.

## Choose the right Qt surface

- Use **Qt Widgets** for conventional desktop tools: forms, preferences, tables, lists, menus, dialogs, editors, and utility apps. Hand-written widget layouts are appropriate for small and medium apps.
- Use **Qt Quick/QML** only when the project already uses it or the task benefits from declarative, highly animated, touch-oriented UI. Keep business logic, persistence, and I/O in Python `QObject` classes exposed through explicit properties and slots.
- Use Qt Designer and `.ui` files when the project already uses them or the user asks for visual design files. Never hand-edit generated `ui_*.py` files; otherwise do not introduce Designer just for ceremony.

## Build workflow

1. Inspect existing Python, UI, test, and launch files. For a new project, initialize with `uv` and add only the required Qt package.
2. Create the smallest runnable vertical slice: application entry point, one window, one useful interaction, and the needed state/persistence.
3. Keep UI composition separate from domain/state logic where it helps testing. Avoid needless frameworks, service layers, or custom widget abstractions.
4. Use layouts (`QVBoxLayout`, `QHBoxLayout`, `QGridLayout`, form layouts) instead of fixed coordinates. Set practical minimum sizes and stretch factors; let the window resize naturally.
5. Connect signals with modern `signal.connect(slot)` syntax. Give slots focused names. For repeated controls, use a dedicated method or `functools.partial` rather than a closure-prone loop lambda.
6. Keep blocking work off the GUI thread. Use `QThread`, a worker object, or an existing project executor for network, subprocess, and expensive file operations. Return UI updates via signals.

## UI quality and behavior

- Establish clear hierarchy: a useful window title, primary action, grouped controls, consistent spacing, and deliberate empty/loading/error states.
- Prefer native controls and a small application stylesheet over extra theme dependencies. Do not add a styling library, icon pack, or QML runtime unless the user asks or the project already depends on it.
- Make keyboard behavior real: sensible tab order, Enter/Escape behavior for dialogs, shortcuts where useful, and visible disabled/error states.
- Persist user data through a small, explicit storage layer. Handle missing or malformed local data safely.
- Use type hints for public functions, state objects, and non-trivial slots. Do not annotate every Qt signal merely for appearances.

## Verification is mandatory

After changing source code, verify more than imports. Run the project’s existing test command when available. For a new Widgets app, use an offscreen smoke test such as `QT_QPA_PLATFORM=offscreen uv run python ...` to instantiate the `QApplication` and main window, then exercise the behavior changed (add/remove/toggle/save, etc.). For QML, load the QML engine and confirm it creates a root object. Also run a compile/import check when appropriate.

If a GUI test fails, report the actual Qt error, fix it, and rerun the test. Do not claim success merely because files were written or the window would probably open.

## Completion report

State the files changed, the user-visible behavior, the framework choice (Widgets or QML) when relevant, and the exact verification command and result.
