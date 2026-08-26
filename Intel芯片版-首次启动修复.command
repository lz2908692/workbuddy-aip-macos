#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$SCRIPT_DIR/WorkBuddy第三方AIP对接工具-Intel芯片.app"
BIN="$APP/Contents/MacOS/WorkBuddy第三方AIP对接工具-Intel芯片"

if [[ ! -d "$APP" ]]; then
  osascript -e 'display alert "未找到应用" message "请把首次启动修复.command 与 WorkBuddy 第三方 AIP 对接工具放在同一个文件夹中。" as critical'
  exit 1
fi

if [[ "$(uname -m)" != "x86_64" ]]; then
  osascript -e 'display alert "芯片版本不匹配" message "此版本仅适用于 Intel Mac。M1/M2/M3/M4 请使用 M 芯片版。" as critical'
  exit 1
fi

chmod 755 "$BIN"
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true
codesign --force --deep --sign - "$APP"

if ! codesign --verify --deep --strict "$APP" 2>/dev/null; then
  osascript -e 'display alert "应用修复失败" message "请重新下载完整 ZIP，使用系统自带归档实用工具解压后再试。" as critical'
  exit 1
fi

osascript -e 'display dialog "执行权限、隔离标记和应用签名已修复。现在可以启动 WorkBuddy 工具；如系统仍拦截，请在应用右上角点击“隐私设置”。" buttons {"启动应用"} default button "启动应用" with title "WorkBuddy 中转站工具 V1.24" with icon note'
open "$APP"
osascript -e 'display notification "已修复执行权限并启动应用" with title "WorkBuddy 中转站工具 V1.24"'
