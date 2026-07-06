import os

# The TUI runs a newer-version check against GitHub on mount; tests must never
# touch the network (slow, flaky offline). The check honours this opt-out.
os.environ["ACTUISENSE_NO_UPDATE_CHECK"] = "1"
