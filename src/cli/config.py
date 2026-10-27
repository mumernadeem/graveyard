"""
Graveyard configuration loader.
Reads .graveyard.yml from the current directory and merges with defaults.
"""
import os
import sys

try:
    import yaml
except ImportError:
    # Fallback: minimal YAML parser for simple configs (no external dependency)
    yaml = None


# ─── Default configuration ───────────────────────────────────────────────
DEFAULTS = {
    "project": "unnamed-project",
    "environment": "production",
    "checks": {
        "tests": {
            "enabled": True,
            "min_pass_rate": 95,
            "min_coverage": 80,
        },
        "security": {
            "enabled": True,
            "block_on": "CRITICAL",
            "warn_on": "HIGH",
            "max_high": 5,
        },
        "k8s": {
            "enabled": True,
            "namespace": "default",
            "require_limits": True,
            "require_probes": True,
            "min_replicas": 2,
        },
        "dependencies": {
            "enabled": True,
            "urls": [],
            "warn_latency": 3,
        },
        "compliance": {
            "enabled": True,
        },
        "cost": {
            "enabled": True,
            "warn_threshold": 50,
        },
    },
}


def _deep_merge(base, override):
    """Recursively merge override dict into base dict. Override wins on conflicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _parse_simple_yaml(filepath):
    """
    Minimal YAML parser for flat/nested configs when PyYAML is not installed.
    Handles: key: value, nested dicts, lists of scalars, and lists of dicts.
    NOT a full YAML parser — just enough for .graveyard.yml.
    """
    with open(filepath, "r") as f:
        lines = f.readlines()

    return _parse_yaml_lines(lines, 0, 0)[0]


def _parse_yaml_lines(lines, start_idx, base_indent):
    """Recursively parse YAML lines starting from start_idx at given indent level."""
    result = {}
    i = start_idx
    current_list_key = None

    while i < len(lines):
        line = lines[i]
        stripped = line.rstrip()

        # Skip empty lines and comments
        if not stripped or stripped.lstrip().startswith("#"):
            i += 1
            continue

        indent = len(line) - len(line.lstrip())
        content = stripped.lstrip()

        # If we've gone back to a lower indent, we're done with this block
        if indent < base_indent and i > start_idx:
            break

        # List item
        if content.startswith("- "):
            list_content = content[2:].strip()

            if current_list_key and current_list_key in result:
                if not isinstance(result[current_list_key], list):
                    result[current_list_key] = []

                if ": " in list_content:
                    # First key-value of a dict in a list
                    k, v = list_content.split(": ", 1)
                    new_item = {k.strip(): _cast_value(v.strip())}

                    # Look ahead for more key-values at deeper indent
                    list_item_indent = indent + 2
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j]
                        next_stripped = next_line.rstrip()
                        if not next_stripped or next_stripped.lstrip().startswith("#"):
                            j += 1
                            continue
                        next_indent = len(next_line) - len(next_line.lstrip())
                        next_content = next_stripped.lstrip()
                        if next_indent >= list_item_indent and not next_content.startswith("- "):
                            if ": " in next_content:
                                nk, nv = next_content.split(": ", 1)
                                new_item[nk.strip()] = _cast_value(nv.strip())
                            j += 1
                        else:
                            break
                    result[current_list_key].append(new_item)
                    i = j
                    continue
                else:
                    result[current_list_key].append(_cast_value(list_content))
            i += 1
            continue

        # Key: value pair
        if ": " in content:
            key, value = content.split(": ", 1)
            key = key.strip()
            value = value.strip()
            result[key] = _cast_value(value)
            current_list_key = None
            i += 1
            continue

        # Key with no value (nested dict or empty list)
        if content.endswith(":"):
            key = content[:-1].strip()

            # Peek at next non-empty line to decide if it's a list or dict
            j = i + 1
            child_indent = None
            is_list = False
            while j < len(lines):
                peek_line = lines[j]
                peek_stripped = peek_line.rstrip()
                if peek_stripped and not peek_stripped.lstrip().startswith("#"):
                    child_indent = len(peek_line) - len(peek_line.lstrip())
                    is_list = peek_stripped.lstrip().startswith("- ")
                    break
                j += 1

            if child_indent is not None and child_indent > indent:
                if is_list:
                    result[key] = []
                    current_list_key = key
                    i += 1
                    continue
                else:
                    child_result, next_i = _parse_yaml_lines(lines, i + 1, child_indent)
                    result[key] = child_result
                    current_list_key = None
                    i = next_i
                    continue
            else:
                result[key] = {}
                current_list_key = None

        i += 1

    return result, i


def _cast_value(value):
    """Convert string values to appropriate Python types."""
    # Strip surrounding quotes (single or double)
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value == "[]":
        return []
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def load_config(config_path=None):
    """
    Load Graveyard configuration.

    Priority:
    1. Explicit config_path argument
    2. .graveyard.yml in current directory
    3. Default configuration

    Returns a merged config dict.
    """
    # Determine config file path
    if config_path is None:
        config_path = os.path.join(os.getcwd(), ".graveyard.yml")

    # If no config file exists, use defaults
    if not os.path.exists(config_path):
        return DEFAULTS.copy(), False  # (config, was_file_found)

    # Read and parse the config file
    try:
        if yaml:
            with open(config_path, "r") as f:
                user_config = yaml.safe_load(f) or {}
        else:
            user_config = _parse_simple_yaml(config_path)
    except Exception as e:
        print(f"\033[91mError reading config file '{config_path}': {e}\033[0m")
        print("Using default configuration.")
        return DEFAULTS.copy(), False

    # Validate basic structure
    if not isinstance(user_config, dict):
        print(f"\033[91mInvalid config file: expected a YAML mapping, got {type(user_config).__name__}\033[0m")
        print("Using default configuration.")
        return DEFAULTS.copy(), False

    # Merge user config with defaults (user wins on conflicts)
    merged = _deep_merge(DEFAULTS, user_config)
    return merged, True


def get_check_config(config, check_name):
    """Get the config for a specific check, with defaults applied.

    Returns the check's config dict if it exists, or a sentinel
    ``{"enabled": False}`` for checks not present in the config so that
    downstream code can safely call ``is_check_enabled()`` and skip.
    """
    checks = config.get("checks", {})
    if check_name in checks:
        return checks[check_name]
    return {"enabled": False}


def is_check_enabled(config, check_name):
    """Check if a specific check is enabled in the config.

    If the check exists in the config but has no explicit ``enabled`` key,
    it defaults to ``True``.  If the check is entirely absent from the
    config, it is treated as disabled (``False``).
    """
    check_cfg = get_check_config(config, check_name)
    return check_cfg.get("enabled", True)
