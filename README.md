# Email LLM Assistant

基于 `Llama 3.2 1B` 的本地智能邮件分类与回复助手。

这是一个面向 Windows 的 Python 桌面应用，使用 `PyQt5` 构建界面，结合本地语言模型完成邮件分类、自动回复和正文润色。项目强调本地运行与隐私保护，适合课程设计、原型验证和离线办公辅助场景。

## 主要功能

- 多邮箱账号管理与自动服务器配置
- IMAP 拉取邮件，SMTP 发送邮件
- 正常邮件 / 垃圾邮件二分类
- 自动回复生成
- 自然 / 正式 / 商务三种风格润色
- 附件识别、保存与发送
- 支持 `Transformers` 与 `Ollama` 双后端

## 技术栈

- Python 3.10+
- PyQt5
- imaplib / smtplib / email
- transformers / torch
- Ollama
- PyInstaller

## 项目结构

```text
email_llm_assistant/
├─ main.py
├─ requirements.txt
├─ email_assistant.spec
├─ BUILD_EXE.md
├─ config/
│  └─ email_servers.py
├─ core/
│  ├─ account_store.py
│  ├─ email_client.py
│  └─ local_llm.py
├─ ui/
│  ├─ add_account_dialog.py
│  └─ main_window.py
├─ utils/
│  ├─ cache.py
│  └─ email_parser.py
├─ scripts/
│  ├─ eval_classification.py
│  └─ generate_preddefense_ppt.py
├─ tests/
│  └─ classification_cases.json
├─ lora/
│  ├─ train_lora.py
│  ├─ merge_lora.py
│  └─ train_data.json
└─ docs/
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 准备模型

项目支持两种本地模型接入方式。

#### 方式一：Ollama

```bash
ollama run llama3.2:1b
```

如有需要，可设置：

```bash
set OLLAMA_BASE_URL=http://127.0.0.1:11434
set OLLAMA_MODEL=llama3.2:1b
```

#### 方式二：Transformers 本地模型目录

```bash
set LLAMA_MODEL_PATH=D:\path\to\Llama-3.2-1B
```

模型目录需包含 `config.json`、tokenizer 文件和权重文件。

### 3. 启动程序

```bash
python main.py
```

首次使用分类、回复或润色功能时，程序可能需要数秒加载模型。

## 使用说明

### 添加邮箱

- 点击“添加账号”
- 输入邮箱地址和密码 / 授权码
- 程序会根据邮箱域名自动匹配常见 IMAP / SMTP 配置

### 查看与分类邮件

- 选择邮箱后自动拉取最近邮件
- 左侧显示邮件列表，右侧显示正文、附件和链接
- 可执行智能分类，并支持手动修正分类结果

### 生成回复与润色

- 选中邮件后点击“生成回复”
- 在下方编辑区可继续修改回复内容
- 选择“自然 / 正式 / 商务”风格后点击“润色”

### 发送邮件

- 确认收件人和正文
- 需要时可附加附件
- 点击“发送”完成回复

## 支持的邮箱

内置常见邮箱服务配置，包括：

- QQ 邮箱
- Gmail
- Outlook / Hotmail / Live
- 网易 163 / 126 / yeah.net
- 新浪邮箱
- 搜狐邮箱
- Yahoo
- 阿里邮箱
- 139 / 189 邮箱

如需扩展，可修改 [config/email_servers.py](C:\Users\12700\email_llm_assistant\config\email_servers.py)。

## 测试与评估

项目包含一份固定分类测试集与评估脚本：

- 测试数据：[tests/classification_cases.json](C:\Users\12700\email_llm_assistant\tests\classification_cases.json)
- 评估脚本：[scripts/eval_classification.py](C:\Users\12700\email_llm_assistant\scripts\eval_classification.py)

运行方式：

```bash
py -3.12 -X utf8 scripts/eval_classification.py --backend ollama
```

## LoRA 扩展

项目保留了面向邮件场景的 LoRA 微调链路，用于后续增强回复与润色效果：

- [lora/train_lora.py](C:\Users\12700\email_llm_assistant\lora\train_lora.py)
- [lora/merge_lora.py](C:\Users\12700\email_llm_assistant\lora\merge_lora.py)
- [lora/README_LORA.md](C:\Users\12700\email_llm_assistant\lora\README_LORA.md)

## 打包 EXE

```bash
pyinstaller email_assistant.spec
```

详细说明见 [BUILD_EXE.md](C:\Users\12700\email_llm_assistant\BUILD_EXE.md)。

## 注意事项

- 部分邮箱服务商要求使用授权码，而不是网页登录密码
- Gmail 需要开启 IMAP、两步验证，并使用应用专用密码
- 账号信息当前保存在本地配置文件中，适合个人单机环境，不建议在共享环境中直接保存敏感账号

## 文档

`docs/` 目录包含论文配图、流程图和图表汇总等材料，可用于论文写作与答辩准备。

## License

当前仓库暂未附带开源许可证；如果计划公开分发，建议补充合适的 License 文件。
