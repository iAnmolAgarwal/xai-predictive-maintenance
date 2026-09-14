"""xpm — explainable predictive maintenance.

The package root deliberately holds no runtime logic: every subpackage
(``xpm.config``, ``xpm.contracts``, ``xpm.data``, ...) is imported directly so
that the OpenAPI and WebSocket-schema exporters can load contracts in
isolation.
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
