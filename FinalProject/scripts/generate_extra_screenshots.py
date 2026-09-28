"""
Module: generate_extra_screenshots.py
Captures high-resolution visual screenshots for API response and Terminal simulation
using Google Chrome headless mode.
"""

import os
import shutil
import subprocess

REPORTS_DIR = "reports"
SCREENSHOTS_DIR = "FinalProject/docs/screenshots"
CHROME_PATH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def capture_screenshot(url: str, output_path: str, width: int = 1920, height: int = 1200) -> bool:
    """Takes a headless Chrome screenshot of the specified local or remote URL."""
    if not os.path.exists(CHROME_PATH):
        print(f"Warning: Chrome binary not found at {CHROME_PATH}")
        return False

    cmd = [
        CHROME_PATH,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        f"--window-size={width},{height}",
        "--virtual-time-budget=3000",
        f"--screenshot={output_path}",
        url,
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error capturing screenshot for {url}: {e}")
        return False


def main():
    """Captures API prediction inspector and terminal simulation screenshots."""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

    api_url = "http://localhost:18080/screenshot_api_response.html"
    api_out = os.path.join(SCREENSHOTS_DIR, "01b_fastapi_prediction_response.png")
    capture_screenshot(api_url, api_out, width=1920, height=1180)

    term_url = "http://localhost:18080/screenshot_terminal_sim.html"
    term_out = os.path.join(SCREENSHOTS_DIR, "08_terminal_drift_simulation_execution.png")
    capture_screenshot(term_url, term_out, width=1920, height=1300)

    print("Screenshots captured successfully.")


if __name__ == "__main__":
    if shutil.which("curl"):
        main()
