---
name: autoscript-script-authoring
description: Create, audit, repair, normalize, validate, and package Python scripts for AutoScript Hub. Use when a user asks to write an AutoScript script, convert an existing Python automation into the platform config()/main() contract, fix upload or execution validation errors, normalize a legacy ZIP, define parameters/presets/requirements/results, or produce a platform-ready .py or .zip artifact.
---

# AutoScript Script Authoring

Create or repair scripts against the versioned AutoScript Hub contract, then prove the result with the included validator before presenting it.

## Workflow

1. Determine whether the request needs a single `.py` file or a multi-file ZIP. Prefer one file unless separation materially improves maintainability.
2. Read [references/contract.md](references/contract.md) before creating or repairing a script. For unusual fields or validation failures, treat that reference and validator output as authoritative.
3. Start from [assets/single_script_template.py](assets/single_script_template.py) or [assets/multi_script/main.py](assets/multi_script/main.py). Preserve user business behavior when repairing an existing script.
4. Keep module import free of real work. `config()` must directly return a static dictionary literal; the validator parses it with AST and never imports or executes the candidate script. Import third-party packages lazily from `main()` or its helpers.
5. Make every `params[].key` a unique non-keyword Python identifier and give `main()` exactly the corresponding keyword parameters, unless it intentionally accepts `**kwargs`.
6. Return `None`, one local result path, or a list of local result paths. Do not upload result files to the server.
7. Run strict validation:

   `python scripts/validate_script.py PATH --strict`

8. Fix every error and warning. Do not deliver a script while strict validation is nonzero.
9. For a directory or multi-file result, create a normalized ZIP:

   `python scripts/package_script.py SOURCE_DIR OUTPUT.zip`

10. Validate the produced ZIP again with `--strict`, then report the artifact path, dependency list, parameters, and any runtime assumptions.

## 可选本机浏览器选择

契约及 standalone snapshot 版本为 1.1.0，向后兼容六种既有参数类型。业务需要时按 [契约参考](references/contract.md) 使用 `type: text, widget: browser, default: ''`，不要新增 `type: browser` 或强加到所有模板。

让新客户端参数表单从本机 `/detect-browsers` 动态列出浏览器；保持 `config()` 为严格静态字面量，脚本不调用平台内部包。`main()` 接收普通路径字符串，可选空值沿用平台默认；旧 1.2.4 忽略 widget 并回退手填文本，仍可正常解析依赖。这是脚本参数选择，不是更改系统默认路径。客户端仅检查非空路径为文件，服务端不查本机路径；已安装不等于能启动或兼容，不执行浏览器或 shell 来做契约校验。依赖写入 `requirements`，不让脚本自行运行 pip。

## Repair Existing Scripts

- First run the validator without editing and record each issue code. This is safe for top-level side effects because validation only parses the candidate; it never imports or executes it.
- Preserve business logic, user-visible names, and result semantics unless the user asks to change them.
- Replace dynamic `config()` construction with one directly returned dictionary literal, and move top-level third-party imports behind `main()`.
- Convert legacy single-directory ZIPs so `main.py` is at the ZIP root.
- Normalize requirements to PEP 508 strings and remove duplicates.
- Re-run strict validation after every meaningful repair group.

## Output Rules

- A single-file deliverable ends in `.py` and contains both `config()` and `main()`.
- A multi-file deliverable ends in `.zip` and has root-level `main.py`; never wrap the files in an extra project directory.
- Never include credentials, cookies, tokens, machine-specific absolute paths, virtual environments, caches, or generated result files.
- Do not claim platform compatibility from inspection alone. Strict validator success is required, and real execution is required when the environment is available.

## Included Tools

- `scripts/validate_script.py`: emits issue codes and exits nonzero on contract violations; it uses the repository contract when available and the bundled versioned snapshot otherwise.
- `scripts/package_script.py`: rejects invalid input and creates a deterministic root-normalized ZIP.
- `references/contract.md`: field, parameter, dependency, ZIP, and result rules.
- `assets/`: single-file and multi-file starting templates.
