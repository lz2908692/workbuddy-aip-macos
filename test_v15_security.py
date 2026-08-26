#!/usr/bin/env python3
"""WorkBuddy AIP v1.5 credential and migration regression tests."""

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
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
    loader = importlib.machinery.SourceFileLoader("workbuddy_aip_v15", str(SOURCE))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main():
    module = load_module()
    assert module.APP_VERSION == "1.21"

    with tempfile.TemporaryDirectory(prefix="workbuddy-aip-v15-") as temp_dir:
        module.DATA_DIR = temp_dir
        module.PROVIDERS_FILE = os.path.join(temp_dir, "providers.json")
        module.BACKUP_DIR = os.path.join(temp_dir, "backups")
        module.EXPORT_DIR = os.path.join(temp_dir, "exports")
        provider = {
            "key": "openkun",
            "name": "OpenKun",
            "base_url": "https://openkun.xyz/v1",
            "wire_api": "responses",
            "api_key": "plain-secret",
            "models": ["gpt-test"],
            "model": "gpt-test",
            "notes": "",
            "active": True,
        }
        Path(module.PROVIDERS_FILE).write_text(json.dumps([provider]), encoding="utf-8")

        if sys.platform.startswith("win"):
            loaded = module.load_providers()
            assert loaded[0]["api_key"] == "plain-secret"
            stored = Path(module.PROVIDERS_FILE).read_text(encoding="utf-8")
            assert "plain-secret" not in stored
            assert module.SECRET_PREFIX in stored
            assert list(Path(module.BACKUP_DIR).glob("providers-*.json"))

            module.save_providers(loaded)
            reloaded = module.load_providers()
            assert reloaded[0]["api_key"] == "plain-secret"

        with patch.object(module.sys, "platform", "darwin"), patch.object(module.subprocess, "run") as run:
            run.return_value.stdout = "plain-secret\n"
            reference = module.protect_secret("plain-secret", "duplicate-0")
            assert reference.startswith(module.KEYCHAIN_PREFIX)
            args, kwargs = run.call_args
            assert args[0] == ["security", "-i"]
            assert "plain-secret" not in args[0]
            assert "plain-secret" in kwargs["input"]
            assert module.unprotect_secret(reference) == "plain-secret"

        safe_export = module.build_export(provider)
        assert safe_export["provider"]["api_key"] == ""
        assert safe_export["provider"]["api_key_included"] is False
        unsafe_export = module.build_export(provider, include_api_key=True)
        assert unsafe_export["provider"]["api_key"] == "plain-secret"

        module.validate_remote_url("https://openkun.xyz/v1")
        module.validate_remote_url("http://localhost:8080/v1")
        for url in ("http://openkun.xyz/v1", "https://user:pass@openkun.xyz/v1", "file:///tmp/models"):
            try:
                module.validate_remote_url(url)
            except ValueError:
                pass
            else:
                raise AssertionError("unsafe URL accepted: %s" % url)

        class LargeResponse:
            headers = {"Content-Length": str(module.MAX_RESPONSE_BYTES + 1)}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        class FakeOpener:
            def open(self, *_args, **_kwargs):
                return LargeResponse()

        with patch.object(module.urllib.request, "build_opener", return_value=FakeOpener()):
            try:
                module.request_json("https://example.com/v1/models", "")
            except ValueError as error:
                assert "8 MB" in str(error)
            else:
                raise AssertionError("oversized response accepted")

    print("V15_SECURITY_OK")
    print("version=%s" % module.APP_VERSION)


if __name__ == "__main__":
    main()
