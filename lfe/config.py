"""Explicit local configuration; never print values or interpolate secrets."""
import os
from pathlib import Path

NEO4J_KEYS = ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD", "NEO4J_DATABASE")
MODEL_KEYS = ("LFE_MODEL_PROVIDER", "LFE_COPILOT_AUTH", "LFE_COPILOT_MODEL",
              "LFE_COPILOT_TIMEOUT_SECONDS", "LFE_DEPLOYMENT_MODE")
TOKEN_KEYS = ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
SDK_OVERRIDE_KEYS = ("COPILOT_CLI_PATH", "COPILOT_HOME")


def _environment(keys, filename, use_file, environ, directory):
    environ = os.environ if environ is None else environ
    result = {}
    token_conflicts = {key for key in TOKEN_KEYS + SDK_OVERRIDE_KEYS if environ.get(key, "").strip()}
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
                    if filename == ".env" and binding.key in TOKEN_KEYS + SDK_OVERRIDE_KEYS and (binding.value or "").strip():
                        token_conflicts.add(binding.key)
                    elif binding.key in keys and binding.value is not None:
                        result[binding.key] = binding.value
        except OSError as exc:
            raise ValueError(f"Cannot read {filename} in the current directory. Create it locally or omit its loading flag.") from exc
    for key in keys:
        if key in environ:
            result[key] = environ[key]
    if filename == ".env":
        result["LFE_SDK_ENV_CONFLICTS"] = sorted(token_conflicts)
    return result


def neo4j_environment(use_env_dev=False, environ=None, directory=None):
    return _environment(NEO4J_KEYS, ".env_dev", use_env_dev, environ, directory)


def model_environment(use_env=False, environ=None, directory=None):
    return _environment(MODEL_KEYS, ".env", use_env, environ, directory)
