#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WorkBuddy Third-Party AI Provider Manager V1.23."""

import base64
import copy
import ctypes
import hashlib
import http.client
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import certifi
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

APP_NAME = "WorkBuddy 第三方 AIP 对接工具"
APP_VERSION = "1.23"
APP_SLUG = "workbuddy-aip"
WIRE_RESPONSES = "responses"
WIRE_CHAT = "chat_completions"
SECRET_PREFIX = "dpapi:"
KEYCHAIN_PREFIX = "keychain:"
KEYCHAIN_SERVICE = "com.susu.workbuddy-aip"
MAX_RESPONSE_BYTES = 8 * 1024 * 1024

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy", APP_SLUG)
PROVIDERS_FILE = os.path.join(DATA_DIR, "providers.json")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
EXPORT_DIR = os.path.join(DATA_DIR, "exports")
WORKBUDDY_MODELS_FILE = os.path.join(os.path.expanduser("~"), ".workbuddy", "models.json")
WORKBUDDY_MODELS_BACKUP_DIR = os.path.join(os.path.expanduser("~"), ".workbuddy", "model-backups")

DEFAULT_PROVIDERS = [
    {
        "key": "vakv",
        "name": "VAKV",
        "base_url": "https://api.vakv.cn/v1",
        "wire_api": WIRE_RESPONSES,
        "api_key": "",
        "models": ["gpt-5.6-terra", "gpt-5.6", "gpt-5.5"],
        "model": "gpt-5.6-terra",
        "notes": "OpenAI-compatible 中转服务",
        "active": True,
    },
    {
        "key": "aivr",
        "name": "AIVR",
        "base_url": "https://api.aivr.cc/v1",
        "wire_api": WIRE_RESPONSES,
        "api_key": "",
        "models": ["gpt-5.6", "gpt-5.5", "claude-opus-4.8"],
        "model": "gpt-5.6",
        "notes": "OpenAI-compatible 中转服务",
        "active": False,
    },
    {
        "key": "openai",
        "name": "OpenAI 官方",
        "base_url": "https://api.openai.com/v1",
        "wire_api": WIRE_RESPONSES,
        "api_key": "",
        "models": ["gpt-5.6", "gpt-5.5", "gpt-4.1"],
        "model": "gpt-5.6",
        "notes": "官方 OpenAI API",
        "active": False,
    },
]


def ensure_dirs():
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(BACKUP_DIR, exist_ok=True)
    os.makedirs(EXPORT_DIR, exist_ok=True)


def clone_defaults():
    return copy.deepcopy(DEFAULT_PROVIDERS)


def _protect_windows_secret(value):
    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    raw = value.encode("utf-8")
    buffer = ctypes.create_string_buffer(raw)
    source = DataBlob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    protected = DataBlob()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(source), None, None, None, None, 1, ctypes.byref(protected)
    ):
        raise ctypes.WinError()
    try:
        encrypted = ctypes.string_at(protected.pbData, protected.cbData)
        return SECRET_PREFIX + base64.b64encode(encrypted).decode("ascii")
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(protected.pbData, ctypes.c_void_p))


def _unprotect_windows_secret(value):
    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    encrypted = base64.b64decode(value[len(SECRET_PREFIX):], validate=True)
    buffer = ctypes.create_string_buffer(encrypted)
    source = DataBlob(len(encrypted), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    plain = DataBlob()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(plain)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(plain.pbData, plain.cbData).decode("utf-8")
    finally:
        local_free = ctypes.windll.kernel32.LocalFree
        local_free.argtypes = [ctypes.c_void_p]
        local_free.restype = ctypes.c_void_p
        local_free(ctypes.cast(plain.pbData, ctypes.c_void_p))


def _keychain_account(provider_key, value):
    digest = hashlib.sha256((provider_key + "\0" + value).encode("utf-8")).hexdigest()[:24]
    return "provider-%s-api-key" % digest


def _security_quote(value):
    value = str(value).replace("\r", "").replace("\n", "")
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def _save_macos_secret(provider_key, value):
    account = _keychain_account(provider_key, value)
    command = "add-generic-password -U -s %s -a %s -w %s\n" % (
        _security_quote(KEYCHAIN_SERVICE),
        _security_quote(account),
        _security_quote(value),
    )
    subprocess.run(
        ["security", "-i"],
        input=command,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    return KEYCHAIN_PREFIX + account


def _load_macos_secret(reference):
    account = reference[len(KEYCHAIN_PREFIX):]
    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.rstrip("\r\n")


def protect_secret(value, provider_key="provider"):
    if not value or value.startswith((SECRET_PREFIX, KEYCHAIN_PREFIX)):
        return value
    if sys.platform.startswith("win"):
        return _protect_windows_secret(value)
    if sys.platform == "darwin":
        return _save_macos_secret(provider_key, value)
    return value


def unprotect_secret(value):
    if not value or not value.startswith((SECRET_PREFIX, KEYCHAIN_PREFIX)):
        return value
    if value.startswith(KEYCHAIN_PREFIX):
        if sys.platform != "darwin":
            raise RuntimeError("该 API Key 保存在 macOS 钥匙串，只能在原 macOS 账户中读取")
        try:
            return _load_macos_secret(value)
        except Exception as error:
            raise RuntimeError("无法从 macOS 钥匙串读取 API Key，请重新输入并保存") from error
    if not sys.platform.startswith("win"):
        raise RuntimeError("该 API Key 由 Windows 用户凭据加密，只能在原 Windows 账户中解密")
    try:
        return _unprotect_windows_secret(value)
    except Exception as error:
        raise RuntimeError("API Key 无法由当前 Windows 账户解密，请恢复对应账户的配置备份") from error


def normalize_api_key(value):
    """Normalize a copied key without changing valid interior characters."""
    value = str(value or "").strip()
    while value.lower().startswith("bearer "):
        value = value[7:].strip()
    return value


def api_key_status(value):
    key = normalize_api_key(value)
    if not key:
        return "未配置"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return "已配置，长度 %d，指纹 %s…%s" % (len(key), digest[:4], digest[-4:])


def authentication_error_message(code, reason=""):
    if int(code) == 401:
        return "HTTP 401：API Key 未被服务端接受。请重新输入有效 Key，点击“保存配置”后再试。"
    if int(code) == 403:
        return "HTTP 403：API Key 已识别，但没有访问权限或账户状态受限。"
    return "HTTP %s: %s" % (code, reason or "请求失败")


def provider_for_storage(provider, index=0):
    stored = copy.deepcopy(provider)
    provider_key = "%s-%s" % (stored.get("key", "provider"), index)
    stored["api_key"] = protect_secret(normalize_api_key(stored.get("api_key", "")), provider_key)
    return stored


def load_providers():
    ensure_dirs()
    if os.path.exists(PROVIDERS_FILE):
        try:
            with open(PROVIDERS_FILE, "r", encoding="utf-8-sig") as f:
                stored = json.load(f)
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
            stored = None
        if isinstance(stored, list) and stored:
            migrated = False
            providers = []
            for item in stored:
                if not isinstance(item, dict):
                    continue
                provider = copy.deepcopy(item)
                secret = provider.get("api_key", "")
                if secret.startswith((SECRET_PREFIX, KEYCHAIN_PREFIX)):
                    provider["api_key"] = unprotect_secret(secret)
                elif secret and (sys.platform.startswith("win") or sys.platform == "darwin"):
                    migrated = True
                providers.append(provider)
            if providers:
                if migrated:
                    backup_providers()
                    save_providers(providers)
                return providers
    data = clone_defaults()
    save_providers(data)
    return data


def save_providers(providers):
    ensure_dirs()
    tmp = PROVIDERS_FILE + ".tmp"
    stored = [provider_for_storage(item, index) for index, item in enumerate(providers)]
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stored, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROVIDERS_FILE)


def key_from_name(name):
    key = "".join(ch.lower() for ch in name if ch.isalnum() or ch in "-_")
    return key or "provider"


def backup_providers():
    ensure_dirs()
    if not os.path.exists(PROVIDERS_FILE):
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, "providers-%s.json" % stamp)
    shutil.copy2(PROVIDERS_FILE, path)
    return path


def create_ssl_context():
    """Create a strict TLS context backed by certifi's Mozilla CA bundle."""
    ca_bundle = certifi.where()
    if not ca_bundle or not os.path.isfile(ca_bundle):
        raise RuntimeError("可信 CA 证书包不可用，请重新安装本工具")
    context = ssl.create_default_context(cafile=ca_bundle)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    ignore_eof = getattr(ssl, "OP_IGNORE_UNEXPECTED_EOF", 0)
    if ignore_eof:
        context.options |= ignore_eof
    return context


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Prevent API credentials from leaking through unsafe redirects."""

    def redirect_request(self, request, fp, code, message, headers, new_url):
        redirected = super().redirect_request(request, fp, code, message, headers, new_url)
        if redirected is None:
            return None
        old_parts = urllib.parse.urlsplit(request.full_url)
        try:
            new_parts = validate_remote_url(new_url)
        except ValueError as error:
            raise urllib.error.URLError(str(error)) from error
        if old_parts.scheme == "https" and new_parts.scheme != "https":
            raise urllib.error.URLError("拒绝 HTTPS 降级重定向")
        if (old_parts.scheme, old_parts.netloc) != (new_parts.scheme, new_parts.netloc):
            redirected.remove_header("Authorization")
        return redirected


def validate_remote_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("API URL 必须是有效的 HTTP(S) 地址")
    hostname = parts.hostname.lower()
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parts.scheme != "https" and hostname not in local_hosts:
        raise ValueError("远程 API 必须使用 HTTPS；HTTP 仅允许 localhost 本地服务")
    if parts.username or parts.password:
        raise ValueError("API URL 不允许包含用户名或密码")
    return parts


def _is_unexpected_tls_eof(error):
    current = error
    while current is not None:
        text = str(current).upper()
        if "UNEXPECTED_EOF_WHILE_READING" in text or "EOF OCCURRED IN VIOLATION OF PROTOCOL" in text:
            return True
        current = getattr(current, "reason", None) or getattr(current, "__cause__", None)
    return False


def _curl_config_quote(value):
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"').replace("\r", "").replace("\n", "")


def _request_json_with_macos_curl(url, api_key, timeout):
    validate_remote_url(url)
    api_key = normalize_api_key(api_key)
    fd, output_path = tempfile.mkstemp(prefix="workbuddy-aip-", suffix=".json")
    os.close(fd)
    config_lines = [
        "silent",
        "show-error",
        "fail",
        "proto = \"=https\"",
        "proto-redir = \"=https\"",
        "location",
        "max-redirs = 5",
        "connect-timeout = %d" % max(1, min(int(timeout), 20)),
        "max-time = %d" % max(1, int(timeout)),
        "max-filesize = %d" % MAX_RESPONSE_BYTES,
        "output = %s" % _curl_config_quote(output_path),
        "write-out = %s" % _curl_config_quote("%{http_code}"),
        "header = %s" % _curl_config_quote("Accept: application/json"),
    ]
    if api_key:
        config_lines.append("header = %s" % _curl_config_quote("Authorization: Bearer %s" % api_key))
    config_lines.append("url = %s" % _curl_config_quote(url))
    config = ("\n".join(config_lines) + "\n").encode("utf-8")
    try:
        try:
            result = subprocess.run(
                ["/usr/bin/curl", "-q", "--config", "-"],
                input=config,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout + 5,
            )
        except subprocess.CalledProcessError as error:
            detail = error.stderr.decode("utf-8", errors="replace").strip()
            if api_key:
                detail = detail.replace(api_key, "***")
            status_text = (error.stdout or b"").decode("ascii", errors="ignore").strip()
            if status_text.isdigit() and int(status_text) >= 400:
                raise urllib.error.HTTPError(
                    url, int(status_text), http.client.responses.get(int(status_text), detail or "HTTP error"), {}, None
                ) from error
            raise urllib.error.URLError("macOS 系统网络请求失败: %s" % (detail or "curl exit %s" % error.returncode)) from error
        except subprocess.TimeoutExpired as error:
            raise urllib.error.URLError("macOS 系统网络请求超时") from error
        if os.path.getsize(output_path) > MAX_RESPONSE_BYTES:
            raise ValueError("API 响应超过 8 MB 安全上限")
        with open(output_path, "rb") as response_file:
            raw_bytes = response_file.read(MAX_RESPONSE_BYTES + 1)
        if len(raw_bytes) > MAX_RESPONSE_BYTES:
            raise ValueError("API 响应超过 8 MB 安全上限")
        return json.loads(raw_bytes.decode("utf-8-sig"))
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def request_json(url, api_key, timeout=20):
    validate_remote_url(url)
    api_key = normalize_api_key(api_key)
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer %s" % api_key
    req = urllib.request.Request(url, headers=headers)
    handlers = [SafeRedirectHandler()]
    if url.lower().startswith("https://"):
        handlers.append(urllib.request.HTTPSHandler(context=create_ssl_context()))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(req, timeout=timeout) as response:
            declared_length = response.headers.get("Content-Length")
            if declared_length and int(declared_length) > MAX_RESPONSE_BYTES:
                raise ValueError("API 响应超过 8 MB 安全上限")
            raw_bytes = response.read(MAX_RESPONSE_BYTES + 1)
    except Exception as error:
        if sys.platform == "darwin" and url.lower().startswith("https://") and _is_unexpected_tls_eof(error):
            return _request_json_with_macos_curl(url, api_key, timeout)
        raise
    if len(raw_bytes) > MAX_RESPONSE_BYTES:
        raise ValueError("API 响应超过 8 MB 安全上限")
    return json.loads(raw_bytes.decode("utf-8-sig"))


def fetch_models(base_url, api_key, timeout=20):
    api_key = normalize_api_key(api_key)
    if not api_key:
        raise ValueError("未配置 API Key。请在供应商信息中输入 Key，点击“保存配置”后再试。")
    data = request_json(base_url.rstrip("/") + "/models", api_key, timeout)
    return [item["id"] for item in data.get("data", []) if item.get("id")]


def open_macos_privacy_settings():
    if sys.platform != "darwin":
        raise RuntimeError("隐私设置入口仅适用于 macOS")
    urls = [
        "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension",
        "x-apple.systempreferences:com.apple.preference.security?General",
    ]
    last_error = None
    for url in urls:
        try:
            subprocess.run(["open", url], check=True)
            return url
        except (OSError, subprocess.CalledProcessError) as error:
            last_error = error
    raise RuntimeError("无法自动打开隐私与安全性设置") from last_error


def build_export(provider, include_api_key=False):
    env_name = "%s_API_KEY" % provider["key"].upper()
    return {
        "app": "WorkBuddy",
        "format": "openai-compatible",
        "provider": {
            "id": provider["key"],
            "name": provider["name"],
            "base_url": provider["base_url"].rstrip("/"),
            "wire_api": provider["wire_api"],
            "model": provider["model"],
            "api_key_env": env_name,
            "api_key": provider.get("api_key", "") if include_api_key else "",
            "api_key_included": bool(include_api_key and provider.get("api_key")),
            "notes": provider.get("notes", ""),
        },
        "usage": {
            "endpoint_models": provider["base_url"].rstrip("/") + "/models",
            "endpoint_responses": provider["base_url"].rstrip("/") + "/responses",
            "endpoint_chat_completions": provider["base_url"].rstrip("/") + "/chat/completions",
        },
    }


def export_provider(provider, path=None, include_api_key=False):
    ensure_dirs()
    if not path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        path = os.path.join(EXPORT_DIR, "%s-%s.json" % (provider["key"], stamp))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(build_export(provider, include_api_key), f, ensure_ascii=False, indent=2)
    return path


def load_workbuddy_models():
    if not os.path.exists(WORKBUDDY_MODELS_FILE):
        return []
    try:
        with open(WORKBUDDY_MODELS_FILE, "r", encoding="utf-8-sig") as f:
            raw = f.read().strip()
        if not raw:
            return []
        models = json.loads(raw)
        if not isinstance(models, list):
            raise ValueError("WorkBuddy models.json 根节点不是数组")
        return models
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise InvalidWorkBuddyModels(str(error)) from error


class InvalidWorkBuddyModels(ValueError):
    pass


def backup_workbuddy_models(suffix=""):
    if not os.path.exists(WORKBUDDY_MODELS_FILE):
        return None
    os.makedirs(WORKBUDDY_MODELS_BACKUP_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(WORKBUDDY_MODELS_BACKUP_DIR, "models-%s%s.json" % (stamp, suffix))
    shutil.copy2(WORKBUDDY_MODELS_FILE, path)
    return path


def write_workbuddy_models(models):
    os.makedirs(os.path.dirname(WORKBUDDY_MODELS_FILE), exist_ok=True)
    temp_path = WORKBUDDY_MODELS_FILE + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(models, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, WORKBUDDY_MODELS_FILE)


def to_workbuddy_model(provider, model_id):
    return {
        "id": model_id,
        "name": model_id,
        "vendor": "Custom",
        "url": provider["base_url"].rstrip("/"),
        "apiKey": provider.get("api_key", ""),
        "supportsToolCall": True,
        "supportsImages": True,
        "supportsReasoning": True,
        "useCustomProtocol": False,
    }


def merge_workbuddy_models(provider, model_ids):
    invalid_backup = None
    try:
        existing = load_workbuddy_models()
    except InvalidWorkBuddyModels:
        invalid_backup = backup_workbuddy_models("-invalid")
        existing = []
    backup = backup_workbuddy_models()
    by_id = {item.get("id"): index for index, item in enumerate(existing) if isinstance(item, dict) and item.get("id")}
    added = 0
    updated = 0
    seen_ids = set()
    for model_id in model_ids:
        if not model_id or model_id in seen_ids:
            continue
        seen_ids.add(model_id)
        item = to_workbuddy_model(provider, model_id)
        if model_id in by_id:
            existing[by_id[model_id]] = item
            updated += 1
        else:
            by_id[model_id] = len(existing)
            existing.append(item)
            added += 1
    write_workbuddy_models(existing)
    return added, updated, len(existing), invalid_backup or backup


class App:
    def __init__(self, root):
        self.root = root
        self.providers = load_providers()
        self.selected_key = None
        self.busy = False
        self.font = "Microsoft YaHei UI"

        root.title("%s v%s" % (APP_NAME, APP_VERSION))
        root.geometry("980x680")
        root.minsize(860, 580)
        root.configure(bg="#f4f6f9")
        self.setup_style()
        self.build_ui()
        self.refresh_list()
        self.log("已加载 %d 个供应商配置" % len(self.providers))
        self.log("配置保存位置: %s" % PROVIDERS_FILE)
        if sys.platform == "darwin":
            self.root.after(500, self.show_macos_privacy_prompt)

    def setup_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f4f6f9")
        style.configure("TLabel", background="#f4f6f9", foreground="#1f2937", font=(self.font, 9))
        style.configure("Section.TLabel", background="#f4f6f9", foreground="#14304d", font=(self.font, 11, "bold"))
        style.configure("Title.TLabel", background="#14304d", foreground="white", font=(self.font, 14, "bold"))
        style.configure("SubTitle.TLabel", background="#14304d", foreground="#c9dcf5", font=(self.font, 9))
        style.configure("Primary.TButton", font=(self.font, 10, "bold"))
        style.configure("TButton", font=(self.font, 9))

    def build_ui(self):
        header = tk.Frame(self.root, bg="#14304d", height=74)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="SS", bg="#2860e1", fg="white", font=("Arial", 18, "bold"),
                 width=3, height=1).pack(side="left", padx=(18, 10), pady=15)
        titlebox = tk.Frame(header, bg="#14304d")
        titlebox.pack(side="left", pady=13)
        ttk.Label(titlebox, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(titlebox, text="OpenAI-compatible 第三方 AI API 配置与连通性管理", style="SubTitle.TLabel").pack(anchor="w")
        ttk.Button(header, text="刷新状态", command=self.refresh_status).pack(side="right", padx=(8, 18), pady=22)
        if sys.platform == "darwin":
            ttk.Button(header, text="隐私设置", command=self.open_privacy_settings).pack(side="right", padx=0, pady=22)

        body = tk.Frame(self.root, bg="#f4f6f9")
        body.pack(fill="both", expand=True, padx=16, pady=14)

        left = tk.Frame(body, bg="#f4f6f9", width=220)
        left.pack(side="left", fill="y", padx=(0, 14))
        left.pack_propagate(False)
        ttk.Label(left, text="供应商配置", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        self.listbox = tk.Listbox(left, font=(self.font, 10), bg="white", fg="#1f2937",
                                  selectbackground="#2860e1", selectforeground="white",
                                  activestyle="none", bd=1, relief="solid")
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        list_ops = tk.Frame(left, bg="#f4f6f9")
        list_ops.pack(fill="x", pady=(10, 0))
        ttk.Button(list_ops, text="添加", command=self.add_provider).pack(side="left", fill="x", expand=True)
        ttk.Button(list_ops, text="删除", command=self.delete_provider).pack(side="left", fill="x", expand=True, padx=(6, 0))

        right = tk.Frame(body, bg="#f4f6f9")
        right.pack(side="left", fill="both", expand=True)
        ttk.Label(right, text="第三方 AIP 连接参数", style="Section.TLabel").pack(anchor="w", pady=(0, 8))

        form = tk.LabelFrame(right, text=" 供应商信息 ", font=(self.font, 10, "bold"),
                             fg="#14304d", bg="#f4f6f9", padx=14, pady=12)
        form.pack(fill="x")
        self.vars = {key: tk.StringVar() for key in ("name", "base_url", "api_key", "model", "notes")}
        rows = [("name", "显示名称"), ("base_url", "API Base URL"), ("api_key", "API Key"), ("model", "默认模型"), ("notes", "备注")]
        for row, (key, label) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=5)
            entry = ttk.Entry(form, textvariable=self.vars[key], show="*" if key == "api_key" else "")
            entry.grid(row=row, column=1, sticky="ew", padx=8, pady=5)
            if key == "api_key":
                self.show_key_var = tk.BooleanVar(value=False)
                ttk.Checkbutton(form, text="显示", variable=self.show_key_var,
                                command=lambda e=entry: e.configure(show="" if self.show_key_var.get() else "*")).grid(row=row, column=2, sticky="w")
            if key == "model":
                self.model_combo = ttk.Combobox(form, textvariable=self.vars[key])
                self.model_combo.grid(row=row, column=1, sticky="ew", padx=8, pady=5)
                ttk.Button(form, text="拉取模型", command=self.fetch_models_async).grid(row=row, column=2, sticky="w")
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="接口协议").grid(row=5, column=0, sticky="w", pady=5)
        self.wire_var = tk.StringVar(value=WIRE_RESPONSES)
        ttk.Radiobutton(form, text="Responses API", value=WIRE_RESPONSES, variable=self.wire_var).grid(row=5, column=1, sticky="w", padx=8)
        ttk.Radiobutton(form, text="Chat Completions", value=WIRE_CHAT, variable=self.wire_var).grid(row=5, column=2, sticky="w")

        actions = tk.Frame(right, bg="#f4f6f9")
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text="保存配置", style="Primary.TButton", command=self.save_current).pack(side="left")
        ttk.Button(actions, text="设为当前", command=self.activate_current).pack(side="left", padx=8)
        ttk.Button(actions, text="测试连接", command=self.test_connection_async).pack(side="left")
        ttk.Button(actions, text="批量配置到 WorkBuddy", command=self.import_all_models_to_workbuddy).pack(side="left", padx=8)
        ttk.Button(actions, text="导出 JSON", command=self.export_current).pack(side="left")
        ttk.Button(actions, text="备份 / 恢复", command=self.manage_backups).pack(side="left", padx=8)

        logframe = tk.LabelFrame(right, text=" 运行日志 ", font=(self.font, 10, "bold"),
                                 fg="#14304d", bg="#f4f6f9")
        logframe.pack(fill="both", expand=True)
        self.log_text = tk.Text(logframe, font=("Consolas", 9), bg="#fbfcfe", fg="#334155",
                                bd=1, relief="solid", state="disabled", wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    def current_provider(self):
        if self.selected_key is None and self.providers:
            self.selected_key = self.providers[0]["key"]
        return next((item for item in self.providers if item.get("key") == self.selected_key), None)

    def refresh_list(self):
        self.listbox.delete(0, "end")
        for item in self.providers:
            marker = "● " if item.get("active") else "○ "
            self.listbox.insert("end", marker + item.get("name", item.get("key", "provider")))
        if not self.providers:
            return
        index = next((i for i, item in enumerate(self.providers) if item.get("key") == self.selected_key), 0)
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self.on_select()

    def on_select(self, _event=None):
        selection = self.listbox.curselection()
        if not selection:
            return
        item = self.providers[selection[0]]
        self.selected_key = item["key"]
        for key in self.vars:
            self.vars[key].set(item.get(key, ""))
        self.wire_var.set(item.get("wire_api", WIRE_RESPONSES))
        self.model_combo["values"] = item.get("models", [])

    def collect_current(self):
        item = self.current_provider()
        if not item:
            return None
        for key in self.vars:
            item[key] = self.vars[key].get().strip()
        item["api_key"] = normalize_api_key(item.get("api_key", ""))
        self.vars["api_key"].set(item["api_key"])
        item["wire_api"] = self.wire_var.get()
        values = list(self.model_combo["values"])
        if item["model"] and item["model"] not in values:
            values.append(item["model"])
        item["models"] = values
        return item

    def validate(self, item):
        if not item:
            messagebox.showwarning("提示", "请先选择供应商")
            return False
        if not item["name"] or not item["base_url"] or not item["model"]:
            messagebox.showwarning("提示", "显示名称、API Base URL、默认模型均为必填")
            return False
        try:
            validate_remote_url(item["base_url"])
        except ValueError as error:
            messagebox.showwarning("提示", str(error))
            return False
        return True

    def save_current(self):
        item = self.collect_current()
        if not self.validate(item):
            return
        backup = backup_providers()
        try:
            save_providers(self.providers)
        except Exception as error:
            self.log("配置保存失败：%s" % error)
            messagebox.showerror("保存失败", "API Key 未能安全写入系统凭据存储：\n%s" % error)
            return
        self.refresh_list()
        self.log("已保存「%s」配置%s；API Key：%s" % (
            item["name"], "，旧配置已备份" if backup else "", api_key_status(item.get("api_key"))
        ))

    def activate_current(self):
        item = self.collect_current()
        if not self.validate(item):
            return
        backup = backup_providers()
        for provider in self.providers:
            provider["active"] = provider["key"] == item["key"]
        save_providers(self.providers)
        self.refresh_list()
        self.log("已将「%s」设为当前供应商%s" % (item["name"], "，旧配置已备份" if backup else ""))

    def add_provider(self):
        name = simpledialog.askstring("添加供应商", "供应商显示名称：", parent=self.root)
        if not name:
            return
        key = key_from_name(name.strip())
        while any(item["key"] == key for item in self.providers):
            key += "_new"
        self.providers.append({
            "key": key, "name": name.strip(), "base_url": "https://api.openai.com/v1",
            "wire_api": WIRE_RESPONSES, "api_key": "", "models": [], "model": "",
            "notes": "", "active": False,
        })
        self.selected_key = key
        save_providers(self.providers)
        self.refresh_list()
        self.log("已添加「%s」" % name.strip())

    def delete_provider(self):
        item = self.current_provider()
        if not item:
            return
        if not messagebox.askyesno("删除供应商", "确定删除「%s」吗？" % item["name"]):
            return
        if len(self.providers) == 1:
            messagebox.showwarning("提示", "至少保留一个供应商")
            return
        self.providers = [provider for provider in self.providers if provider["key"] != item["key"]]
        self.selected_key = self.providers[0]["key"]
        save_providers(self.providers)
        self.refresh_list()
        self.log("已删除「%s」" % item["name"])

    def fetch_models_async(self):
        item = self.collect_current()
        if not item or not item["base_url"]:
            messagebox.showwarning("提示", "请先填写 API Base URL")
            return
        if not item.get("api_key"):
            self.log("模型拉取已停止：未配置 API Key")
            messagebox.showwarning("缺少 API Key", "请先输入 API Key 并点击“保存配置”，再拉取模型。")
            return
        self.log("正在请求 %s/models ...（API Key：%s）" % (item["base_url"], api_key_status(item["api_key"])))
        threading.Thread(
            target=self._fetch_models_worker,
            args=(item["key"], item["base_url"], item["api_key"]),
            daemon=True,
        ).start()

    def _fetch_models_worker(self, provider_key, base_url, api_key):
        try:
            models = fetch_models(base_url, api_key)
        except urllib.error.HTTPError as error:
            self.log("模型拉取失败：%s" % authentication_error_message(error.code, error.reason))
            return
        except Exception as error:
            self.log("模型拉取失败: %s" % error)
            return
        self.root.after(0, lambda: self.apply_models(provider_key, models))

    def apply_models(self, provider_key, models):
        item = next((provider for provider in self.providers if provider.get("key") == provider_key), None)
        if not item:
            self.log("模型拉取结果已丢弃：供应商已删除")
            return
        item["models"] = models
        save_providers(self.providers)
        if self.selected_key == provider_key:
            self.model_combo["values"] = models
            if models and not self.vars["model"].get():
                self.vars["model"].set(models[0])
        self.log("「%s」模型拉取成功，共 %d 个" % (item.get("name", provider_key), len(models)))

    def import_all_models_to_workbuddy(self):
        item = self.collect_current()
        if not self.validate(item):
            return
        model_ids = []
        for model_id in item.get("models", []):
            if model_id and model_id not in model_ids:
                model_ids.append(model_id)
        if item["model"] and item["model"] not in model_ids:
            model_ids.append(item["model"])
        if not model_ids:
            messagebox.showwarning("提示", "请先点击“拉取模型”，再批量配置到 WorkBuddy")
            return
        prompt = (
            "将把 %d 个模型写入 WorkBuddy：\n\n%s\n\n"
            "同 ID 模型会更新为当前供应商地址和 Key，其他已有模型会保留。\n"
            "写入前会自动备份 models.json。完成后请重启 WorkBuddy。"
        ) % (len(model_ids), "、".join(model_ids[:8]) + (" 等" if len(model_ids) > 8 else ""))
        if not messagebox.askyesno("批量配置到 WorkBuddy", prompt):
            return
        try:
            added, updated, total, backup = merge_workbuddy_models(item, model_ids)
        except Exception as error:
            messagebox.showerror("写入失败", str(error))
            self.log("批量写入 WorkBuddy 失败: %s" % error)
            return
        details = "新增 %d 个，更新 %d 个，WorkBuddy 共 %d 个模型" % (added, updated, total)
        if backup:
            details += "\n备份：%s" % backup
        self.log("已批量写入 WorkBuddy：%s" % details.replace("\n", "；"))
        messagebox.showinfo("批量配置完成", details + "\n\n请完全退出并重新打开 WorkBuddy，再到 设置 > 模型 查看。")

    def test_connection_async(self):
        item = self.collect_current()
        if not item or not item["base_url"]:
            messagebox.showwarning("提示", "请先填写 API Base URL")
            return
        if not item.get("api_key"):
            self.log("连接测试已停止：未配置 API Key")
            messagebox.showwarning("缺少 API Key", "请先输入 API Key 并点击“保存配置”，再测试连接。")
            return
        self.log("正在测试 %s ...（API Key：%s）" % (item["base_url"], api_key_status(item["api_key"])))
        threading.Thread(target=self._test_worker, args=(item["base_url"], item["api_key"]), daemon=True).start()

    def _test_worker(self, base_url, api_key):
        try:
            models = fetch_models(base_url, api_key, timeout=20)
            self.log("连接成功：/models 返回 %d 个模型" % len(models))
        except urllib.error.HTTPError as error:
            self.log("连接测试失败：%s" % authentication_error_message(error.code, error.reason))
        except Exception as error:
            self.log("连接失败: %s" % error)

    def export_current(self):
        item = self.collect_current()
        if not self.validate(item):
            return
        path = filedialog.asksaveasfilename(
            parent=self.root, title="导出 WorkBuddy AIP 配置", defaultextension=".json",
            initialfile="%s-workbuddy-aip.json" % item["key"], filetypes=[("JSON", "*.json")])
        if not path:
            return
        include_api_key = False
        if item.get("api_key"):
            include_api_key = messagebox.askyesno(
                "导出 API Key",
                "默认导出会移除 API Key，避免配置文件泄露。\n\n是否明确将 API Key 写入导出文件？",
                parent=self.root,
            )
        export_provider(item, path, include_api_key=include_api_key)
        self.log("已导出配置%s：%s" % ("（含 API Key）" if include_api_key else "（已脱敏）", path))
        messagebox.showinfo("导出完成", "配置已导出到：\n%s\n\n%s" % (
            path, "文件包含 API Key，请妥善保管。" if include_api_key else "API Key 已移除。"))

    def manage_backups(self):
        ensure_dirs()
        files = sorted((name for name in os.listdir(BACKUP_DIR) if name.endswith(".json")), reverse=True)
        if not files:
            messagebox.showinfo("备份 / 恢复", "暂无备份")
            return
        win = tk.Toplevel(self.root)
        win.title("备份 / 恢复")
        win.geometry("500x340")
        lb = tk.Listbox(win, font=("Consolas", 9))
        lb.pack(fill="both", expand=True, padx=10, pady=10)
        for name in files:
            lb.insert("end", name)

        def restore():
            selection = lb.curselection()
            if not selection:
                return
            path = os.path.join(BACKUP_DIR, files[selection[0]])
            if not messagebox.askyesno("恢复配置", "用该备份覆盖当前供应商列表？", parent=win):
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    restored = json.load(f)
                if not isinstance(restored, list) or not restored:
                    raise ValueError("备份格式无效")
                restored_runtime = []
                for stored_provider in restored:
                    if not isinstance(stored_provider, dict):
                        continue
                    provider = copy.deepcopy(stored_provider)
                    secret = provider.get("api_key", "")
                    if secret.startswith((SECRET_PREFIX, KEYCHAIN_PREFIX)):
                        provider["api_key"] = unprotect_secret(secret)
                    restored_runtime.append(provider)
                if not restored_runtime:
                    raise ValueError("备份中没有有效的供应商配置")
                save_providers(restored_runtime)
                self.providers = restored_runtime
                self.selected_key = restored_runtime[0].get("key")
                self.refresh_list()
                self.log("已恢复备份：%s" % files[selection[0]])
                win.destroy()
            except Exception as error:
                messagebox.showerror("恢复失败", str(error), parent=win)

        ttk.Button(win, text="恢复选中备份", command=restore).pack(side="left", padx=10, pady=(0, 10))
        ttk.Button(win, text="打开备份目录", command=lambda: self.open_path(BACKUP_DIR)).pack(side="left", pady=(0, 10))

    def refresh_status(self):
        item = next((provider for provider in self.providers if provider.get("active")), None)
        if item:
            self.log("当前供应商：%s / %s；API Key：%s" % (
                item.get("name"), item.get("model"), api_key_status(item.get("api_key"))
            ))
        else:
            self.log("当前未设置活动供应商")

    def show_macos_privacy_prompt(self):
        if not messagebox.askyesno(
            "macOS 隐私与安全性设置",
            "如果系统提示无法验证开发者或阻止打开，请点击“是”进入“隐私与安全性”，然后在安全性区域点击“仍要打开”。\n\n现在打开隐私设置吗？",
            parent=self.root,
        ):
            self.log("可随时点击窗口右上角“隐私设置”重新打开系统设置")
            return
        self.open_privacy_settings()

    def open_privacy_settings(self):
        try:
            open_macos_privacy_settings()
            self.log("已打开 macOS“隐私与安全性”设置")
            messagebox.showinfo(
                "隐私设置已打开",
                "请在“安全性”区域找到被拦截的应用，点击“仍要打开”，再返回重新启动工具。",
                parent=self.root,
            )
        except Exception as error:
            self.log("打开隐私设置失败: %s" % error)
            messagebox.showerror("打开失败", "%s\n\n请手动打开：系统设置 > 隐私与安全性。" % error, parent=self.root)

    def open_path(self, path):
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as error:
            messagebox.showerror("打开失败", str(error))

    def log(self, message):
        def append():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", "[%s] %s\n" % (time.strftime("%H:%M:%S"), message))
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        if threading.current_thread() is threading.main_thread():
            append()
        else:
            self.root.after(0, append)


def main():
    if "--self-test-tls" in sys.argv:
        context = create_ssl_context()
        if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
            raise RuntimeError("TLS 严格校验未启用")
        return
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
