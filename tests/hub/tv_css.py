"""JY-259 (P1, 2026-10-28): tv.css is written in rem tied to the viewport (B.: "It scales to every TV needed"), with
1rem = 16 CSS px at the TCL's 960x540. The older TV tests pin design values in those CSS px; `design_px` reads the sheet
back in them (1.125rem -> 18px), so each pin keeps its meaning. `root_px` is what 1rem is at a given viewport."""
import re

REM = re.compile(r"(?<![\w.#-])(-?\d*\.?\d+)rem\b")
ROOT = re.compile(r"html\.tv \{ font-size: max\((\d+)px, min\(calc\(100vw / ([\d.]+)\), calc\(100vh / ([\d.]+)\)\)\); \}")


def _px(m) -> str:
    v = round(float(m.group(1)) * 16, 4)
    return f"{int(v) if v == int(v) else v}px"


def design_px(css: str) -> str:
    """tv.css with every rem length written back as the CSS px it is at 960x540."""
    return REM.sub(_px, css)


def root_px(css: str, width: float, height: float) -> float:
    """1rem in CSS px at a viewport, from the sheet's one scaling rule."""
    floor, vw, vh = (float(x) for x in ROOT.search(css).groups())
    return max(floor, min(width / vw, height / vh))
