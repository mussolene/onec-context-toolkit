"""Minimal code indexing helpers for compact 1C code packs."""

from .bsl import BslParser, Call, Symbol, extract_calls, extract_symbols

__all__ = ["BslParser", "Call", "Symbol", "extract_calls", "extract_symbols"]
