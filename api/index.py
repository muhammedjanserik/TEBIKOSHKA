"""Vercel Python function entry point."""
from app import Handler

class handler(Handler):
    """Explicit HTTP handler class for Vercel's Python function discovery."""
    pass
