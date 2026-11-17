"""Explicit local configuration; never print values or interpolate secrets."""
import os
from pathlib import Path

NEO4J_KEYS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE")
MODEL_KEYS = ("LFE_MODEL_PROVIDER", "COPILOT_GITHUB_TOKEN")


def _environment(keys, filename, use_file, environ, directory):
    environ = os.environ if environ is None else environ
    result = {}
    if use_file:
        path = (Path.cwd() if directory is None else Path(directory)) / filename
        try:
            from dotenv.parser import parse_stream
        except ImportError as exc:
            raise RuntimeError("Configuration loader missing. Install the project requirements.") from exc
        try:
            with path.open(encoding="utf-8") as stream:
                for binding in parse_stream(stream):
                    if binding.error:
                        raise ValueError(f"Invalid {filename} syntax at line {binding.original.line}.")
                    if binding.key in keys and binding.value is not None:
                        result[binding.key] = binding.value
        except OSError as exc:
            raise ValueError(f"Cannot read {filename} in the current directory. Create it locally or omit its loading flag.") from exc
    for key in keys:
        if key in environ:
            result[key] = environ[key]
    return result


def neo4j_environment(use_env_dev=False, environ=None, directory=None):
    return _environment(NEO4J_KEYS, ".env_dev", use_env_dev, environ, directory)


def model_environment(use_env=False, environ=None, directory=None):
    return _environment(MODEL_KEYS, ".env", use_env, environ, directory)
