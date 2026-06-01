"""Module entry point: ``python -m connectors.recato [args]`` → ``cli.main``."""
from .cli import main
import sys

sys.exit(main())
