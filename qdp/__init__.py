"""qdp package.

Keep package import side-effect free so CLI, tests, and frozen builds can import
submodules without pulling in the full runtime eagerly.
"""

__all__ = []
