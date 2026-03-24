# -*- coding: utf-8 -*-
"""
本地大模型单例封装：避免重复加载，支持分类（低温度）与生成（可调温度/max_tokens）。
支持 backend: transformers（默认）、ollama。
"""

from typing import Optional, Literal
import threading
import os
import re

# 后端类型
BackendType = Literal["transformers", "ollama"]

# 默认不使用 HuggingFace 模型 ID，避免访问 gated 仓库；仅支持本地目录或 Ollama
DEFAULT_MODEL_NAME = None


class LocalLLM:
    """单例：本地 Llama3.2 1B 加载与推理。"""

    _instance: Optional["LocalLLM"] = None
    _lock = threading.Lock()

    def __new__(cls, model_path: Optional[str] = None, backend: BackendType = "transformers", **kwargs) -> "LocalLLM":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(
        self,
        model_path: Optional[str] = None,
        backend: BackendType = "transformers",
        device: Optional[str] = None,
        use_cache: bool = True,
        cache_max_size: int = 300,
    ):
        if self._initialized:
            return
        self._model_path = (model_path or os.environ.get("LLAMA_MODEL_PATH") or DEFAULT_MODEL_NAME) or None
        if self._model_path:
            self._model_path = self._model_path.strip()
        self._backend = backend
        self._device = device
        self._model = None
        self._tokenizer = None
        self._ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self._ollama_model = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
        self._initialized = True
        self._load_lock = threading.Lock()
        if use_cache:
            from utils.cache import SimpleCache  # noqa: relative import from project root
            self._cache = SimpleCache(max_size=cache_max_size)
        else:
            self._cache = None

    def _ensure_loaded(self) -> None:
        with self._load_lock:
            if self._model is not None:
                return
            if self._backend == "transformers":
                self._load_transformers()
            elif self._backend == "ollama":
                self._model = "ollama"  # 仅标记已初始化
            else:
                raise ValueError(f"Unsupported backend: {self._backend}")

    def _load_transformers(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        path = (self._model_path or "").strip()
        if not path or not os.path.isdir(path):
            raise RuntimeError(
                "使用 Transformers 本地模型时，必须指定本地模型目录（完全离线，不访问 HuggingFace）。\n\n"
                "请将 Llama3.2 1B 下载到本地后，设置环境变量：\n"
                "  set LLAMA_MODEL_PATH=D:\\你的路径\\Llama-3.2-1B\n"
                "（路径需为包含 config.json 的模型目录）\n\n"
                "若已安装 Ollama，可先运行 ollama run llama3.2:1b，本程序将自动尝试使用 Ollama 后端。"
            )
        dev = self._device
        if dev is None:
            dev = "cuda" if torch.cuda.is_available() else "cpu"
        self._device = dev
        # 仅从本地加载，不访问网络
        self._tokenizer = AutoTokenizer.from_pretrained(path, trust_remote_code=True, local_files_only=True)
        self._model = AutoModelForCausalLM.from_pretrained(
            path,
            trust_remote_code=True,
            torch_dtype=torch.float32 if dev == "cpu" else torch.float16,
            device_map="auto" if dev == "cuda" else None,
            low_cpu_mem_usage=True,
            local_files_only=True,
        )
        if dev == "cpu" and self._model is not None:
            self._model = self._model.to(dev)

    def _generate_transformers(self, prompt: str, temperature: float = 0.1, max_tokens: int = 64) -> str:
        import torch
        inputs = self._tokenizer(prompt, return_tensors="pt", truncation=True, max_length=2048)
        inputs = {k: v.to(self._model.device) for k, v in inputs.items()}
        with torch.no_grad():
            out = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=max(0.01, temperature),
                do_sample=temperature > 0,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        decoded = self._tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
        return decoded.strip()

    def _generate_ollama(self, prompt: str, temperature: float = 0.1, max_tokens: int = 64) -> str:
        import requests
        try:
            r = requests.post(
                f"{self._ollama_base_url.rstrip('/')}/api/generate",
                json={
                    "model": self._ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=120,
            )
            r.raise_for_status()
            j = r.json()
            return (j.get("response") or "").strip()
        except Exception as e:
            return f"[Ollama 调用失败: {e}]"

    def generate(self, prompt: str, temperature: float = 0.1, max_tokens: int = 128, use_cache: bool = True) -> str:
        """
        通用生成接口。分类时建议 temperature=0.1, max_tokens=16；回复/润色可提高 temperature 和 max_tokens。
        """
        self._ensure_loaded()
        if use_cache and self._cache is not None:
            cache_key = f"{prompt[:200]}|{temperature}|{max_tokens}"
            out = self._cache.get(cache_key)
            if out is not None:
                return out
        if self._backend == "transformers" and self._model is not None:
            out = self._generate_transformers(prompt, temperature=temperature, max_tokens=max_tokens)
        else:
            out = self._generate_ollama(prompt, temperature=temperature, max_tokens=max_tokens)
        if use_cache and self._cache is not None:
            self._cache.set(cache_key, out)
        return out

    # ---------- 业务接口 ----------

    SPAM_PROMPT = (
        "判断下面这封邮件是「正常邮件」还是「垃圾邮件」。\n"
        "只有「明显」是垃圾的才选垃圾：主题或正文带 <广告>、推销、领奖、点击链接、群发营销、新闻头条推送等。\n"
        "以下一律算正常邮件：个人问候（你好/在吗/吃了吗）、私信、工作学习往来、无主题或简短主题的私人内容。\n"
        "拿不准、看不出明显广告推销的，一律答正常邮件。只回答：正常邮件 或 垃圾邮件。\n\n邮件内容：\n"
    )

    def classify_spam(self, subject: str, body: str, use_cache: bool = True) -> str:
        """垃圾邮件二分类，低温度稳定输出。返回「正常邮件」或「垃圾邮件」。"""
        subject = subject or ""
        # 主题中带广告标记的，直接判为垃圾邮件
        if "广告" in subject or "推广" in subject or "<广告>" in subject:
            return "垃圾邮件"
        # 无主题或极短、正文也很短且无推销关键词时，倾向正常邮件，减少小模型误杀
        body_trim = (body or "").strip()
        if len(subject) <= 2 and len(body_trim) < 200 and not any(
            k in (subject + body_trim) for k in ("促销", "优惠", "点击", "领奖", "注册", "订阅", "退订", "广告", "推广")
        ):
            return "正常邮件"
        text = f"主题：{subject}\n正文：{body}"[:1500]
        prompt = self.SPAM_PROMPT + text
        out = self.generate(prompt, temperature=0.1, max_tokens=16, use_cache=use_cache)
        out = out.strip()
        if "垃圾邮件" in out:
            return "垃圾邮件"
        return "正常邮件"

    def generate_reply(self, subject: str, body: str, use_cache: bool = False) -> str:
        """
        根据收到的邮件生成自动回复，追求「非常简短、直接回答」。
        """
        body_trim = (body or "").strip()
        subject = subject or ""
        # 使用统一的 email_content 变量承载原始邮件内容（含主题和正文）
        email_content = f"邮件主题：{subject}\n\n邮件正文：\n{body_trim[:3000]}"

        prompt = (
            "你是一个邮件自动回复助手。\n\n"
            "任务：\n"
            "阅读下面的邮件内容，只给出一个非常简短的回复。\n\n"
            "规则：\n"
            "1. 只围绕原邮件的内容做出直接回答：对问题就回答问题，对请求就简单确认会处理，对问候就简短回应。\n"
            "2. 只用 1 句或最多 2 句，总长度尽量控制在 40 个汉字或 100 个字符以内。\n"
            "3. 输出语言必须与原邮件主体语言一致，只使用一种语言，不允许中英混杂。\n"
            "4. 不要重复或复述对方的原话，不要引用原文内容。\n"
            "5. 不要解释自己在做什么，不要分析原文，不要列出多个版本或使用序号。\n"
            "6. 不要添加问候语或结尾套话，只写需要发出的核心回复内容。\n\n"
            "收到的邮件：\n"
            f"{email_content}\n\n"
            "请直接给出这封邮件的简短回复：\n"
        )
        # 始终按“短回复”处理
        raw = self.generate(prompt, temperature=0.6, max_tokens=64, use_cache=use_cache)
        cleaned = self._dedup_repeated_lines(raw)
        # 将回复裁剪为最多 1~2 句的简短文本
        return self._shrink_to_reasonable_reply(cleaned, short=True)

    # 润色场合约束：不同风格对应不同提示
    POLISH_STYLES = {
        "自然": (
            "请把下面这段邮件正文润色一下。要求：保持原意，只改表达，让句子更通顺、自然、好读；"
            "语气像真人写的，不要刻板。只输出润色后的正文，不要解释或前缀。\n\n待润色内容：\n"
        ),
        "正式": (
            "请把下面这段邮件正文润色成正式场合用语。要求：用词规范、语气得体、结构清晰，"
            "适合正式沟通或书面场合；保持原意，不要口语化。只输出润色后的正文，不要解释或前缀。\n\n待润色内容：\n"
        ),
        "商务": (
            "请把下面这段邮件正文润色成商务风格。要求：专业、简洁、礼貌、有条理，"
            "适合与客户或同事的商务往来；保持原意，避免口语和冗余。只输出润色后的正文，不要解释或前缀。\n\n待润色内容：\n"
        ),
    }

    def polish_email(self, content: str, style: str = "自然", use_cache: bool = False) -> str:
        """润色邮件正文。style 可选：自然、正式、商务。"""
        trimmed = (content or "").strip()
        # 使用统一的 email_content 变量承载原始邮件内容
        email_content = trimmed[:3000]

        style = (style or "自然").strip()
        if style not in ("自然", "正式", "商务"):
            style = "自然"

        if style == "自然":
            style_block = (
                "- 风格：自然。\n"
                "- 语气轻松、自然，像和熟悉同事或朋友沟通，可以适度口语化。\n"
                "- 重点是通顺好读、亲切真实，不要太官方。\n"
            )
        elif style == "正式":
            style_block = (
                "- 风格：正式。\n"
                "- 用词规范、严谨，语气庄重有礼，适合公文、通知、正式工作邮件。\n"
                "- 句式完整，避免口语和网络用语。\n"
            )
        else:  # 商务
            style_block = (
                "- 风格：商务。\n"
                "- 表达专业、简洁、有条理，适合与客户、合作伙伴、供应商等的商务往来。\n"
                "- 突出关键信息、时间、金额、行动项，语气礼貌但不过多铺垫。\n"
            )

        prompt = (
            "你是一个擅长模仿人类写作风格的邮件润色助手。\n\n"
            "任务：\n"
            f"在不改变原本含义和态度的前提下，把下面的邮件按「{style}」风格润色得更自然、更有条理。\n\n"
            "风格说明：\n"
            f"{style_block}\n"
            "- 尽量保留原来的语气和人格特征，只在不自然的地方做细致调整。\n"
            "- 让句子更流畅、有逻辑，段落清晰，可以适当拆句或合并句子。\n\n"
            "必须遵守的规则：\n"
            "1. 不能改变原本要表达的事实、态度和结论，只优化表达方式。\n"
            "2. 绝对不要添加原文中没有提到的新信息、请求、提议或安排（例如主动提出帮忙、提到新的任务或文件）。\n"
            "3. 保持篇幅与原文接近，尽量不要明显变长，只在必须时少量补充过渡语句。\n"
            "4. 提高语句的流畅度和逻辑性，删除多余的重复或啰嗦表达。\n"
            "5. 输出语言必须与输入语言一致，只使用一种语言，不允许中英混杂。\n"
            "6. 不要说明你做了哪些修改，不要添加任何解释性或总结性的句子，例如「以上是润色后的版本」「请您查收」之类。\n"
            "7. 只输出润色后的完整邮件正文，不要加标题、前缀，也不要列出多个版本。\n"
            "8. 不要使用项目符号或编号列出多条内容，只保留一个最终版本。\n\n"
            "原始邮件：\n"
            f"{email_content}\n\n"
            "请直接给出「润色后的邮件」正文：\n"
        )
        # 根据原文长度自适应生成长度，避免长时间推理
        length = len(trimmed)
        if length <= 200:
            max_tokens = 96
        elif length <= 800:
            max_tokens = 220
        else:
            max_tokens = 320
        # 略低的 temperature 让输出更稳定，也能减少无谓展开
        raw = self.generate(prompt, temperature=0.3, max_tokens=max_tokens, use_cache=use_cache)
        cleaned = self._dedup_repeated_lines(raw)
        # 对非常短的原文，只允许输出一两句，防止无缘无故扩写
        if length <= 30:
            return self._shrink_polish_short(cleaned)
        return cleaned

    @staticmethod
    def _dedup_repeated_lines(text: str) -> str:
        """
        简单后处理：去掉连续的重复句子/行，并压缩多余空行。
        目的是抑制小模型常见的“同一句话重复多次”的问题。
        """
        if not text:
            return ""
        lines = text.splitlines()
        out = []
        prev_non_empty = None
        for line in lines:
            stripped = line.strip()
            if stripped and prev_non_empty is not None and stripped == prev_non_empty:
                # 跳过与上一句完全相同的非空行
                continue
            out.append(line)
            if stripped:
                prev_non_empty = stripped
        result = "\n".join(out)
        # 将连续三个及以上空行压缩成最多两个
        while "\n\n\n" in result:
            result = result.replace("\n\n\n", "\n\n")
        return result.strip()


    @staticmethod
    def _shrink_to_reasonable_reply(text: str, short: bool = False) -> str:
        """
        再做一层基于句子的裁剪：
        - 将文本按中英文句号/问号/感叹号切分成句子；
        - 去掉完全重复的句子；
        - 对短邮件只保留前 1~2 句，对长邮件保留前 3~5 句，避免小模型啰嗦或重复强调。
        """
        if not text:
            return ""
        # 先按行合并成一段，避免换行导致的假句子分割
        merged = " ".join([ln.strip() for ln in text.splitlines() if ln.strip()])
        if not merged:
            return ""

        # 使用正则按句末标点切分（兼容中英文）
        parts = re.split(r"(?<=[。！？!?])\s+|(?<=[\.\?\!])\s+", merged)
        sentences = [p.strip() for p in parts if p and p.strip()]

        if not sentences:
            return merged.strip()

        max_sentences = 2 if short else 5
        seen = set()
        kept = []
        for s in sentences:
            key = s
            if key in seen:
                continue
            seen.add(key)
            kept.append(s)
            if len(kept) >= max_sentences:
                break

        # 中文场景下直接无缝连接，英文则用空格连接，两者混合时也不会太违和
        result = " ".join(kept).strip()

        if short:
            # 对于短邮件回复，再次限制整体长度，避免生成过长段落
            max_len = 80
            if len(result) > max_len:
                # 优先在第一个句号/问号/感叹号后截断
                for ch in "。！？!?.":
                    idx = result.find(ch)
                    if 0 < idx <= max_len:
                        return result[: idx + 1].strip()
                return (result[:max_len] + "…").strip()

        return result or merged.strip()

    @staticmethod
    def _shrink_polish_short(text: str) -> str:
        """
        对很短的待润色内容，只保留润色结果中的第一句，避免模型凭空扩写。
        """
        if not text:
            return ""
        merged = " ".join([ln.strip() for ln in text.splitlines() if ln.strip()])
        if not merged:
            return ""
        for ch in "。！？!?.":
            idx = merged.find(ch)
            if idx != -1:
                return merged[: idx + 1].strip()
        return merged.strip()

    @classmethod
    def reset_instance(cls) -> None:
        """用于测试或切换模型时重置单例。"""
        with cls._lock:
            if cls._instance is not None:
                cls._instance._model = None
                cls._instance._tokenizer = None
                cls._instance._initialized = False
                cls._instance = None
