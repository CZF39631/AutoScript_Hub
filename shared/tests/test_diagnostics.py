import json

from shared.diagnostics import (
    MAX_PARAM_BYTES, REDACTED, parse_diagnostic_params, redact_data,
    redact_text, sensitive_values,
)


def test_nested_secrets_and_custom_fields():
    data = {"count": 3, "nested": [{"password": "private-value", "remark": "private-value"}],
            "businessCode": "hidden-code"}
    fields = ["businessCode"]
    secrets = sensitive_values(data, fields)
    result = redact_data(data, secrets, fields)
    assert result["count"] == 3
    assert result["nested"][0] == {"password": REDACTED, "remark": REDACTED}
    assert result["businessCode"] == REDACTED
    assert "hidden-code" not in redact_text("businessCode=hidden-code", custom_fields=fields)


def test_urls_auth_headers_and_private_keys():
    text = ('https://user:proxy-pass@example.com/file?X-Amz-Signature=signed-value#fragment\n'
            'Authorization: Bearer bearer-value\nCookie: sid=cookie-one; auth=cookie-two\npassword="two word secret"\n'
            '-----BEGIN PRIVATE KEY-----\nkey-material\n-----END PRIVATE KEY-----')
    result = redact_text(text)
    assert "https://example.com/file" in result
    for secret in ("proxy-pass", "signed-value", "bearer-value", "two word secret", "key-material", "fragment", "cookie-one", "cookie-two"):
        assert secret not in result
    assert "partial-key" not in redact_text("partial-key\n-----END PRIVATE KEY-----\nnormal")


def test_custom_fields_are_literals_not_regex():
    result = redact_text("a+b=private\naxb=public", custom_fields=["a+b"])
    assert "private" not in result
    assert "axb=public" in result


def test_malformed_large_and_deep_params_fail_bounded():
    for raw in ('{"password": "unclosed', '"scalar"', '{"count":NaN}', '[' * 1200, 'x' * (MAX_PARAM_BYTES + 1)):
        assert "诊断提示" in parse_diagnostic_params(raw)
    nested = {"value": "deep-secret"}
    for _ in range(30):
        nested = {"nested": nested}
    assert "deep-secret" not in str(parse_diagnostic_params(json.dumps(nested)))
    assert parse_diagnostic_params(None) == {}
    assert parse_diagnostic_params('{"count":3}') == {"count": 3}
