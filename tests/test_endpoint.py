# Copyright (c) 2026 Shashikanth Dhanekula
# SPDX-License-Identifier: MIT
"""Tests for secure endpoint validation."""

from __future__ import annotations

import pytest

from dgx_lab.endpoint import (
    EndpointError,
    assert_loopback_bind,
    is_loopback_host,
    redact_secrets,
    validate_endpoint,
)


def test_loopback_http_ok():
    ep = validate_endpoint("http://127.0.0.1:8000", token="secret")
    assert ep.is_loopback
    assert ep.scheme == "http"


def test_localhost_and_ipv6_loopback():
    assert validate_endpoint("http://localhost:8000/v1", token="t").is_loopback
    assert validate_endpoint("http://[::1]:8000", token="t").is_loopback


def test_remote_requires_https_and_token():
    with pytest.raises(EndpointError, match="https"):
        validate_endpoint("http://cluster.example:8000", token="t")
    with pytest.raises(EndpointError, match="token"):
        validate_endpoint("https://cluster.example/v1", token="")
    ep = validate_endpoint("https://cluster.example/v1", token="t")
    assert not ep.is_loopback
    assert ep.scheme == "https"


def test_rejects_userinfo_and_wildcard():
    with pytest.raises(EndpointError, match="credentials"):
        validate_endpoint("https://user:pass@cluster.example/v1", token="t")
    with pytest.raises(EndpointError, match="wildcard"):
        validate_endpoint("http://0.0.0.0:8000", token="t")


def test_assert_loopback_bind_opt_in():
    assert_loopback_bind("127.0.0.1")
    with pytest.raises(EndpointError):
        assert_loopback_bind("10.0.0.5")
    assert_loopback_bind("10.0.0.5", allow_non_loopback=True)
    with pytest.raises(EndpointError, match="wildcard"):
        assert_loopback_bind("0.0.0.0", allow_non_loopback=True)


def test_is_loopback_and_redact():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert not is_loopback_host("example.com")
    assert redact_secrets("token=abc123", "abc123") == "token=***"
