# 基于 Llama3.2 1B 的本地智能邮件分类与回复助手

Windows + Python 3.10 桌面应用，**完全离线**运行，支持多邮箱、本地大模型分类/回复/润色，可打包为 .exe。

## 功能概览

- **多邮箱**：支持 QQ、Gmail、Outlook、网易、新浪等，根据后缀自动匹配 IMAP/SMTP
- **邮件拉取**：最近 N 封，解析发件人、主题、时间、正文（优先 text/plain）
- **垃圾邮件二分类**：本地 Llama3.2 1B，固定 Prompt，低温度稳定输出
- **自动生成回复**：根据原邮件语境生成合适回复
- **邮件润色**：优化表达，更清晰自然得体
- **内存管理**：不落库，多账号仅在内存中管理

## 项目结构

```
email_llm_assistant/
├── main.py                 # 程序入口
├── requirements.txt        # 依赖
├── email_assistant.spec    # PyInstaller 打包配置
├── BUILD_EXE.md            # 打包为 exe 的完整说明
├── config/
│   ├── __init__.py
│   └── email_servers.py    # 邮箱后缀 -> IMAP/SMTP 配置
├── core/
│   ├── __init__.py
│   ├── local_llm.py        # 本地大模型单例（transformers/ollama）
│   ├── account_store.py    # 内存账号管理
│   └── email_client.py     # IMAP/SMTP 拉取与发送
├── utils/
│   ├── __init__.py
│   ├── email_parser.py    # 邮件解析 -> MailItem
│   └── cache.py           # 简单缓存（分类/生成结果）
└── ui/
    ├── __init__.py
    ├── main_window.py      # 主窗口：邮箱选择、邮件列表、正文、分类、回复、润色、发送
    └── add_account_dialog.py  # 添加邮箱对话框
```

## 运行环境

- Windows
- Python 3.10
- 本地已部署 Llama3.2 1B：任选其一
  - **transformers**：本地路径或 HuggingFace 模型名，环境变量 `LLAMA_MODEL_PATH` 可指定路径
  - **ollama**：先启动 Ollama 并拉取 `llama3.2:1b`，可选环境变量 `OLLAMA_BASE_URL`、`OLLAMA_MODEL`

## 安装与运行

```bash
cd email_llm_assistant
pip install -r requirements.txt
python main.py
```

首次使用「智能分类」或「生成回复」时会加载模型（在后台线程），可能稍等几秒。

## 打包为 .exe

详见 **BUILD_EXE.md**。简要步骤：

```bash
pyinstaller email_assistant.spec
```

生成 `dist/EmailLLMAssistant.exe`。模型建议不打包，通过环境变量指定路径或使用 Ollama。

## 使用说明

1. **添加账号**：点击「添加账号」，输入邮箱与密码（QQ/163 等使用授权码），自动匹配服务器。
2. **刷新邮件**：选择当前邮箱后自动拉取最近 50 封，或点击「刷新邮件」。
3. **查看与分类**：左侧点击邮件，右侧显示正文；点击「智能分类」得到正常邮件/垃圾邮件（垃圾邮件在列表中红色显示）。
4. **回复**：在回复框输入或点击「生成回复」/「润色」，再点击「发送」。

## 许可证

按项目需求自行选择。
