"""Run a command with the pinned ffmpeg first on PATH.

The application's clip-feature code calls a plain ``ffmpeg``. This exposes the binary shipped
in the locked ``imageio-ffmpeg`` wheel under that name for the duration of one command:

    uv run python with_ffmpeg.py python ranking/prepare_pipeline_features.py ...
"""
import os
import subprocess
import sys
import tempfile

import imageio_ffmpeg

with tempfile.TemporaryDirectory() as folder:
    os.symlink(imageio_ffmpeg.get_ffmpeg_exe(), os.path.join(folder, "ffmpeg"))
    os.environ["PATH"] = folder + os.pathsep + os.environ["PATH"]
    sys.exit(subprocess.call(sys.argv[1:]))
