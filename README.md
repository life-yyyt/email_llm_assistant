# Email LLM Assistant

基于 Llama 3.2 1B 的本地智能邮件分类与回复助手。

这是一个面向 Windows 的 Python 桌面应用，使用 `PyQt5` 构建界面，结合本地大语言模型完成邮件分类、回复生成和文本润色。项目强调本地运行体验，适合课程设计、原型验证和离线场景下的智能邮件辅助。

## 项目亮点

- 本地运行：支持本地 `transformers` 模型或 `Ollama`
- 多邮箱支持：根据邮箱后缀自动匹配 IMAP/SMTP 配置
- 智能分类：对邮件进行正常邮件 / 垃圾邮件二分类
- 自动回复：根据邮件上下文生成简短回复
- 邮件润色：支持自然、正式、商务三种风格
- 桌面应用：可直接运行，也可打包为 Windows `.exe`

## 功能概览

- 拉取最近邮件并解析发件人、主题、时间、正文、附件、链接
- 在界面中查看邮件详情并手动修正分类结果
- 使用本地模型生成回复草稿
- 对回复内容进行润色优化
- 通过 SMTP 直接发送回复邮件

## 技术栈

- Python 3.10
- PyQt5
- imaplib / smtplib / email
- transformers / torch
- Ollama
- PyInstaller

## 项目结构

```text
email_llm_assistant/
├── main.py
├── requirements.txt
├── email_assistant.spec
├── BUILD_EXE.md
├── config/
│   ├── __init__.py
│   └── email_servers.py
├── core/
│   ├── __init__.py
│   ├── account_store.py
│   ├── email_client.py
│   └── local_llm.py
├── ui/
│   ├── __init__.py
│   ├── add_account_dialog.py
│   └── main_window.py
├── utils/
│   ├── __init__.py
│   ├── cache.py
│   └── email_parser.py
└── docs/
```

## 工作流程

1. 用户添加邮箱账号，系统自动匹配 IMAP / SMTP 服务地址。
2. 程序拉取最近邮件并解析正文、附件和链接。
3. 本地 LLM 对邮件执行垃圾邮件分类。
4. 用户可选中某封邮件生成回复或继续人工编辑。
5. 回复内容可按不同风格进行润色后发送。

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备模型

项目支持两种方式运行本地模型。

#### 方式一：Ollama

先安装并启动 Ollama，然后拉取模型：

```bash
ollama run llama3.2:1b
```

如有需要，可通过环境变量指定服务地址或模型名：

```bash
set OLLAMA_BASE_URL=http://127.0.0.1:11434
set OLLAMA_MODEL=llama3.2:1b
```

#### 方式二：Transformers 本地模型目录

将模型下载到本地后，设置环境变量：

```bash
set LLAMA_MODEL_PATH=D:\path\to\Llama-3.2-1B
```

该目录应包含 `config.json`、tokenizer 文件和模型权重文件。

### 3. 运行项目

```bash
python main.py
```

首次使用智能分类、自动回复或润色功能时，程序会在后台加载模型，可能需要等待几秒。

## 使用说明

### 添加邮箱

- 点击“添加账号”
- 输入邮箱地址和密码或授权码
- 程序会根据邮箱域名自动匹配服务器配置

### 查看与分类邮件

- 选择邮箱后会拉取最近 50 封邮件
- 左侧列表展示邮件概览
- 右侧区域展示正文、附件、链接和分类状态

### 生成回复

- 选中一封邮件
- 点击“生成回复”
- 程序会基于邮件内容生成简短回复草稿

### 润色回复

- 在回复框中编辑内容
- 选择“自然 / 正式 / 商务”风格
- 点击“润色”生成优化后的版本

### 发送邮件

- 确认收件人和回复内容
- 如有需要可添加附件
- 点击“发送”完成邮件回复

## 支持的邮箱

当前内置了常见邮箱服务配置，包括：

- QQ 邮箱
- Gmail
- Outlook / Hotmail / Live
- 网易 163 / 126 / yeah.net
- 新浪邮箱
- 搜狐邮箱
- Yahoo
- 阿里邮箱
- 139 / 189 邮箱

对应配置可在 `config/email_servers.py` 中扩展。

## 打包为 EXE

项目已提供 `PyInstaller` 配置文件：

```bash
pyinstaller email_assistant.spec
```

详细说明见 [BUILD_EXE.md](./BUILD_EXE.md)。

## 注意事项

- 某些邮箱服务商要求使用授权码而不是登录密码
- 使用 `transformers` 本地模型时，需要提前准备完整模型目录
- 使用 `Ollama` 时，需要确保本地服务已启动
- 当前账号信息会保存到本地配置文件中，适合个人本机使用，不建议在共享环境中直接保存敏感账号

## 文档说明

`docs/` 目录包含项目相关的论文材料、架构设计、测试评估与研究总结，可用于课程汇报或论文撰写参考。

## 后续可改进方向

- 增加更多邮件分类标签，而不仅限于二分类
- 支持草稿箱、已发送、星标邮件等更多文件夹
- 增加账号密码的安全存储能力
- 提升模型输出稳定性和多语言表现
- 增加日志、测试和异常恢复机制

## License

当前仓库暂未指定开源许可证。如计划公开分发，建议补充合适的 License 文件。
