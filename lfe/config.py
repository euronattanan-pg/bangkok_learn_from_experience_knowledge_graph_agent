"""Explicit local configuration; never print values or interpolate secrets."""
import os
from pathlib import Path

NEO4J_KEYS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE")


def neo4j_environment(use_env_dev=False, environ=None, directory=None):
    environ = os.environ if environ is None else environ
    result = {}
    if use_env_dev:
        path = (Path.cwd() if directory is None else Path(directory)) / ".env_dev"
        try:
            from dotenv.parser import parse_stream
        except ImportError as exc:
            raise RuntimeError("Configuration loader missing. Install the project requirements.") from exc
        try:
            with path.open(encoding="utf-8") as stream:
                for binding in parse_stream(stream):
                    if binding.error:
                        raise ValueError(f"Invalid .env_dev syntax at line {binding.original.line}.")
                    if binding.key in NEO4J_KEYS and binding.value is not None:
                        result[binding.key] = binding.value
        except OSError as exc:
            raise ValueError("Cannot read .env_dev in the current directory. Create it locally or omit --env-dev.") from exc
    for key in NEO4J_KEYS:
        if key in environ:
            result[key] = environ[key]
    return result
