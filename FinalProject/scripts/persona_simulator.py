"""Forwarding entrypoint for persona_simulator."""

import runpy
from pathlib import Path

from simulations.persona_simulator import *  # noqa: F403

if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "simulations" / "persona_simulator.py"
    runpy.run_path(str(target), run_name="__main__")
