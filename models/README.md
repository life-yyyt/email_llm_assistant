本目录用于存放本地语言模型（如 Llama3.2 1B）的权重文件。

使用方式建议：

1. 在本目录下为每个模型创建一个子文件夹，例如：
   - `models/Llama-3.2-1B`
   - `models/Llama-3.2-1B-instruct`
2. 确保子文件夹内是 Transformers 可识别的本地模型结构（包含 `config.json`、`tokenizer.json`、`model.safetensors` 等文件）。
3. 启动程序后，在主界面顶部的「当前模型」下拉框中选择对应的子文件夹名称，即可切换到该本地模型。
4. 若未选择本地模型，程序仍会按照原逻辑：
   - 若未设置 `LLAMA_MODEL_PATH`，优先尝试使用 Ollama；
   - 否则使用环境变量 `LLAMA_MODEL_PATH` 指定的路径。

