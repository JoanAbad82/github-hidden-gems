"""Deep static analysis: bounded file selection, evidence, no execution."""

from .analyzer import DeepAnalyzer
from .evidence_builder import build_evidence
from .file_selector import SelectedFile, select_files

__all__ = ["DeepAnalyzer", "build_evidence", "select_files", "SelectedFile"]
