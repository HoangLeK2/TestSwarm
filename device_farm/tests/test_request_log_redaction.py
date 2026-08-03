from starlette.requests import Request

from web.server import RequestLogMiddleware


def _request(query: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/screenshot/device-1",
            "headers": [],
            "query_string": query.encode(),
            "server": ("testserver", 80),
            "client": ("testclient", 1234),
            "scheme": "http",
        }
    )


def test_request_log_query_redacts_credentials_and_preserves_regular_params() -> None:
    query = RequestLogMiddleware._safe_query(
        _request(
            "token=jwt-value&pair=pair-id&secret=s3cr3t&key=device-key"
            "&device_control_key=control-key&max_width=360&tag=one&tag=two"
        )
    )

    assert "jwt-value" not in query
    assert "pair-id" not in query
    assert "s3cr3t" not in query
    assert "device-key" not in query
    assert "control-key" not in query
    assert query.count("%3CREDACTED%3E") == 5
    assert "max_width=360" in query
    assert query.endswith("tag=one&tag=two")
