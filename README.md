# WorkBuddy 第三方 AIP 对接工具 V1.22

本项目提供一个本地桌面配置管理器，用于管理 WorkBuddy 可使用的 OpenAI-compatible 第三方 AI API 参数。

## V1.22 macOS 网络兼容修复

- 修复 Intel/M 芯片版访问 OpenKun `/models` 时可能出现的 `UNEXPECTED_EOF_WHILE_READING`。
- 优先使用 certifi + 严格证书/主机名校验；只在该特定 TLS EOF 上回退到 macOS 系统 curl，并强制 HTTPS、隔离 `.curlrc`、限制响应为 8 MB。
- Intel/M 芯片版启动后提供“隐私与安全性”弹窗和右上角入口；首次启动修复程序也可直接打开系统设置。
- macOS 使用圆形苏苏 SS 图标，圆形外区域透明。
- Windows 使用当前用户 DPAPI、macOS 使用系统钥匙串保存 API Key；`providers.json` 只保留密文或钥匙串引用，旧版明文 Key 首次启动自动备份并迁移。
- JSON 导出默认移除 API Key；只有用户二次明确确认时才导出明文 Key。
- 远程服务强制 HTTPS，仅允许 `localhost` / `127.0.0.1` / `::1` 使用 HTTP。
- API URL 禁止内嵌用户名或密码，JSON 响应限制为 8 MB。
- 继续使用 certifi/Mozilla CA 严格校验证书和主机名，拒绝 HTTPS 降级并防止跨域重定向泄露 Authorization。

## 三个平台

- Windows
- macOS Apple Silicon（M 芯片）
- macOS Intel

## 批量导入到 WorkBuddy

通过当前 WorkBuddy 安装实际使用的 `%USERPROFILE%\.workbuddy\models.json` 格式，工具在拉取供应商 `/models` 后可以一键导入全部模型：按模型 ID 去重，同 ID 更新为当前供应商地址和 Key，其他已有模型保留；写入前自动备份到 `%USERPROFILE%\.workbuddy\model-backups\`。空文件会自动初始化，损坏或无效 JSON 会先备份为 `*-invalid.json` 再重建。导入完成后必须完全重启 WorkBuddy，才能在“设置 > 模型”看到更新后的列表。

## 本地开发

```text
python workbuddy_aip.pyw
```

Windows 构建：

```text
python build_windows.py
```

macOS 构建由 `.github/workflows/build-macos.yml` 生成 M 芯片和 Intel 两个产物。
