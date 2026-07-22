from shared.script_contract import validate_script


def parse_script_config(file_path):
    """Compatibility facade over the shared versioned script contract."""
    report = validate_script(file_path, strict=False)
    if report.errors:
        first = report.errors[0]
        if first.code == "script.missing":
            raise FileNotFoundError("Script not found: {}".format(file_path))
        if first.code == "config.missing":
            return None
        raise RuntimeError("{}: {}".format(first.code, first.message))
    return report.config
