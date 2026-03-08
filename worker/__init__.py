"""RunPod worker package for HotShort Extraction Engine v2.

This package contains a lightweight queue consumer and signal acquisition
utilities used by the external worker process.

Importing the package itself does *not* pull in heavy dependencies; users
should import the submodules they need explicitly (e.g. ``from worker import
contracts``).
"""
