# -*- coding: utf-8 -*-
r"""
将 LoRA 适配器合并回基座模型，生成完整的微调后模型。

用法：
  python merge_lora.py --base_model D:\LLAMA_LORA --adapter ./lora_adapter --output D:\LLAMA_LORA_MERGED

合并后的模型可以直接用 AutoModelForCausalLM.from_pretrained 加载，不再需要 peft 库。
"""

import argparse
import os
import sys

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer


def main():
    parser = argparse.ArgumentParser(description="合并 LoRA 适配器到基座模型")
    parser.add_argument("--base_model", type=str, default=r"D:\LLAMA_LORA", help="基座模型路径")
    parser.add_argument("--adapter", type=str, default="./lora_adapter", help="LoRA 适配器目录")
    parser.add_argument("--output", type=str, default=r"D:\LLAMA_LORA_MERGED", help="合并后模型输出目录")
    args = parser.parse_args()

    if not os.path.isdir(args.base_model):
        print(f"错误：基座模型路径不存在 -> {args.base_model}")
        sys.exit(1)
    if not os.path.isdir(args.adapter):
        print(f"错误：LoRA 适配器路径不存在 -> {args.adapter}")
        sys.exit(1)

    print(f"基座模型：{args.base_model}")
    print(f"LoRA 适配器：{args.adapter}")
    print(f"合并输出：{args.output}")

    print("\n[1/4] 加载 tokenizer ...")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True, local_files_only=True)

    print("[2/4] 加载基座模型（float16）...")
    base_model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        torch_dtype=torch.float16,
        device_map="cpu",
        trust_remote_code=True,
        local_files_only=True,
    )

    print("[3/4] 加载并合并 LoRA 适配器 ...")
    model = PeftModel.from_pretrained(base_model, args.adapter)
    model = model.merge_and_unload()

    print("[4/4] 保存合并后的模型 ...")
    os.makedirs(args.output, exist_ok=True)
    model.save_pretrained(args.output)
    tokenizer.save_pretrained(args.output)

    print(f"\n合并完成！模型已保存到：{os.path.abspath(args.output)}")
    print("现在可以在邮件助手中将模型路径切换到合并后的目录，或设置环境变量：")
    print(f"  set LLAMA_MODEL_PATH={os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
