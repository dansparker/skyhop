"""Entry point for shared hosting with Phusion Passenger (cPanel/Plesk „Python App“)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wsgi import application  # noqa: E402,F401
