# AutoScript Hub Script Contract 1.1.0

Contract 1.1.0 adds backward-compatible optional browser presentation metadata; the six parameter types are unchanged. The standalone validator snapshot ships the same contract version.

## Required functions

Every script exposes a declarative `config()` and an executable `main()`. `config()` must directly return one static dictionary literal (an optional docstring is allowed). Validation parses that return value with Python AST and never imports the candidate module, executes top-level code, calls `config()`, or calls `main()`.

## config fields

- `name`: non-empty string.
- `version`: SemVer such as `1.0.0`.
- `description`: string.
- `category`: string.
- `params`: array of parameter definitions.
- `requirements`: PEP 508 strings, for example `requests>=2.31`.
- `timeout`: positive integer seconds, at most 86400.
- `presets`: optional array of `{name, values}` objects; values may reference only defined keys.

## parameters

Every definition has `key`, `type`, and non-empty `label`. `required` is optional and Boolean.

Supported types are `text`, `number`, `file`, `folder`, `select`, and `checkbox`.

- Keys are unique valid Python identifiers and not Python keywords.
- `number` may use numeric `min`, `max`, and `default`; ranges must be consistent.
- `select` has non-empty `options`; its default belongs to those options.
- `checkbox` has a Boolean default.
- `text`, `file`, and `folder` have string defaults when supplied.
- The server checks shape and ranges; the executing Windows Agent checks local file/folder existence.

### 本机浏览器参数（可选）

仅在业务需要用户选择浏览器时声明，不必给每个脚本添加：

```python
{'key': 'browser_path', 'type': 'text', 'widget': 'browser',
 'label': '浏览器（留空使用默认设置）', 'default': ''}
```

- `widget` 是展示元数据，不是新参数类型；提供时必须是字符串 `browser` 且搭配 `type: text`。未知或非字符串值报 `params.widget`，非法类型组合报 `params.widget-type`。
- 默认值及提交值遵循现有 `text` 校验；可选参数留空沿用平台默认设置，`main(browser_path='')` 接收普通路径字符串，不接收浏览器对象。
- 新客户端参数表单从本机 `/detect-browsers` 动态查询列表；`config()` 仍只返回静态字面量。脚本不调用平台内部包，不自行探测列表或运行 shell。
- 旧 1.2.4 忽略未知 `widget` 键，回退为手填文本并正常解析依赖；不要改成 `type: browser`，旧 Agent 不认识该类型可能吞掉解析错误。
- 这是单次脚本参数中的本机浏览器选择，不修改系统或平台默认浏览器路径；示例默认值保持空字符串，不嵌入机器专用路径。
- 客户端 `check_paths=True` 对非空值检查本地路径为文件；服务端 `check_paths=False` 不检查本机路径。验证不执行浏览器或 shell；已安装不代表能启动或与脚本兼容，运行兼容性另行验证。

## imports and dependencies

Only the Python standard library should be imported at module scope. Put third-party imports inside `main()` or a helper called by `main()`. List every runtime package in `requirements`; never run `pip` from the script.

## ZIP layout

The normalized layout is:

```text
script.zip
  main.py
  optional_module.py
  optional_data/
```

Absolute paths, drive-qualified paths, symlinks, and `..` traversal members are rejected. A legacy single wrapper directory is only a compatibility warning and fails strict Skill validation.

## results

Return `None`, a local path string, or a list of local path strings. Results stay on the executing client. Never embed file contents or secrets in run metadata.
