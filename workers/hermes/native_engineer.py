"""All arguments, tools and execution behavior belong to the pinned upstream CLI."""
import os
import sys

sys.path.insert(0, os.environ['MIKASA_HERMES_SOURCE'])

if __name__ == '__main__':
    from hermes_cli.main import main
    main()
