"""Test package configuration.

The test machine may run a Chinese Windows.  Existing and future UI
tests assert English text by default, so pin the UI language unless a
test explicitly switches it.
"""

import os

os.environ.setdefault("LAGLENS_LANGUAGE", "en")
