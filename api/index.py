"""Vercel serverless entrypoint for the Industry Pioneers Club Flask app.

Vercel's @vercel/python runtime looks for an object named `app` (or `handler`)
in the module it's told to serve. We re-export the Flask instance from the
project root here so Vercel can mount it.

The project root (where app.py lives) is one level above this file;
we add it to sys.path so `from app import app` succeeds inside the
serverless function sandbox at /var/task/.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_HERE)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from app import app   # noqa: E402  (sys.path adjusted above)

# Vercel's @vercel/python looks for `app` (WSGI). Flask instances are WSGI
# callables, so no further wrapping is needed.
