"""Versioned validation contract for AutoScript Hub scripts."""

from __future__ import annotations

import ast
from dataclasses import dataclass, replace
import keyword
import ntpath
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import tokenize
from typing import Any, Optional, Sequence
import zipfile

from packaging.requirements import InvalidRequirement, Requirement


SCRIPT_CONTRACT_VERSION = "1.0.0"
PARAMETER_TYPES = {"text", "number", "file", "folder", "select", "checkbox"}
_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    severity: str = "error"


@dataclass
class ValidationReport:
    config: Optional[dict]
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]

    @property
    def ok(self) -> bool:
        return not self.errors


def _issue(code: str, message: str, path: str = "") -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path)


def _warning(code: str, message: str, path: str = "") -> ValidationIssue:
    return ValidationIssue(code=code, message=message, path=path, severity="warning")


def _safe_zip_parts(info: zipfile.ZipInfo) -> Optional[tuple[str, ...]]:
    name = info.filename.replace("\\", "/")
    if not name or name.startswith("/") or ntpath.splitdrive(name)[0]:
        return None
    parts = PurePosixPath(name).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        return None
    mode = (info.external_attr >> 16) & 0o170000
    if mode == stat.S_IFLNK:
        return None
    return tuple(parts)


def extract_script_archive(archive: os.PathLike[str] | str, destination: os.PathLike[str] | str) -> Path:
    """Safely extract a validated script ZIP and return its main.py path."""
    archive_path = Path(archive)
    destination_path = Path(destination)
    try:
        bundle = zipfile.ZipFile(archive_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError("ZIP 文件损坏或无法读取") from exc

    with bundle:
        members: list[tuple[zipfile.ZipInfo, tuple[str, ...]]] = []
        for info in bundle.infolist():
            parts = _safe_zip_parts(info)
            if parts is None:
                raise ValueError(f"ZIP 包含不安全路径: {info.filename}")
            members.append((info, parts))

        destination_path.mkdir(parents=True, exist_ok=True)
        for info, parts in members:
            target = destination_path.joinpath(*parts)
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)

    root_main = destination_path / "main.py"
    if root_main.is_file():
        return root_main

    top_directories = {parts[0] for _, parts in members if len(parts) > 1}
    if len(top_directories) == 1:
        legacy_main = destination_path / next(iter(top_directories)) / "main.py"
        if legacy_main.is_file():
            return legacy_main
    raise ValueError("ZIP 根目录必须包含 main.py")


def _load_config(script_path: Path) -> tuple[Optional[dict], Optional[ValidationIssue]]:
    try:
        with tokenize.open(script_path) as source:
            tree = ast.parse(source.read(), filename=str(script_path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        return None, _issue("script.syntax", f"脚本无法解析: {exc}", "main.py")

    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "config"
    ]
    if not functions:
        return None, _issue("config.missing", "脚本必须包含可调用的 config()", "config")

    body = list(functions[0].body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Return) or body[0].value is None:
        return None, _issue(
            "config.static",
            "config() 必须直接返回一个静态字面量对象，验证器不会执行候选脚本",
            "config",
        )
    try:
        value = ast.literal_eval(body[0].value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None, _issue(
            "config.static",
            "config() 必须直接返回一个静态字面量对象，不能调用函数或读取运行时状态",
            "config",
        )
    if not isinstance(value, dict):
        return None, _issue("config.type", "config() 必须返回对象", "config")
    return value, None


def _validate_parameter_definitions(config: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    definitions = config.get("params")
    if not isinstance(definitions, list):
        return [_issue("params.type", "params 必须是数组", "params")]

    keys: set[str] = set()
    for index, definition in enumerate(definitions):
        path = f"params[{index}]"
        if not isinstance(definition, dict):
            issues.append(_issue("params.item", "参数定义必须是对象", path))
            continue
        key = definition.get("key")
        if not isinstance(key, str) or not key.isidentifier() or keyword.iskeyword(key) or key in keys:
            issues.append(_issue("params.key", "参数 key 必须唯一且是非关键字 Python 标识符", f"{path}.key"))
        else:
            keys.add(key)
        param_type = definition.get("type")
        if param_type not in PARAMETER_TYPES:
            issues.append(_issue("params.type", "参数 type 不受支持", f"{path}.type"))
            continue
        if not isinstance(definition.get("label"), str) or not definition.get("label", "").strip():
            issues.append(_issue("params.label", "参数 label 不能为空", f"{path}.label"))
        if "required" in definition and not isinstance(definition["required"], bool):
            issues.append(_issue("params.required", "required 必须是布尔值", f"{path}.required"))

        default = definition.get("default")
        if param_type == "number":
            numeric = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool)
            minimum = definition.get("min")
            maximum = definition.get("max")
            if "default" in definition and not numeric(default):
                issues.append(_issue("params.number-default", "number 默认值必须是数字", f"{path}.default"))
            if minimum is not None and not numeric(minimum):
                issues.append(_issue("params.number-range", "min 必须是数字", f"{path}.min"))
            if maximum is not None and not numeric(maximum):
                issues.append(_issue("params.number-range", "max 必须是数字", f"{path}.max"))
            if numeric(minimum) and numeric(maximum) and minimum > maximum:
                issues.append(_issue("params.number-range", "min 不能大于 max", path))
            if numeric(default) and numeric(minimum) and default < minimum:
                issues.append(_issue("params.number-default", "默认值不能小于 min", f"{path}.default"))
            if numeric(default) and numeric(maximum) and default > maximum:
                issues.append(_issue("params.number-default", "默认值不能大于 max", f"{path}.default"))
        elif param_type == "select":
            options = definition.get("options")
            if not isinstance(options, list) or not options:
                issues.append(_issue("params.select-options", "select options 必须是非空数组", f"{path}.options"))
            elif "default" in definition and default not in options:
                issues.append(_issue("params.select-default", "select 默认值必须属于 options", f"{path}.default"))
        elif param_type == "checkbox" and "default" in definition and not isinstance(default, bool):
            issues.append(_issue("params.checkbox-default", "checkbox 默认值必须是布尔值", f"{path}.default"))
        elif param_type in {"text", "file", "folder"} and "default" in definition and not isinstance(default, str):
            issues.append(_issue("params.text-default", "默认值必须是字符串", f"{path}.default"))
    return issues


def _validate_config(config: dict) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key in ("name", "description", "category"):
        value = config.get(key)
        if not isinstance(value, str) or (key == "name" and not value.strip()):
            issues.append(_issue(f"config.{key}", f"{key} 必须是字符串，name 不能为空", key))

    version = config.get("version")
    if not isinstance(version, str) or not _SEMVER.fullmatch(version.lstrip("v")):
        issues.append(_issue("config.version", "version 必须符合 SemVer", "version"))

    timeout = config.get("timeout")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0 or timeout > 86400:
        issues.append(_issue("config.timeout", "timeout 必须是 1 到 86400 的整数秒", "timeout"))

    issues.extend(_validate_parameter_definitions(config))

    requirements = config.get("requirements")
    normalized: list[str] = []
    if not isinstance(requirements, list) or not all(isinstance(item, str) for item in requirements):
        issues.append(_issue("requirements.type", "requirements 必须是字符串数组", "requirements"))
    else:
        for index, item in enumerate(requirements):
            try:
                normalized.append(str(Requirement(item)))
            except InvalidRequirement:
                issues.append(_issue("requirements.invalid", f"依赖不符合 PEP 508: {item}", f"requirements[{index}]"))
        if not any(issue.code.startswith("requirements.") for issue in issues):
            config["requirements"] = sorted(set(normalized), key=str.casefold)

    presets = config.get("presets", [])
    param_keys = {item.get("key") for item in config.get("params", []) if isinstance(item, dict)}
    if not isinstance(presets, list):
        issues.append(_issue("presets.type", "presets 必须是数组", "presets"))
    else:
        for index, preset in enumerate(presets):
            path = f"presets[{index}]"
            if not isinstance(preset, dict) or not isinstance(preset.get("name"), str) or not preset.get("name", "").strip():
                issues.append(_issue("presets.item", "预设必须包含非空 name", path))
                continue
            values = preset.get("values")
            if not isinstance(values, dict) or not set(values).issubset(param_keys):
                issues.append(_issue("presets.values", "预设 values 必须只引用已定义参数", f"{path}.values"))
    return issues


def _validate_main_signature(script_path: Path, config: dict) -> list[ValidationIssue]:
    try:
        with tokenize.open(script_path) as source:
            tree = ast.parse(source.read(), filename=str(script_path))
    except (OSError, SyntaxError, UnicodeError) as exc:
        return [_issue("script.syntax", f"脚本无法解析: {exc}", "main.py")]

    functions = [
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "main"
    ]
    if not functions:
        return [_issue("main.missing", "脚本必须包含 main()", "main")]
    function = functions[0]
    configured = {item["key"] for item in config.get("params", []) if isinstance(item, dict) and isinstance(item.get("key"), str)}
    accepted = {
        argument.arg
        for argument in function.args.posonlyargs + function.args.args + function.args.kwonlyargs
    }
    if function.args.kwarg is None and configured != accepted:
        missing = sorted(configured - accepted)
        extra = sorted(accepted - configured)
        return [_issue("main.signature", f"main() 参数与 config 不一致；缺少 {missing}，多出 {extra}", "main")]
    return []


def validate_script(path: os.PathLike[str] | str, strict: bool = False) -> ValidationReport:
    """Validate a .py or .zip script without invoking main()."""
    candidate = Path(path)
    if not candidate.is_file():
        return ValidationReport(None, [_issue("script.missing", "脚本文件不存在", str(candidate))], [])

    warnings: list[ValidationIssue] = []
    errors: list[ValidationIssue] = []
    temporary: Optional[tempfile.TemporaryDirectory[str]] = None
    script_path = candidate
    try:
        if candidate.suffix.lower() == ".zip":
            temporary = tempfile.TemporaryDirectory(prefix="autoscript-validate-")
            destination = Path(temporary.name)
            try:
                script_path = extract_script_archive(candidate, destination)
            except ValueError as exc:
                message = str(exc)
                code = "zip.unsafe-path" if "不安全路径" in message else "zip.structure"
                return ValidationReport(None, [_issue(code, message, str(candidate))], [])
            if script_path.parent != destination:
                warnings.append(_warning("zip.legacy-root", "历史 ZIP 使用单层目录；请把 main.py 移到根目录", str(candidate)))
        elif candidate.suffix.lower() != ".py":
            return ValidationReport(None, [_issue("script.extension", "仅支持 .py 和 .zip", str(candidate))], [])

        config, load_error = _load_config(script_path)
        if load_error:
            errors.append(load_error)
        if config is not None:
            errors.extend(_validate_config(config))
            if not errors:
                errors.extend(_validate_main_signature(script_path, config))

        if strict and warnings:
            errors.extend(replace(item, severity="error") for item in warnings)
            warnings = []
        return ValidationReport(config, errors, warnings)
    finally:
        if temporary is not None:
            temporary.cleanup()


def validate_params(
    param_defs: Sequence[dict],
    params: dict,
    check_paths: bool,
) -> list[str]:
    """Validate submitted values; only a client may check its local paths."""
    errors: list[str] = []
    definitions = {item.get("key"): item for item in param_defs if isinstance(item, dict) and item.get("key")}
    for key in params:
        if key not in definitions:
            errors.append(f"未知参数: {key}")

    for key, definition in definitions.items():
        label = definition.get("label") or key
        value = params.get(key)
        if definition.get("required") and (value is None or value == ""):
            errors.append(f"{label} 为必填项")
            continue
        if value is None or value == "":
            continue
        param_type = definition.get("type")
        if param_type == "number":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                errors.append(f"{label} 必须是数字")
                continue
            if definition.get("min") is not None and value < definition["min"]:
                errors.append(f"{label} 小于最小值 {definition['min']}")
            if definition.get("max") is not None and value > definition["max"]:
                errors.append(f"{label} 大于最大值 {definition['max']}")
        elif param_type == "select" and value not in definition.get("options", []):
            errors.append(f"{label} 不是有效可选项")
        elif param_type == "checkbox" and not isinstance(value, bool):
            errors.append(f"{label} 必须是布尔值")
        elif param_type in {"text", "file", "folder"} and not isinstance(value, str):
            errors.append(f"{label} 必须是字符串")
        elif check_paths and param_type == "file" and not os.path.isfile(value):
            errors.append(f"{label} 文件不存在: {value}")
        elif check_paths and param_type == "folder" and not os.path.isdir(value):
            errors.append(f"{label} 文件夹不存在: {value}")
    return errors
