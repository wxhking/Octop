# MCP OAuth 授权端点 query：本地验证证据

这些材料来自真实本地运行，使用虚拟域名和客户端标识。截图是测试报告，不是产品界面或远端 CI 截图。

## 已验证行为

- 原实现基线：TencentCloud/Octop `2de23da5f36995014ba2902e7cda568de0515c57`。
- 无 query 对照：修复前后均接受。
- `?tenant=acme`：原实现将 response_type 拼进 tenant 值；修复后 tenant 与 response_type 均正确。
- 末尾空 `?`、多参数、百分号编码等边界：修复前丢失必需参数，修复后保持完整。
- 空值/重复非 OAuth tag 为原 query 保留的兼容性样例，不据此证明完整 OAuth 服务合规性。

## 可独立重跑

在 Octop 仓库安装锁定依赖后，下载此目录的 repro_oauth_flow.py，执行：

```text
# 上述固定上游提交，验证旧行为
uv run python <证据目录>/repro_oauth_flow.py --repo . --expect broken

# 应用修复后，验证新行为
uv run python <证据目录>/repro_oauth_flow.py --repo . --expect fixed
```

脚本调用真实 `registry.start_oauth_for_target(custom_mcp)`，经过 MCP 401、资源/授权服务元数据发现、动态注册、URL 构建，再用 HTTPX 模拟授权请求校验器检查原参数、response_type、state、redirect_uri、PKCE、scope/resource。

仅替换 DNS 和 HTTP transport；没有替换 Octop 业务函数，没有真实外部网络、模型或凭据。200 表示模拟参数校验接受，400 表示参数缺失/污染。不是完整浏览器登录、真实第三方授权或 token exchange E2E。

## 文件

- [修复前原始输出](public-before.jsonl)
- [修复后原始输出](public-after.jsonl)
- [最小复现前输出](minimal-before.txt) / [后输出](minimal-after.txt)
- [可运行公共入口脚本](repro_oauth_flow.py)
- [中文对照截图](regression-evidence.png)

## 协议依据

[RFC 6749 §3.1](https://www.rfc-editor.org/rfc/rfc6749#section-3.1) 要求添加参数时保留授权端点原 query；[§3.1.1](https://www.rfc-editor.org/rfc/rfc6749#section-3.1.1) 规定 response_type 必需，缺失需返回错误。
