# -*- coding: utf-8 -*-
"""
本地大模型单例封装：避免重复加载，支持分类（低温度）与生成（可调温度/max_tokens）。
支持 backend: transformers（默认）、ollama。
"""

from typing import Optional, Literal
import hashlib
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

    @staticmethod
    def _project_root() -> str:
        """返回项目根目录。"""
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @classmethod
    def _looks_like_model_dir(cls, path: str) -> bool:
        return os.path.isfile(os.path.join(path, "config.json"))

    @classmethod
    def _looks_like_lora_adapter_dir(cls, path: str) -> bool:
        return os.path.isfile(os.path.join(path, "adapter_config.json"))

    @classmethod
    def _resolve_model_path(cls, model_path: Optional[str]) -> Optional[str]:
        """
        解析模型目录：
        - 优先使用显式传入路径，其次使用 LLAMA_MODEL_PATH；
        - 支持绝对路径、相对项目根目录路径、models/ 子目录、lora/ 子目录；
        - 若路径指向 LoRA adapter，则直接给出清晰错误，引导先合并模型。
        """
        raw_path = (model_path or os.environ.get("LLAMA_MODEL_PATH") or DEFAULT_MODEL_NAME or "").strip()
        if not raw_path:
            return None

        project_root = cls._project_root()
        candidates = []
        if os.path.isabs(raw_path):
            candidates.append(raw_path)
        else:
            candidates.extend(
                [
                    raw_path,
                    os.path.join(project_root, raw_path),
                    os.path.join(project_root, "models", raw_path),
                    os.path.join(project_root, "lora", raw_path),
                ]
            )

        seen = set()
        normalized_candidates = []
        for candidate in candidates:
            abs_candidate = os.path.normpath(os.path.abspath(candidate))
            if abs_candidate not in seen:
                seen.add(abs_candidate)
                normalized_candidates.append(abs_candidate)

        adapter_dir = None
        for candidate in normalized_candidates:
            if not os.path.isdir(candidate):
                continue
            if cls._looks_like_model_dir(candidate):
                return candidate
            if cls._looks_like_lora_adapter_dir(candidate):
                adapter_dir = candidate

        if adapter_dir:
            raise RuntimeError(
                "当前模型路径指向的是 LoRA 适配器目录，而不是可直接推理的完整模型目录：\n"
                f"  {adapter_dir}\n\n"
                "请先运行 lora/merge_lora.py 合并 LoRA 适配器，再将 LLAMA_MODEL_PATH 指向合并后的模型目录。"
            )

        return normalized_candidates[0]

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
        self._model_path = self._resolve_model_path(model_path)
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
            gen_kwargs = dict(
                **inputs,
                max_new_tokens=max_tokens,
                pad_token_id=self._tokenizer.eos_token_id,
            )
            if temperature > 0:
                gen_kwargs["do_sample"] = True
                gen_kwargs["temperature"] = max(0.01, temperature)
                gen_kwargs["top_p"] = 0.9
                gen_kwargs["repetition_penalty"] = 1.15
            else:
                gen_kwargs["do_sample"] = False
            out = self._model.generate(**gen_kwargs)
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
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                        "top_p": 0.9,
                        "repeat_penalty": 1.15,
                    },
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
            cache_key = hashlib.md5(f"{prompt}|{temperature}|{max_tokens}".encode("utf-8")).hexdigest()
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

    REPLY_FEW_SHOT = {
        "问候": (
            "示例：\n"
            "来信：你好，晚上吃饭了吗？\n"
            "回复：吃过了，谢谢关心，你呢？\n"
            "来信：在吗？看到邮件后回复我一下。\n"
            "回复：在的，刚看到邮件，您请说。\n\n"
        ),
        "确认": (
            "示例：\n"
            "来信：您好，请确认您明天下午三点是否方便参加项目讨论会。\n"
            "回复：您好，可以参加，明天下午三点我会准时到会。\n"
            "来信：请确认一下本周五前是否可以完成初稿。\n"
            "回复：您好，可以的，我会按时完成初稿。\n\n"
        ),
        "查收": (
            "示例：\n"
            "来信：我刚把合同和报价单发给您了，麻烦您查收后回复一下。\n"
            "回复：您好，已收到合同和报价单，我会尽快查看并回复您。\n"
            "来信：进度报告已发您邮箱，请查收附件并确认。\n"
            "回复：您好，附件已收到，我先查看，稍后给您反馈。\n\n"
        ),
        "处理": (
            "示例：\n"
            "来信：系统这边还有一个报错没有解决，请你今天内处理一下并同步结果。\n"
            "回复：好的，我今天内处理完后同步结果给您。\n"
            "来信：这个问题比较急，麻烦您尽快跟进处理。\n"
            "回复：好的，我会尽快跟进处理，有进展及时回复您。\n\n"
        ),
        "感谢": (
            "示例：\n"
            "来信：今天的事情多亏你帮忙，辛苦啦。\n"
            "回复：不客气，举手之劳，有需要随时找我。\n"
            "来信：感谢你这次的支持，项目推进顺利多了。\n"
            "回复：不客气，很高兴能帮上忙，后续有需要随时联系我。\n\n"
        ),
        "审批": (
            "示例：\n"
            "来信：我下周一需要请一天事假，已经在OA系统提交了申请，请您审批一下。\n"
            "回复：好的，我会尽快审批，请提前做好工作交接。\n"
            "来信：报销流程已经提交，麻烦您有空审批一下。\n"
            "回复：好的，我会尽快处理审批，如有需要再和您确认。\n\n"
        ),
        "安排": (
            "示例：\n"
            "来信：想跟你沟通一下下个季度的合作计划，方便时回复。\n"
            "回复：好的，我看一下安排，稍后回复您具体时间。\n"
            "来信：这周方便约个时间电话沟通一下方案吗？\n"
            "回复：好的，我确认一下时间安排，稍后回复您。\n\n"
        ),
        "默认": (
            "示例：\n"
            "来信：麻烦您看到邮件后回复一下。\n"
            "回复：您好，邮件已收到，我会尽快处理。\n"
            "来信：请您先看一下这封邮件，方便时给我个反馈。\n"
            "回复：您好，邮件已收到，我先查看，稍后给您反馈。\n\n"
        ),
    }

    POLISH_FEW_SHOT = {
        "自然": (
            "示例：\n"
            "原文：我已经看了你发的内容，整体没什么问题，就是个别地方还得改一下，改完再给我就行。\n"
            "润色后：我已经看过你发来的内容了，整体没什么问题，个别地方再调整一下就可以，改完后再发我即可。\n"
            "原文：这个我先看下，晚点回你。\n"
            "润色后：这个我先看一下，晚些时候回复你。\n\n"
        ),
        "正式": (
            "示例：\n"
            "原文：资料我看过了，基本没问题，你们改一下细节再发我。\n"
            "润色后：相关资料已查阅，整体上基本没有问题。请对细节部分再做完善后发送给我。\n"
            "原文：这个事情比较急，请你尽快处理一下。\n"
            "润色后：此事较为紧急，请您尽快处理。\n\n"
        ),
        "商务": (
            "示例：\n"
            "原文：报价我收到了，你们先按这个推进，后面有变化我再告诉你。\n"
            "润色后：报价已收到，现阶段可先按照该方案推进。如后续有调整，我会及时与您沟通。\n"
            "原文：我们觉得这个价格有点高，能不能再优惠一些。\n"
            "润色后：经评估，我方认为当前报价略高，能否再给予一定优惠。\n\n"
        ),
    }

    def classify_spam(self, subject: str, body: str, use_cache: bool = True) -> str:
        """垃圾邮件二分类，低温度稳定输出。返回「正常邮件」或「垃圾邮件」。"""
        subject = (subject or "").strip()
        body_trim = (body or "").strip()
        rule_label = self._classify_spam_by_rule(subject, body_trim)
        if rule_label:
            return rule_label
        text = f"主题：{subject}\n正文：{body}"[:1500]
        prompt = self.SPAM_PROMPT + text
        out = self.generate(prompt, temperature=0.1, max_tokens=16, use_cache=use_cache)
        out = out.strip()
        if "垃圾邮件" in out:
            return "垃圾邮件"
        return "正常邮件"

    def generate_reply(self, subject: str, body: str, use_cache: bool = False) -> str:
        """
        根据收到的邮件生成自动回复。
        模式明确的常见邮件优先使用规则回复，避免小模型跑偏；
        仅对不易规则覆盖的邮件再走 LLM 生成。
        """
        body_trim = self._sanitize_body_for_reply(body)
        subject = subject or ""
        if self._looks_like_spam_by_rule(subject, body_trim):
            return "这封邮件疑似垃圾邮件，建议不要回复。"
        mode = self._detect_reply_mode(subject, body_trim)

        preset_reply = self._rule_based_reply(mode, subject, body_trim)
        prefer_default_rule = any(
            k in body_trim for k in ("给我个反馈", "回复一下", "收到请回", "看到邮件后回复", "方便时给我个反馈")
        )
        if preset_reply and (mode != "默认" or prefer_default_rule):
            return preset_reply

        email_content = f"邮件主题：{subject}\n邮件正文：{body_trim[:900]}"
        example = self.REPLY_FEW_SHOT.get(mode, self.REPLY_FEW_SHOT["默认"])

        prompt = (
            "你是邮件回复助手。请写一段可以直接发送的邮件回复。\n"
            "要求：\n"
            "1. 只回复邮件本身，不新增事实、附件、承诺或具体时间。\n"
            "2. 语气自然、礼貌、像真人，不要像模板。\n"
            "3. 一般 1 到 2 句，必要时最多 3 句。\n"
            "4. 不要分析邮件，不要复述原文，不要写“根据来信”“我无法访问邮件”等话。\n"
            "5. 只输出最终回复正文，不要加任何前缀或标签。\n\n"
            f"当前邮件类型：{mode}\n"
            f"{example}"
            f"收到的邮件：\n{email_content}\n\n"
            "最终回复：\n"
        )
        raw = self.generate(prompt, temperature=0.3, max_tokens=96, use_cache=use_cache)
        cleaned = self._clean_reply_output(self._dedup_repeated_lines(raw))
        if not cleaned:
            fallback = self._rule_based_reply(mode, subject, body_trim)
            if fallback:
                return fallback
            return "您好，邮件已收到，我会尽快处理。"
        return self._shrink_to_reasonable_reply(cleaned, short=False)

    _POLISH_STYLE_BLOCKS = {
        "自然": (
            "- 风格：自然。\n"
            "- 语气轻松、自然，像和熟悉同事或朋友沟通，可以适度口语化。\n"
            "- 重点是通顺好读、亲切真实，不要太官方。\n"
        ),
        "正式": (
            "- 风格：正式。\n"
            "- 用词规范、严谨，语气庄重有礼，适合公文、通知、正式工作邮件。\n"
            "- 句式完整，避免口语和网络用语。\n"
        ),
        "商务": (
            "- 风格：商务。\n"
            "- 表达专业、简洁、有条理，适合与客户、合作伙伴、供应商等的商务往来。\n"
            "- 突出关键信息、时间、金额、行动项，语气礼貌但不过多铺垫。\n"
        ),
    }

    def polish_email(self, content: str, style: str = "自然", use_cache: bool = False) -> str:
        """润色邮件正文。style 可选：自然、正式、商务。稳定性优先，正式/商务以规则润色为主。"""
        trimmed = (content or "").strip()
        email_content = trimmed[:3000]

        style = (style or "自然").strip()
        if style not in ("自然", "正式", "商务"):
            style = "自然"

        rule_polished = self._rule_based_polish(trimmed, style)
        if style in ("正式", "商务"):
            return rule_polished
        if len(trimmed) <= 80 and rule_polished:
            return rule_polished

        style_block = self._POLISH_STYLE_BLOCKS.get(style, self._POLISH_STYLE_BLOCKS["自然"])

        prompt = (
            "你是邮件润色助手，请把下面内容润色成更适合直接发送的邮件正文。\n"
            f"风格：{style}\n"
            f"{style_block}"
            f"{self.POLISH_FEW_SHOT.get(style, '')}"
            "要求：\n"
            "1. 保持原意，不新增事实、请求、承诺或附件信息。\n"
            "2. 只改表达，让句子更通顺、得体，符合所选风格。\n"
            "3. 尽量保持篇幅接近，原文已经顺时只做轻微优化。\n"
            "4. 只输出润色后的正文，不要解释，不要标题，不要多个版本。\n\n"
            f"原文：\n{email_content[:1000]}\n\n"
            "润色后：\n"
        )
        length = len(trimmed)
        if length <= 200:
            max_tokens = 96
        elif length <= 800:
            max_tokens = 180
        else:
            max_tokens = 260
        raw = self.generate(prompt, temperature=0.2, max_tokens=max_tokens, use_cache=use_cache)
        cleaned = self._clean_polish_output(self._dedup_repeated_lines(raw))
        if self._looks_like_bad_polish(trimmed, cleaned):
            cleaned = rule_polished
        if length <= 30:
            return self._shrink_polish_short(cleaned)
        return cleaned

    @staticmethod
    def _detect_reply_mode(subject: str, body: str) -> str:
        text = f"{subject}\n{body}".lower()
        if any(k in text for k in ("收到", "查收", "收悉", "附件", "报价单", "合同")):
            return "查收"
        if any(k in text for k in ("吃饭了吗", "在吗", "忙吗", "最近怎么样", "你好", "您好呀", "最近还好吗")):
            return "问候"
        if any(k in text for k in ("审批", "oa", "请假", "申请", "报销", "签字")):
            return "审批"
        if any(k in text for k in ("沟通", "合作计划", "排期", "方便时回复", "约个时间", "对接", "电话沟通", "安排一下")):
            return "安排"
        if any(k in text for k in ("给我个反馈", "回复一下", "收到请回", "看到邮件后回复", "稍后反馈")):
            return "默认"
        if any(k in text for k in ("确认", "是否", "方便", "参加", "可以吗", "能否", "确认一下", "请确认")):
            return "确认"
        if any(k in text for k in ("处理", "尽快", "修复", "今天内", "同步结果", "麻烦你", "麻烦您", "跟进")):
            return "处理"
        if any(k in text for k in ("辛苦", "谢谢", "感谢", "多亏", "麻烦了")):
            return "感谢"
        return "默认"

    @staticmethod
    def _extract_time_phrase(text: str) -> str:
        hour = r"(?:\d{1,2}|[一二三四五六七八九十两]{1,3})"
        minute = r"(?:半|[一二三四五六七八九十两\d]{1,3}分)?"
        patterns = [
            rf"(明天(?:上午|下午|晚上)?{hour}点{minute})",
            rf"(今天(?:上午|下午|晚上)?{hour}点{minute})",
            rf"((?:上午|下午|晚上){hour}点{minute})",
            rf"(\d{{1,2}}月\d{{1,2}}日(?:上午|下午|晚上)?{hour}点{minute})",
        ]
        for pattern in patterns:
            m = re.search(pattern, text)
            if m:
                return m.group(1)
        return ""

    @classmethod
    def _rule_based_reply(cls, mode: str, subject: str, body: str) -> str:
        body = (body or "").strip()
        if not body:
            return ""
        merged_text = f"{subject}\n{body}"
        time_phrase = cls._extract_time_phrase(merged_text)
        if mode == "确认":
            if time_phrase:
                return f"您好，可以参加，{time_phrase}我会准时到会。"
            if any(k in merged_text for k in ("初稿", "提交", "完成")):
                return "您好，可以的，我会按时完成并及时提交。"
            if any(k in body for k in ("参加", "开会", "会议", "讨论会")):
                return "您好，可以参加，我会准时到会。"
            return "您好，可以的，我会按要求配合。"
        if mode == "查收":
            if any(k in merged_text for k in ("合同", "报价单", "报价")):
                return "您好，合同和相关资料已收到，我先核对，稍后回复您。"
            if any(k in merged_text for k in ("附件", "资料", "文档", "报告")):
                return "您好，附件已收到，我先查看，稍后给您反馈。"
            return "您好，已收到，我会尽快查看并回复您。"
        if mode == "问候":
            if "吃饭了吗" in body:
                return "吃过了，谢谢关心，你呢？"
            if any(k in body for k in ("最近怎么样", "最近还好吗")):
                return "最近挺好的，谢谢关心，也祝您一切顺利。"
            if any(k in body for k in ("在吗", "忙吗")):
                return "在的，刚看到邮件，您请说。"
            return "您好，收到您的来信，很高兴和您联系。"
        if mode == "审批":
            if any(k in body for k in ("请假", "OA", "oa", "申请")):
                return "好的，我会尽快审批，请提前做好工作交接。"
            if any(k in body for k in ("报销", "签字")):
                return "好的，我会尽快处理审批，如有需要再和您确认。"
            return "好的，我会尽快处理审批事项。"
        if mode == "安排":
            if any(k in merged_text for k in ("电话", "沟通", "会议", "约个时间")):
                return "好的，我确认一下时间安排，稍后回复您。"
            return "好的，我看一下安排，稍后回复您具体时间。"
        if mode == "处理":
            if "今天内" in merged_text:
                return "好的，我会今天内处理，并及时同步结果。"
            if any(k in merged_text for k in ("尽快", "加急", "跟进")):
                return "好的，我会尽快跟进处理，有进展及时回复您。"
            return "好的，我会尽快处理，并在完成后同步结果。"
        if mode == "感谢":
            if any(k in merged_text for k in ("辛苦", "支持")):
                return "不客气，很高兴能帮上忙，后续有需要随时联系我。"
            return "不客气，这是我应该做的。"
        if "问候" in body or any(k in body for k in ("你好", "您好", "在吗")):
            return "您好，收到您的邮件。"
        if any(k in merged_text for k in ("回复一下", "看到后回复", "收到请回", "给我个反馈")):
            return "您好，邮件已收到，我先查看，稍后给您反馈。"
        if any(k in merged_text for k in ("方便时回复", "有空回复")):
            return "好的，我看到后会尽快回复您。"
        return "您好，邮件已收到，我会尽快查看并回复您。"

    @staticmethod
    def _count_hits(text: str, keywords) -> int:
        return sum(1 for k in keywords if k and k in text)

    @classmethod
    def _classify_spam_by_rule(cls, subject: str, body: str) -> Optional[str]:
        subject = (subject or "").strip()
        body = (body or "").strip()
        text = f"{subject}\n{body}".strip()
        if not text:
            return "正常邮件"

        subject_lower = subject.lower()
        body_lower = body.lower()
        text_lower = text.lower()

        strong_spam_subject = (
            "<广告>", "广告", "推广", "促销", "优惠券", "限时优惠", "抽奖", "领奖",
            "free", "sale", "deal", "discount", "offer", "gift card", "apple gift card",
        )
        spam_keywords = (
            "点击链接", "立即领取", "退订", "订阅", "优惠", "注册", "中奖", "抽奖",
            "返现", "领券", "活动价", "专享价", "低至", "仅限今日", "立即抢购",
            "unsubscribe", "click", "buy now", "promo", "promotion", "gift card", "claim your", "reward",
        )
        normal_keywords = (
            "请查收", "附件", "进度报告", "合同", "报价单", "处理一下", "同步结果",
            "项目", "会议", "方案", "需求", "审批", "请假", "工作交接",
            "确认", "回复一下", "反馈", "沟通", "安排", "电话沟通", "报销",
            "老师", "同学", "您好", "你好", "在吗", "辛苦", "感谢", "支持",
            "初稿", "文档", "资料", "邮件已收到", "报错", "跟进处理", "完成后同步结果",
        )

        spam_score = 0
        normal_score = 0

        spam_score += cls._count_hits(subject, strong_spam_subject) * 3
        spam_score += cls._count_hits(text, spam_keywords)
        normal_score += cls._count_hits(text, normal_keywords)

        if any(k in text for k in ("http://", "https://", "www.")):
            spam_score += 1
        if sum(1 for k in ("http://", "https://", "www.") if k in text) >= 2:
            spam_score += 1

        if any(k in text for k in ("退订请回复", "回复TD", "点击下方链接", "扫码领取", "立即注册")):
            spam_score += 3
        if any(k in text_lower for k in ("gift card", "claim your", "buy now", "limited offer")):
            spam_score += 2

        if len(subject) <= 2 and len(body) < 200 and spam_score == 0:
            normal_score += 2

        if any(k in text for k in ("你好", "您好", "在吗", "吃饭了吗", "最近怎么样")) and len(body) <= 120:
            normal_score += 3

        if any(k in text for k in ("合同", "报价单", "进度报告", "查收附件", "项目讨论会", "工作交接")):
            normal_score += 3
        if "报销" in text and "审批" in text:
            normal_score += 3
        if "报错" in text and any(k in text for k in ("处理", "同步结果", "跟进")):
            normal_score += 3

        if spam_score >= 4 and spam_score >= normal_score + 2:
            return "垃圾邮件"
        if normal_score >= 3 and normal_score >= spam_score + 1:
            return "正常邮件"
        return None

    @classmethod
    def _looks_like_spam_by_rule(cls, subject: str, body: str) -> bool:
        return cls._classify_spam_by_rule(subject, body) == "垃圾邮件"

    @staticmethod
    def _clean_reply_output(text: str) -> str:
        if not text:
            return ""
        if text.startswith("[Ollama 调用失败:"):
            return ""
        text = re.sub(r"mailto:[^\s]+", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "", text)
        if any(token in text for token in ("来信：", "邮件正文：", "收到的邮件：", "以下是回复")):
            return ""
        lines = []
        bad_prefixes = (
            "根据", "意图", "语气", "需要动作", "回复策略", "分析", "说明", "来信：", "邮件正文：",
            "最终回复", "回复：", "答复：", "邮件类型", "类型：", "我将在此回复如下",
        )
        bad_contains = (
            "我无法访问邮件", "我无法直接访问", "根据当前来信", "根据上述分析",
            "意图是", "回复策略", "作为邮件回复助手", "作为AI",
        )
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            if any(s.startswith(prefix) for prefix in bad_prefixes):
                continue
            if any(token in s for token in bad_contains):
                continue
            lines.append(s)
        return " ".join(lines).strip()

    @staticmethod
    def _sanitize_body_for_reply(text: str) -> str:
        """清掉地址和明显签名，避免小模型把它们当成正文回复。"""
        s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"mailto:[^\s]+", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", "", s)
        cleaned_lines = []
        for line in s.splitlines():
            line = line.strip()
            if not line:
                if cleaned_lines and cleaned_lines[-1] != "":
                    cleaned_lines.append("")
                continue
            if re.fullmatch(r"[_\-\s]{2,}", line):
                continue
            if cleaned_lines and len(line) <= 12 and re.fullmatch(r"[\u4e00-\u9fa5A-Za-z0-9_.·]+", line):
                continue
            cleaned_lines.append(line)
        return "\n".join(cleaned_lines).strip()

    @staticmethod
    def _clean_polish_output(text: str) -> str:
        if not text:
            return ""
        if text.startswith("[Ollama 调用失败:"):
            return ""
        lines = []
        bad_prefixes = ("润色后：", "修改后：", "优化后：", "正式版：", "商务版：", "自然版：")
        bad_contains = ("以下是", "润色后的版本", "修改说明", "作为邮件润色助手")
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            for prefix in bad_prefixes:
                if s.startswith(prefix):
                    s = s[len(prefix):].strip()
            if not s:
                continue
            if any(token in s for token in bad_contains):
                continue
            lines.append(s)
        return "\n".join(lines).strip()

    @staticmethod
    def _looks_like_bad_polish(source: str, output: str) -> bool:
        if not output:
            return True
        if output.startswith("[Ollama 调用失败:"):
            return True
        bad_phrases = (
            "我已经看过你发来的内容了",
            "整体没什么问题",
            "个别地方再调整一下就可以",
            "发回说好的",
            "这件事我了解了",
        )
        if any(p in output for p in bad_phrases) and not any(p in source for p in bad_phrases):
            return True
        if len(output) > max(len(source) * 2, len(source) + 80):
            return True
        return False

    @staticmethod
    def _rule_based_polish(text: str, style: str) -> str:
        s = (text or "").strip()
        if not s:
            return ""

        short_reply_map = {
            "自然": {
                "收到": "收到，稍后回复你。",
                "好的": "好的，我这边先处理一下。",
                "谢谢": "谢谢你，辛苦了。",
                "已收到": "已经收到了，我先看一下。",
                "明白了": "明白了，我先处理一下。",
                "行": "行，我知道了。",
                "辛苦了": "辛苦了，谢谢你。",
                "好的收到": "好的，已经收到啦。",
            },
            "正式": {
                "收到": "已收到，感谢您的来信。",
                "好的": "好的，我会尽快处理。",
                "谢谢": "感谢您的支持。",
                "已收到": "已收到，我会尽快查看并回复您。",
                "明白了": "已知悉，我会按要求处理。",
                "行": "好的，我已了解。",
                "辛苦了": "辛苦了，感谢您的配合。",
                "好的收到": "好的，已收到，我会尽快处理。",
            },
            "商务": {
                "收到": "已收到，感谢您的来信，我会尽快查看并回复您。",
                "好的": "好的，我会尽快跟进处理。",
                "谢谢": "感谢您的支持，后续保持沟通。",
                "已收到": "已收到，我会尽快确认并向您反馈。",
                "明白了": "已知悉，我会尽快跟进处理。",
                "行": "好的，我这边已了解。",
                "辛苦了": "辛苦了，感谢贵方配合。",
                "好的收到": "好的，已收到，我会尽快确认并反馈。",
            },
        }
        if len(s) <= 6:
            mapped = short_reply_map.get(style, {}).get(s)
            if mapped:
                return mapped

        if style == "自然":
            replacements_natural = [
                ("看了", "看过"),
                ("发的内容", "发来的内容"),
                ("没啥问题", "没什么问题"),
                ("改一下", "调整一下"),
                ("再给我", "再发我"),
                ("就行", "即可"),
                ("回你", "回复你"),
                ("晚点", "晚些时候"),
                ("先看下", "先看一下"),
                ("辛苦你了", "辛苦了"),
                ("这个事情", "这件事"),
                ("给我个反馈", "给我一个反馈"),
            ]
            for old, new in replacements_natural:
                s = s.replace(old, new)
            s = s.replace("改完再发我即可", "改完后再发我即可")
            s = s.replace("行不行", "可以吗")
            s = s.replace("好的收到", "好的，已经收到了")
            return s

        if style == "正式":
            if "这个我先看下，晚点回你" in s:
                s = s.replace("这个我先看下，晚点回你", "该事项我先查看，稍后回复您")
            if "我这边没问题，你们继续推进就行" in s:
                s = s.replace("我这边没问题，你们继续推进就行", "我方暂无异议，贵方可继续推进")
            if "麻烦你们先看下这个方案，有结果给我个反馈" in s:
                s = s.replace("麻烦你们先看下这个方案，有结果给我个反馈", "烦请贵方先查看该方案，并在有结果后及时反馈")
            if "你们改一下细节再发我" in s:
                s = s.replace("你们改一下细节再发我", "请对细节部分进一步完善后发送给我")
            if "你们改一下细节" in s:
                s = s.replace("你们改一下细节", "请对细节部分进一步完善")
            if "资料我看过了" in s:
                s = s.replace("资料我看过了", "相关资料我已查阅")
            if "基本没问题" in s:
                s = s.replace("基本没问题", "整体上基本没有问题")
            if "没什么问题" in s:
                s = s.replace("没什么问题", "未发现明显问题")
            s = s.replace("这个事情", "此事")
            s = s.replace("这个价格", "当前价格")
            s = s.replace("比较急", "较为紧急")
            s = s.replace("麻烦你", "烦请您")
            s = s.replace("麻烦你们", "烦请贵方")
            s = s.replace("收到后跟我说一下", "收到后请告知我")
            s = s.replace("尽快给我回个消息", "请尽快回复")
            s = s.replace("给我个反馈", "向我反馈")
            s = s.replace("你们", "贵方")
            s = s.replace("请你", "请您")
            s = s.replace("你", "您")
            s = s.replace("处理一下", "处理")
            s = s.replace("改一下细节", "对细节部分进一步完善")
            s = s.replace("再发我", "发送给我")
            s = s.replace("就行", "即可")
            s = s.replace("能不能", "是否可以")
            s = s.replace("您们", "贵方")
            if not s.endswith(("。", "！", "？")):
                s += "。"
            return s

        if "这个我先看下，晚点回你" in s:
            s = s.replace("这个我先看下，晚点回你", "相关内容我先查看，稍后向您回复")
        if "我这边没问题，你们继续推进就行" in s:
            s = s.replace("我这边没问题，你们继续推进就行", "我方当前没有异议，贵方可继续推进")
        if "麻烦你们先看下这个方案，有结果给我个反馈" in s:
            s = s.replace("麻烦你们先看下这个方案，有结果给我个反馈", "烦请贵方先查看该方案，如有进展请及时给予反馈")
        if "资料我看过了" in s:
            s = s.replace("资料我看过了", "相关资料我已审阅")
        if "基本没问题" in s:
            s = s.replace("基本没问题", "整体上没有明显问题")
        if "报价我收到了" in s:
            s = s.replace("报价我收到了", "报价已收到")
        if "你们先按这个推进" in s:
            s = s.replace("你们先按这个推进", "现阶段可先按照该方案推进")
        s = s.replace("我们觉得", "经评估，我方认为")
        s = s.replace("有点高", "略高")
        s = s.replace("能不能", "能否")
        s = s.replace("再优惠一些", "再给予一定优惠")
        s = s.replace("后面有变化我再告诉你", "如后续有调整，我会再及时与您沟通")
        s = s.replace("麻烦你们", "烦请贵方")
        s = s.replace("给我个反馈", "给予反馈")
        s = s.replace("看下", "查看")
        s = s.replace("安排一下", "协调安排")
        s = s.replace("请你尽快处理一下", "烦请尽快处理")
        s = s.replace("请您尽快处理", "烦请尽快处理")
        s = s.replace("有结果给予反馈", "如有进展，请及时给予反馈")
        s = s.replace("再发我", "发送给我")
        s = s.replace("你们", "贵方")
        s = s.replace("就行", "即可")
        if not s.endswith(("。", "！", "？")):
            s += "。"
        return s

    @staticmethod
    def _dedup_repeated_lines(text: str) -> str:
        """去掉连续的重复句子/行，并压缩多余空行。"""
        if not text:
            return ""
        lines = text.splitlines()
        out = []
        prev_non_empty = None
        for line in lines:
            stripped = line.strip()
            if stripped and prev_non_empty is not None and stripped == prev_non_empty:
                continue
            out.append(line)
            if stripped:
                prev_non_empty = stripped
        result = "\n".join(out)
        while "\n\n\n" in result:
            result = result.replace("\n\n\n", "\n\n")
        return result.strip()

    @staticmethod
    def _shrink_to_reasonable_reply(text: str, short: bool = False) -> str:
        """
        基于句子的裁剪：去重复句，限制句数，避免小模型啰嗦。
        short=True 时最多 2 句 80 字，short=False 时最多 4 句 150 字。
        """
        if not text:
            return ""
        merged = " ".join([ln.strip() for ln in text.splitlines() if ln.strip()])
        if not merged:
            return ""

        parts = re.split(r"(?<=[。！？!?])\s*|(?<=[\.\?\!])\s+", merged)
        sentences = [p.strip() for p in parts if p and p.strip()]

        if not sentences:
            return merged.strip()

        max_sentences = 2 if short else 4
        seen = set()
        kept = []
        for s in sentences:
            if s in seen:
                continue
            seen.add(s)
            kept.append(s)
            if len(kept) >= max_sentences:
                break

        result = "".join(kept).strip()

        max_len = 80 if short else 150
        if len(result) > max_len:
            for ch in "。！？!?.":
                idx = result.find(ch)
                if 0 < idx <= max_len:
                    return result[: idx + 1].strip()
            return (result[:max_len] + "…").strip()

        return result or merged.strip()

    @staticmethod
    def _shrink_polish_short(text: str) -> str:
        """对很短的待润色内容，只保留润色结果中的前两句，避免模型凭空扩写。"""
        if not text:
            return ""
        merged = " ".join([ln.strip() for ln in text.splitlines() if ln.strip()])
        if not merged:
            return ""
        count = 0
        for i, ch in enumerate(merged):
            if ch in "。！？!?.":
                count += 1
                if count >= 2:
                    return merged[: i + 1].strip()
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
