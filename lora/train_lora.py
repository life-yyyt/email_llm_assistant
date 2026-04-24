# -*- coding: utf-8 -*-
r"""
Llama 3.2 1B LoRA 微调训练脚本
适配 3050 Ti (4GB VRAM)：使用 4bit 量化 + gradient checkpointing + 小 batch size

用法：
  cd lora
  python train_lora.py --base_model D:\LLAMA_LORA --epochs 3

训练完成后，LoRA 适配器保存在 --output_dir 指定的目录（默认 ./lora_adapter）。
"""

import argparse
import json
import os
import sys

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, TaskType, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
)


def load_train_data(path: str) -> list:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_sample(sample: dict, tokenizer, max_length: int = 512) -> dict:
    """将一条样本格式化为 prompt + completion 的 token ids。"""
    prompt = f"### 指令：\n{sample['instruction']}\n\n### 输入：\n{sample['input']}\n\n### 回复：\n"
    completion = sample["output"] + tokenizer.eos_token

    prompt_ids = tokenizer(prompt, add_special_tokens=True, truncation=True, max_length=max_length)["input_ids"]
    completion_ids = tokenizer(completion, add_special_tokens=False, truncation=True, max_length=max_length)["input_ids"]

    input_ids = (prompt_ids + completion_ids)[:max_length]
    # labels 中 prompt 部分设为 -100（不计算 loss），只对 completion 部分计算 loss
    labels = ([-100] * len(prompt_ids) + completion_ids)[:max_length]

    return {
        "input_ids": input_ids,
        "attention_mask": [1] * len(input_ids),
        "labels": labels,
    }


def main():
    parser = argparse.ArgumentParser(description="Llama 3.2 1B LoRA 微调")
    parser.add_argument("--base_model", type=str, default=r"D:\LLAMA_LORA", help="基座模型路径")
    parser.add_argument("--data_file", type=str, default="train_data.json", help="训练数据 JSON 文件路径")
    parser.add_argument("--output_dir", type=str, default="./lora_adapter", help="LoRA 适配器输出目录")
    parser.add_argument("--epochs", type=int, default=3, help="训练轮数")
    parser.add_argument("--lr", type=float, default=2e-4, help="学习率")
    parser.add_argument("--batch_size", type=int, default=1, help="每张卡 batch size（4GB 显存建议设为 1）")
    parser.add_argument("--grad_accum", type=int, default=8, help="梯度累积步数（等效 batch_size = batch_size * grad_accum）")
    parser.add_argument("--max_length", type=int, default=512, help="单条样本最大 token 数")
    parser.add_argument("--lora_r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--lora_alpha", type=int, default=32, help="LoRA alpha")
    parser.add_argument("--lora_dropout", type=float, default=0.05, help="LoRA dropout")
    args = parser.parse_args()

    if not os.path.isdir(args.base_model):
        print(f"错误：基座模型路径不存在 -> {args.base_model}")
        sys.exit(1)

    print(f"基座模型：{args.base_model}")
    print(f"训练数据：{args.data_file}")
    print(f"训练轮数：{args.epochs}")
    print(f"LoRA rank={args.lora_r}, alpha={args.lora_alpha}, dropout={args.lora_dropout}")
    print(f"batch_size={args.batch_size}, grad_accum={args.grad_accum}, 等效批大小={args.batch_size * args.grad_accum}")

    # ---- 1. 加载 tokenizer ----
    print("\n[1/5] 加载 tokenizer ...")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ---- 2. 4bit 量化加载模型 ----
    print("[2/5] 加载模型（4bit 量化）...")
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=True,
    )
    model = prepare_model_for_kbit_training(model)

    # ---- 3. 配置 LoRA ----
    print("[3/5] 配置 LoRA 适配器 ...")
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ---- 4. 准备数据集 ----
    print("[4/5] 处理训练数据 ...")
    raw_data = load_train_data(args.data_file)
    print(f"  共 {len(raw_data)} 条训练样本")

    processed = [format_sample(s, tokenizer, max_length=args.max_length) for s in raw_data]
    dataset = Dataset.from_list(processed)

    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        return_tensors="pt",
    )

    # ---- 5. 训练 ----
    print("[5/5] 开始训练 ...\n")
    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.1,
        fp16=True,
        logging_steps=5,
        save_strategy="epoch",
        save_total_limit=2,
        gradient_checkpointing=True,
        optim="paged_adamw_8bit",
        report_to="none",
        remove_unused_columns=False,
        dataloader_pin_memory=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        data_collator=data_collator,
    )

    trainer.train()

    # 保存 LoRA 适配器
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"\n训练完成！LoRA 适配器已保存到：{os.path.abspath(args.output_dir)}")
    print("下一步：运行 merge_lora.py 将适配器合并到基座模型，或直接在程序中加载适配器。")


if __name__ == "__main__":
    main()
