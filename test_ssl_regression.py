#!/usr/bin/env python3
"""Regression checks for WorkBuddy AIP strict TLS handling."""

import importlib.machinery
import importlib.util
import json
import os
import ssl
import sys
import types
from pathlib import Path
from unittest.mock import patch

SOURCE = Path(__file__).with_name("workbuddy_aip.pyw")


def load_module():
    if "tkinter" not in sys.modules:
        tkinter = types.ModuleType("tkinter")
        tkinter.filedialog = types.ModuleType("filedialog")
        tkinter.messagebox = types.ModuleType("messagebox")
        tkinter.simpledialog = types.ModuleType("simpledialog")
        tkinter.ttk = types.ModuleType("ttk")
        sys.modules["tkinter"] = tkinter
        sys.modules["tkinter.filedialog"] = tkinter.filedialog
        sys.modules["tkinter.messagebox"] = tkinter.messagebox
        sys.modules["tkinter.simpledialog"] = tkinter.simpledialog
        sys.modules["tkinter.ttk"] = tkinter.ttk
    loader = importlib.machinery.SourceFileLoader("workbuddy_aip", str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        return False

    def read(self):
        return json.dumps({"data": [{"id": "gpt-test"}]}).encode("utf-8")


def main():
    module = load_module()
    context = module.create_ssl_context()
    assert module.APP_VERSION == "1.4"
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert os.path.isfile(module.certifi.where())
    assert os.path.getsize(module.certifi.where()) > 0

    calls = []

    class FakeOpener:
        def open(self, request, timeout):
            calls.append((request, timeout))
            return FakeResponse()

    captured_handlers = []

    def fake_build_opener(*handlers):
        captured_handlers.extend(handlers)
        return FakeOpener()

    with patch.object(module.urllib.request, "build_opener", side_effect=fake_build_opener):
        data = module.request_json("https://openkun.xyz/v1/models", "secret", timeout=7)

    assert data["data"][0]["id"] == "gpt-test"
    request, timeout = calls[0]
    assert request.full_url == "https://openkun.xyz/v1/models"
    assert request.get_header("Authorization") == "Bearer secret"
    assert timeout == 7
    https_handler = next(item for item in captured_handlers if isinstance(item, module.urllib.request.HTTPSHandler))
    request_context = https_handler._context
    assert request_context.verify_mode == ssl.CERT_REQUIRED
    assert request_context.check_hostname is True

    redirect = module.SafeRedirectHandler()
    original = module.urllib.request.Request(
        "https://openkun.xyz/v1/models",
        headers={"Authorization": "Bearer secret"},
    )
    same_origin = redirect.redirect_request(
        original, None, 302, "Found", {}, "https://openkun.xyz/v1/models?page=2"
    )
    assert same_origin.get_header("Authorization") == "Bearer secret"
    cross_origin = redirect.redirect_request(
        original, None, 302, "Found", {}, "https://example.com/v1/models"
    )
    assert cross_origin.get_header("Authorization") is None
    try:
        redirect.redirect_request(original, None, 302, "Found", {}, "http://openkun.xyz/v1/models")
    except module.urllib.error.URLError:
        pass
    else:
        raise AssertionError("HTTPS downgrade redirect must be rejected")

    print("SSL_REGRESSION_OK")
    print("version=%s" % module.APP_VERSION)
    print("ca_bundle=%s" % module.certifi.where())
    print("ca_bundle_bytes=%d" % os.path.getsize(module.certifi.where()))


if __name__ == "__main__":
    main()
