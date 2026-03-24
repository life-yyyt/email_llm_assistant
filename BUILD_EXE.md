# 打包为 .exe 完整流程

## 环境要求

- Windows
- Python 3.10
- 已安装项目依赖：`pip install -r requirements.txt`

## 一、打包命令

在项目根目录执行：

```bash
# 单文件 exe（推荐先测试单目录）
pyinstaller email_assistant.spec
```

生成物在 `dist/EmailLLMAssistant.exe`（单文件）或 `dist/EmailLLMAssistant/`（若改用 COLLECT 单目录）。

## 二、spec 说明

- `pathex=[ROOT]`：保证能解析到 `config`、`core`、`ui`、`utils` 包。
- `hiddenimports`：显式加入 PyQt5、transformers、torch 等，避免运行时找不到模块。
- `console=False`：不弹出黑色控制台，仅 GUI 窗口。
- 模型不写入 `datas`：Llama 模型体积大，建议放在磁盘固定目录，通过环境变量 `LLAMA_MODEL_PATH` 指定；或使用 Ollama 时设置 `OLLAMA_BASE_URL`、`OLLAMA_MODEL`。

## 三、模型目录打包方式（可选）

若必须把模型打进安装包：

1. 在 spec 中增加：

   ```python
   MODEL_PATH = r'D:\models\Llama-3.2-1B'  # 本地模型路径
   a = Analysis(
       ...
       datas=[(MODEL_PATH, 'models/Llama-3.2-1B')],
       ...
   )
   ```

2. 在代码中（如 `core/local_llm.py`）在打包环境下读取模型路径：

   ```python
   if getattr(sys, 'frozen', False):
       _base = sys._MEIPASS
       DEFAULT_MODEL_NAME = os.path.join(_base, 'models', 'Llama-3.2-1B')
   else:
       DEFAULT_MODEL_NAME = "meta-llama/Llama-3.2-1B"
   ```

这样 exe 解压到临时目录后，会从 `_MEIPASS/models/Llama-3.2-1B` 加载模型。注意单文件 exe 体积会非常大（数 GB）。

## 四、DLL 丢失解决方案

- **缺少 VCRUNTIME / MSVCP**：安装 [Visual C++ Redistributable](https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist)（x64）。
- **缺少 CUDA DLL**：若用 GPU，在目标机器安装对应版本 CUDA 运行库，或将 CUDA DLL 用 `binaries` 打进 spec（复杂，一般建议要求用户自装 CUDA）。
- **PyQt5 相关 DLL**：通常 PyInstaller 会自动收集；若仍报错，在 spec 的 `binaries` 中手动加入 Qt 的 `plugins/platforms/qwindows.dll` 等路径。

## 五、体积优化建议

1. **不打包模型**：通过环境变量或配置文件指定本地/网络模型路径，exe 只含程序与依赖。
2. **使用虚拟环境**：在干净 venv 中只装本项目依赖再打包，避免把无关库打进去。
3. **excludes**：在 spec 的 `excludes` 中排除不需要的库（如 matplotlib、pytest、setuptools）。
4. **UPX**：`upx=True` 可压缩 exe；若杀软误报可改为 `upx=False`。
5. **单目录模式**：用 `COLLECT` 生成目录版，启动更快，便于排查缺失 DLL。

## 六、运行 exe 时指定模型

- **Transformers 本地路径**：在批处理或系统环境变量中设置 `LLAMA_MODEL_PATH=D:\models\Llama-3.2-1B`，再双击 exe。
- **Ollama**：先启动 Ollama 并拉取 `llama3.2:1b`，设置 `OLLAMA_MODEL=llama3.2:1b`（可选），运行 exe 即可。
