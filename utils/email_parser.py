# -*- coding: utf-8 -*-
"""
邮件解析：从 raw message 解析发件人、主题、时间、正文。
优先 text/plain，其次 text/html 转纯文本。
"""

import email
from email.header import decode_header
from datetime import datetime
from typing import Optional, List
import re

from dataclasses import dataclass


@dataclass
class AttachmentInfo:
    """邮件附件的元信息与内容。"""
    filename: str
    content_type: str
    size: int
    payload: bytes


@dataclass
class MailItem:
    """单封邮件的结构化数据。"""
    uid: Optional[int]
    message_id: str
    sender: str
    subject: str
    date_str: str
    body_plain: str
    body_html: str
    attachments: Optional[List[AttachmentInfo]] = None
    links: Optional[List[str]] = None
    raw_message: Optional[object] = None

    def get_display_body(self) -> str:
        """优先返回纯文本正文，否则返回 strip 后的 html 文本。"""
        if self.body_plain and self.body_plain.strip():
            return self.body_plain.strip()
        return _html_to_plain(self.body_html).strip() if self.body_html else ""


def _decode_mime_header(header: Optional[str]) -> str:
    """解码 MIME 编码的邮件头。"""
    if not header:
        return ""
    try:
        parts = decode_header(header)
        result = []
        for part, charset in parts:
            if isinstance(part, bytes):
                result.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                result.append(str(part))
        return "".join(result).strip()
    except Exception:
        return str(header) if header else ""


def _parse_date(msg: email.message.Message) -> str:
    """解析 Date 头为可读字符串。"""
    raw = msg.get("Date") or ""
    if not raw:
        return ""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(raw)
        return dt.strftime("%Y-%m-%d %H:%M") if dt else raw
    except Exception:
        return raw


def _html_to_plain(html: str) -> str:
    """简单将 HTML 转成纯文本。"""
    if not html:
        return ""
    # 去掉 script/style
    html = re.sub(r"<script[^>]*>[\s\S]*?</script>", "", html, flags=re.I)
    html = re.sub(r"<style[^>]*>[\s\S]*?</style>", "", html, flags=re.I)
    # 块级换行
    html = re.sub(r"</(p|div|br|tr|li)[^>]*>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_body_from_message(msg: email.message.Message):
    """
    从 Message 提取 text/plain、text/html 与附件。
    返回 (plain, html, attachments)。
    """
    plain, html = "", ""
    attachments: List[AttachmentInfo] = []
    for part in msg.walk():
        ctype = part.get_content_type()
        disp = (part.get("Content-Disposition") or "").lower()
        is_attachment = "attachment" in disp or part.get_filename()

        if ctype == "text/plain" and not is_attachment:
            try:
                raw = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                plain = (raw or b"").decode(charset, errors="replace")
            except Exception:
                pass
        elif ctype == "text/html" and not is_attachment:
            try:
                raw = part.get_payload(decode=True)
                charset = part.get_content_charset() or "utf-8"
                html = (raw or b"").decode(charset, errors="replace")
            except Exception:
                pass
        elif is_attachment:
            try:
                filename = part.get_filename() or "附件"
                filename = _decode_mime_header(filename)
                payload = part.get_payload(decode=True) or b""
                attachments.append(
                    AttachmentInfo(
                        filename=filename or "附件",
                        content_type=ctype,
                        size=len(payload),
                        payload=payload,
                    )
                )
            except Exception:
                continue

    # 若整封邮件是单 part
    if not plain and not html and msg.get_content_maintype() == "text":
        try:
            raw = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or "utf-8"
            s = (raw or b"").decode(charset, errors="replace")
            if msg.get_content_subtype() == "html":
                html = s
            else:
                plain = s
        except Exception:
            pass
    return plain, html, attachments


def _extract_links(text: str) -> List[str]:
    """从文本中提取 URL 列表。"""
    if not text:
        return []
    # 简单 URL 匹配
    pattern = re.compile(r"(https?://[^\s<>\"]+)", re.IGNORECASE)
    seen = set()
    result: List[str] = []
    for m in pattern.finditer(text):
        url = m.group(1).strip()
        if url and url not in seen:
            seen.add(url)
            result.append(url)
    return result


def parse_email_message(uid: Optional[int], raw_bytes: bytes, message_id_fallback: str = "") -> MailItem:
    """
    解析一封邮件的 raw 字节为 MailItem。
    :param uid: IMAP UID（可选）
    :param raw_bytes: 原始邮件字节
    :param message_id_fallback: 无 Message-ID 时的默认值
    """
    msg = email.message_from_bytes(raw_bytes)
    sender = _decode_mime_header(msg.get("From") or "")
    subject = _decode_mime_header(msg.get("Subject") or "")
    date_str = _parse_date(msg)
    message_id = (msg.get("Message-ID") or message_id_fallback or "").strip()
    plain, html, attachments = _get_body_from_message(msg)
    links = _extract_links(plain + "\n" + _html_to_plain(html))
    return MailItem(
        uid=uid,
        message_id=message_id,
        sender=sender,
        subject=subject,
        date_str=date_str,
        body_plain=plain,
        body_html=html,
        attachments=attachments or None,
        links=links or None,
        raw_message=msg,
    )
