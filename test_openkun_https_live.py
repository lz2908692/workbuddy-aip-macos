#!/usr/bin/env python3
"""Live OpenKun /models smoke test without exposing the local API key."""

import importlib.machinery
import importlib.util
import json
import sys
import types
from pathlib import Path

SOURCE = Path(__file__).with_name("workbuddy_aip.pyw")
CONFIG = Path.home() / ".workbuddy" / "workbuddy-aip" / "providers.json"


def load_module():
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


def main():
    providers = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    provider = next(
        (
            item
            for item in providers
            if str(item.get("key", "")).lower() == "openkun"
            or str(item.get("name", "")).lower() == "openkun"
        ),
        None,
    )
    if not provider:
        raise RuntimeError("本机配置中未找到 OpenKun")
    module = load_module()
    stored_secret = provider.get("api_key", "")
    api_key = module.unprotect_secret(stored_secret) if stored_secret.startswith(
        (module.SECRET_PREFIX, module.KEYCHAIN_PREFIX)
    ) else stored_secret
    print("api_key_status=%s" % module.api_key_status(api_key))
    models = module.fetch_models(provider["base_url"], api_key, timeout=20)
    print("OPENKUN_HTTPS_OK")
    print("base_url=%s" % provider["base_url"])
    print("model_count=%d" % len(models))
    print("default_model_found=%s" % (provider.get("model") in models))


if __name__ == "__main__":
    main()
