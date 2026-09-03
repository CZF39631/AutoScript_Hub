import hashlib

import pytest

from client.update.download import download_verified_file


class _Response:
    def __init__(self, chunks, *, status=200, headers=None, fail_after=False):
        self.chunks = list(chunks)
        self.status = status
        self.headers = headers or {}
        self.fail_after = fail_after

    def read(self, _size):
        if self.chunks:
            return self.chunks.pop(0)
        if self.fail_after:
            self.fail_after = False
            raise OSError("connection reset")
        return b""

    def close(self):
        pass


class _Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return next(self.responses)


def _header(request, name):
    return next((value for key, value in request.header_items() if key.lower() == name.lower()), None)


def test_interrupted_part_resumes_only_with_strong_etag_and_exact_range(tmp_path):
    payload = b"abcdef"
    opener = _Opener([
        _Response([b"abc"], headers={"ETag": '"release-1"'}, fail_after=True),
        _Response(
            [b"def"],
            status=206,
            headers={
                "ETag": '"release-1"',
                "Content-Range": "bytes 3-5/6",
                "Content-Length": "3",
            },
        ),
    ])
    destination = tmp_path / "part0001"

    download_verified_file(
        "https://example.com/part0001",
        destination,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        opener=opener,
        retry_delay=0,
    )

    assert destination.read_bytes() == payload
    assert _header(opener.requests[1], "Range") == "bytes=3-"
    assert _header(opener.requests[1], "If-Range") == '"release-1"'


def test_weak_etag_partial_is_discarded_and_restarted(tmp_path):
    payload = b"abcdef"
    opener = _Opener([
        _Response([b"abc"], headers={"ETag": 'W/"release-1"'}, fail_after=True),
        _Response([payload], headers={"ETag": '"release-1"'}),
    ])
    destination = tmp_path / "part0001"

    download_verified_file(
        "https://example.com/part0001",
        destination,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        opener=opener,
        retry_delay=0,
    )

    assert destination.read_bytes() == payload
    assert _header(opener.requests[1], "Range") is None


def test_failed_full_download_never_replaces_existing_destination(tmp_path):
    payload = b"expected"
    opener = _Opener([_Response([b"wrong"]) for _ in range(3)])
    destination = tmp_path / "installer.exe"
    destination.write_bytes(b"previous")

    with pytest.raises(RuntimeError, match="已重试 3 次"):
        download_verified_file(
            "https://example.com/installer.exe",
            destination,
            len(payload),
            hashlib.sha256(payload).hexdigest(),
            opener=opener,
            retry_delay=0,
        )

    assert destination.read_bytes() == b"previous"
    assert not (tmp_path / "installer.exe.download").exists()


def test_mismatched_content_range_discards_partial_before_full_retry(tmp_path):
    payload = b"abcdef"
    opener = _Opener([
        _Response([b"abc"], headers={"ETag": '"release-1"'}, fail_after=True),
        _Response(
            [b"def"],
            status=206,
            headers={
                "ETag": '"release-1"',
                "Content-Range": "bytes 2-5/6",
                "Content-Length": "4",
            },
        ),
        _Response([payload], headers={"ETag": '"release-1"'}),
    ])
    destination = tmp_path / "part0001"

    download_verified_file(
        "https://example.com/part0001",
        destination,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        opener=opener,
        retry_delay=0,
    )

    assert destination.read_bytes() == payload
    assert _header(opener.requests[1], "Range") == "bytes=3-"
    assert _header(opener.requests[2], "Range") is None
