"""Launch the unmodified pinned Gateway with an explicit isolated profile."""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.environ["MIKASA_HERMES_SOURCE"])
if __name__ == "__main__":
    if Path.cwd() != Path(os.environ["HERMES_HOME"]) / "workspace":
        raise SystemExit("isolated workspace required")
    from gateway.run import main
    main()
