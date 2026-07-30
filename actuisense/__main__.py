"""Allow running as ``python -m actuisense`` (e.g. where exe shims are blocked)."""

from actuisense.cli import main

if __name__ == "__main__":
    main()
