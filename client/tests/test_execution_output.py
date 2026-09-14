import json
from client.runtime.execution_output import bounded_execution_output


def test_long_unicode_error_and_results_fit_report_contract():
    result = bounded_execution_output('异常' * 5000, ['文件' * 500] * 200, '输出' * 40000)
    assert len(result['error_msg'].encode('utf-8')) <= 4096
    assert len(result['log_tail'].encode('utf-8')) <= 65536
    assert len(result['result_files']) <= 100
    assert len(json.dumps(result['result_files'], ensure_ascii=False).encode('utf-8')) <= 65536
    assert '结果文件列表已截断' in result['error_msg']
    assert result['error_msg'].endswith('[内容已截断]')


def test_normal_completion_is_preserved_without_inventing_an_error():
    assert bounded_execution_output(None, ['report.xlsx'], 'ok') == {
        'error_msg': None, 'result_files': ['report.xlsx'], 'log_tail': 'ok'}
