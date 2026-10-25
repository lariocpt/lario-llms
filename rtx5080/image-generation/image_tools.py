#!/usr/bin/env python3
"""Compatibility entrypoint; machine-setup owns the shared images MCP implementation."""
from pathlib import Path

_source = Path(__file__).resolve().parents[3]/'machine-setup/shared/agents/image_tools.py'
__file__ = str(_source)
exec(compile(_source.read_text(), str(_source), 'exec'), globals())
