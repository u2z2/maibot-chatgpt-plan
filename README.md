# MaiBot ChatGPT Plan（Windows 测试版）

在 Windows 上为本机 MaiBot 接入 **Sign in with ChatGPT** 订阅授权。登录自己的符合条件的 ChatGPT 账号，选择账号返回的模型，测试成功后添加一个 **可选模型**。

**不会自动替换现有模型，不会修改 replyer、planner 或其他任务的选择。**

这是独立应用集成的测试版，不是 OpenAI 官方项目，也不提供通用会员 API、账号共享或额度转租服务。

## 使用范围

- Windows 10/11、Python 3.11 或更高版本。
- MaiBot 需要支持 `openai_responses` 提供商；已在带有该适配器的本地 MaiBot 配置结构上验证。
- 需要自己的符合条件的 ChatGPT 订阅账号，以及可访问 OpenAI 服务的网络。可用模型和额度由账号决定。
- 初版仅支持文本 Responses 请求。未验证其他机器人框架，不支持 Chat Completions、原生工具调用、图片、音频或文件。
- **只用于已登录用户本人的请求和明确授权的个人自动化。不要用自己的订阅满足群友或其他用户的请求。**

官方条款要求订阅仅用于已连接应用、禁止通用 API 转供其他工具、禁止满足他人的请求：
[Sign in with ChatGPT Terms](https://openai.com/policies/sign-in-with-chatgpt-terms/)。公开源码的 MIT 许可证不会扩大 OpenAI 订阅授权范围。

## 安装和启动

下载本仓库，进入目录，在 PowerShell 中运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
```

安装脚本使用独立 `.venv`，不修改 MaiBot 的 Python 环境。启动脚本启动隐藏后台进程并打开设置页，默认地址为 `http://127.0.0.1:8776/`。

1. 填写现有 MaiBot `config/model_config.toml` 的完整路径，保存位置。
2. 点击 **Continue with ChatGPT**，在 OpenAI 官方页面登录并授权使用订阅额度。
3. 选择需要的模型，例如账号列表中出现的 GPT-5.6-Luna。
4. 确认个人使用和自动化授权，点击 **测试并添加 GPT 可选模型**。
5. 在 MaiBot 中自行选择 `chatgpt-plan-local`。提供商名称为 `MaiBot-ChatGPT-Plan`。

测试会发送一句简短问候并使用少量订阅额度。只有收到完整且包含非空文本的 `response.completed` 后才添加模型。桥接会将前面已完成的输出补入缺少 output 的最终事件，避免 MaiBot 误报“响应为空”。若 MaiBot 未自动加载新选项，在启动器中重启 MaiBot。

### 自定义端口与配置位置

```powershell
.\scripts\start.ps1 -Port 8777 -MaiBotConfig 'D:\MaiBot\config\model_config.toml'
```

同一数据目录只允许一个运行实例，避免旋转刷新令牌被多个进程同时使用。重启 Windows 后重新运行启动脚本；本项目不会注册开机自启。

前台诊断模式：

```powershell
.\.venv\Scripts\python.exe -m maibot_chatgpt_plan --port 8776
```

## 数据、备份与隐私

默认数据目录为 `%LOCALAPPDATA%\MaiBotChatGPTPlan`，不在仓库内。账号邮箱、OAuth 令牌、客户端注册信息、本地连接密钥及完整配置备份均使用 Windows DPAPI 加密，目录只允许当前 Windows 用户访问。

- 本地 API 只监听 `127.0.0.1`，需要本应用为连接的 MaiBot 配置生成的本地密钥。
- OpenAI OAuth 令牌不写入 MaiBot 配置；配置只包含本地连接密钥，仍应保密。
- 授权需要你在浏览器完成；本程序不接收 ChatGPT 密码或网页 Cookie。
- 聊天输入经 HTTPS 发送给 OpenAI；程序不保存输入、输出、授权 URL 或访问日志，不发送遥测。
- 模型配置备份为 `model-config-backup-*.dpapi`；可通过 `scripts/restore-backup.ps1` 先预览再选择恢复。
- 换电脑或换 Windows 用户请重新登录，不要复制凭据。
- 点击“断开订阅授权”会尝试撤销会话并删除本地授权令牌。网络故障时会提示远程撤销未确认，可在 ChatGPT 设置中断开应用。

## 接口限制

上游采用官方 `https://api.openai.com/v1/responses`，不是 ChatGPT 网页内部接口。

根据官方预览约定，自动把字符串 input 转换为消息列表，把 system 消息转换为 developer 消息，并省略此授权流程不支持的采样、输出限制及存储相关字段。**MaiBot 配置里的温度和最大输出 token 不会在这条订阅线路上生效。** 聊天历史需要在每次请求中提供，不依赖上游持久会话。

模型添加为 `visual=false`、`force_stream_mode=true`、`send_temperature=false`，默认不重试，避免错误请求反复消耗额度。选用此模型前应保留其他任务已验证的模型设置。

官方文档：

- [订阅授权](https://developers.openai.com/siwc/token-sharing-open-source)
- [注册与登录](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [模型与请求](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [预览限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)

## 常见问题

- **无法打开本地页面**：确认启动成功，或使用前台模式查看启动错误；端口占用时换一个端口。
- **登录按钮无响应／过期**：刷新设置页，确保浏览器允许本机页面 Cookie，再重新登录。
- **HTTP 400**：页面会显示经过脱敏的上游原因；确认使用文本模型和当前支持的请求格式。
- **授权或额度失效**：查看 ChatGPT 的 Usage 设置。重新登录不会增加额度，本应用也不会自动转为另行收费的 API。
- **MaiBot 能力测试**：本版只支持文本，包含图片或原生工具调用的综合测试会提示不支持；不要据此启用视觉或工具功能。
- **收消息不回复**：MaiBot 的回复频率、@ 触发和规划流程独立于本集成；检查 MaiBot 日志。

## 开发与验证

```powershell
python -m pip install -e .
python -m unittest discover -s tests -v
```

测试使用模拟上游和临时配置，不需要登录、不修改实际机器人、不消耗订阅额度。GitHub Actions 在 Windows 上运行同一组测试。真实账号授权、模型可用性和所有 MaiBot 分支的完整聊天链路不属于自动测试覆盖范围。

## License

本项目自行实现的代码使用 MIT License。第三方 Python 依赖及 OpenAI 服务各自适用其许可证和条款。
