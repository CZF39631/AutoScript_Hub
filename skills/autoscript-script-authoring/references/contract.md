# AutoScript Hub Script Contract 1.0.0

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
