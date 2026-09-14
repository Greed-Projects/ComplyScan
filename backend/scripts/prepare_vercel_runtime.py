from __future__ import annotations

import os
import subprocess
import sys


HEADLESS_OPENCV = "opencv-contrib-python-headless==4.10.0.84"


def main() -> None:
    if not os.getenv("VERCEL"):
        print("ComplyScan: Vercel runtime preparation skipped outside Vercel.")
        return

    print(
        "ComplyScan: replacing the OpenCV GUI binary with the headless server build "
        "while retaining PaddleX's opencv-contrib-python package metadata."
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--force-reinstall",
            "--no-deps",
            HEADLESS_OPENCV,
        ],
        check=True,
    )

    import cv2

    print(f"ComplyScan: headless OpenCV import OK ({cv2.__version__}).")


if __name__ == "__main__":
    main()
