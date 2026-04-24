# LoRA 微调使用说明

## 环境准备

```bash
pip install -r requirements_lora.txt
```

> 注意：`bitsandbytes` 在 Windows 上需要安装社区版本：
> ```bash
> pip install bitsandbytes-windows
> ```
> 如果安装失败，也可以参考 https://github.com/jllllll/bitsandbytes-windows-webui

## 第一步：训练

```bash
cd lora
python train_lora.py --base_model D:\LLAMA_LORA --epochs 3
```

训练参数说明（默认值已针对 3050 Ti 4GB 显存优化）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--base_model` | `D:\LLAMA_LORA` | Llama 3.2 1B 基座模型路径 |
| `--data_file` | `train_data.json` | 训练数据文件 |
| `--output_dir` | `./lora_adapter` | LoRA 适配器输出目录 |
| `--epochs` | 3 | 训练轮数 |
| `--batch_size` | 1 | 每步批大小（4GB 显存请保持 1） |
| `--grad_accum` | 8 | 梯度累积步数 |
| `--lora_r` | 16 | LoRA rank |

训练完成后，适配器保存在 `./lora_adapter` 目录。

## 第二步：合并模型

```bash
python merge_lora.py --base_model D:\LLAMA_LORA --adapter ./lora_adapter --output D:\LLAMA_LORA_MERGED
```

合并后 `D:\LLAMA_LORA_MERGED` 就是一个完整的模型目录，可以直接加载。

如果希望它能直接出现在邮件助手界面的“当前模型”下拉框里，建议将合并后的模型输出到以下任一位置：

- 项目下的 `models/某个目录`
- 项目下的 `lora/某个已合并模型目录`

例如：

```bash
python merge_lora.py --base_model D:\LLAMA_LORA --adapter ./lora_adapter --output ..\models\Llama-3.2-1B-LoRA-Merged
```

## 第三步：使用微调后的模型

在邮件助手中切换模型路径即可：

```bash
set LLAMA_MODEL_PATH=D:\LLAMA_LORA_MERGED
python main.py
```

如果合并后的模型目录位于项目的 `models/` 或 `lora/` 下，启动后可以直接在界面的“当前模型”下拉框中选择。
如果模型放在项目外部目录，则继续使用 `LLAMA_MODEL_PATH` 指向该目录即可。

## 训练数据

`train_data.json` 当前包含 96 条样本：
- 51 条邮件自动回复（覆盖确认、查收、处理、感谢、一般沟通等场景）
- 15 条自然风格润色
- 15 条正式风格润色
- 15 条商务风格润色

如果要增加训练数据，按相同的 JSON 格式添加即可：

```json
{
  "instruction": "任务描述",
  "input": "输入内容",
  "output": "期望输出"
}
```
