"""HTTP header helpers."""

from urllib.parse import unquote

from api.http_headers import content_disposition_attachment


def _assert_latin1_encodable(headers: dict[str, str]) -> None:
    for key, value in headers.items():
        key.encode("latin-1")
        value.encode("latin-1")


def test_content_disposition_attachment_ascii_only():
    headers = content_disposition_attachment("ExportMe.yaml")
    assert 'filename="ExportMe.yaml"' in headers["Content-Disposition"]
    _assert_latin1_encodable(headers)


def test_content_disposition_attachment_unicode_filename():
    name = "Kịch bản thử nghiệm.yaml"
    headers = content_disposition_attachment(name)
    value = headers["Content-Disposition"]
    assert value.startswith('attachment; filename="')
    encoded = value.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == name
    _assert_latin1_encodable(headers)
