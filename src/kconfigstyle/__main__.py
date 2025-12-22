"""Allow running the package with `python -m kconfigstyle`."""

import sys

from . import main

if __name__ == "__main__":
    sys.exit(main())
