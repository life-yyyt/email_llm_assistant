# -*- coding: utf-8 -*-
"""
邮件客户端：使用 imaplib、smtplib、email 拉取与发送邮件。
根据 AccountItem 的 IMAP/SMTP 配置连接。
"""

import imaplib
import smtplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import List, Optional
import os
import ssl

from core.account_store import AccountItem
from utils.email_parser import parse_email_message, MailItem


class EmailClient:
    """单账号 IMAP 拉取 + SMTP 发送。"""

    def __init__(self, account: AccountItem):
        self._account = account
        self._imap: Optional[imaplib.IMAP4_SSL] = None
        self._smtp: Optional[smtplib.SMTP] = None

    def _imap_connect(self) -> imaplib.IMAP4_SSL:
        if self._imap is not None:
            try:
                self._imap.noop()
                return self._imap
            except Exception:
                self._imap = None
        ssl_ctx = ssl.create_default_context()
        self._imap = imaplib.IMAP4_SSL(
            self._account.imap_host,
            self._account.imap_port,
            ssl_context=ssl_ctx,
        )
        self._imap.login(self._account.email, self._account.password)
        # 163 等邮箱会检查客户端身份，未识别客户端会返回 "Unsafe Login" 并拒绝访问
        # 发送 IMAP ID（RFC 2971）以通过安全检查
        try:
            if hasattr(self._imap, "id_"):
                self._imap.id_({"name": "EmailLLMAssistant", "version": "1.0"})
        except Exception:
            pass
        return self._imap

    def _format_imap_response(self, data) -> str:
        """把 IMAP 返回的 data 转成可读字符串，便于诊断。"""
        if data is None:
            return ""
        if isinstance(data, (list, tuple)):
            parts = []
            for x in data:
                if isinstance(x, bytes):
                    try:
                        parts.append(x.decode("utf-8", errors="replace"))
                    except Exception:
                        parts.append(repr(x))
                else:
                    parts.append(str(x))
            return " ".join(parts).strip()
        if isinstance(data, bytes):
            try:
                return data.decode("utf-8", errors="replace").strip()
            except Exception:
                return repr(data)
        return str(data).strip()

    def fetch_recent(self, n: int = 50, folder: str = "INBOX") -> List[MailItem]:
        """
        拉取最近 N 封邮件（按 UID 倒序），解析为 MailItem 列表。
        """
        imap = self._imap_connect()
        status, data = imap.select(folder, readonly=True)
        if status != "OK":
            server_msg = self._format_imap_response(data)
            hint = (
                f"无法打开邮箱文件夹 {folder}。\n\n"
                f"服务器返回：{status}" + (f" — {server_msg}" if server_msg else "") + "\n\n"
                "常见原因：\n"
                "1. 未在网页版邮箱中开启 IMAP 服务（设置 → POP3/SMTP/IMAP）；\n"
                "2. 密码填的是登录密码，应使用「客户端授权码/授权码」（163/QQ 等必须在网页生成）；\n"
                "3. 账号或授权码错误、授权码已过期或被重置；\n"
                "4. 163 等邮箱将第三方客户端识别为「不安全登录」并拒绝访问。\n\n"
                "建议：删除本账号后，用刚生成的授权码重新添加；若仍报「Unsafe Login」，可尝试使用网易邮箱大师等官方客户端。"
            )
            raise RuntimeError(hint)

        status, numbers = imap.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("邮箱搜索失败，IMAP 服务器返回错误，可能是 IMAP 未完全开启或服务器暂时不可用。")
        uid_list = numbers[0].split()
        if not uid_list:
            return []
        # 取最后 n 个 UID
        uid_list = uid_list[-n:] if len(uid_list) >= n else uid_list
        uid_list = list(reversed(uid_list))
        result = []
        for uid_b in uid_list:
            try:
                uid = int(uid_b.decode() if isinstance(uid_b, bytes) else uid_b)
                _, data = imap.fetch(uid_b, "(RFC822)")
                if not data or data[0] is None:
                    continue
                raw = data[0][1]
                if isinstance(raw, bytes):
                    item = parse_email_message(uid, raw, message_id_fallback=str(uid))
                else:
                    item = parse_email_message(uid, raw.encode("latin1", errors="replace"), message_id_fallback=str(uid))
                result.append(item)
            except Exception:
                continue
        return result

    def send_mail(
        self,
        to: str,
        subject: str,
        body_plain: str,
        reply_to_message_id: Optional[str] = None,
        attachments: Optional[List[str]] = None,
    ) -> None:
        """发送邮件，支持纯文本正文和可选附件。"""
        has_attachments = bool(attachments)
        msg = MIMEMultipart("mixed" if has_attachments else "alternative")
        msg["Subject"] = subject
        msg["From"] = self._account.email
        msg["To"] = to
        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
            msg["References"] = reply_to_message_id
        msg.attach(MIMEText(body_plain, "plain", "utf-8"))

        # 添加附件
        if has_attachments:
            for path in attachments or []:
                if not path:
                    continue
                try:
                    filename = os.path.basename(path)
                    with open(path, "rb") as f:
                        part = MIMEApplication(f.read(), Name=filename or "attachment")
                    part.add_header("Content-Disposition", "attachment", filename=filename or "attachment")
                    msg.attach(part)
                except Exception:
                    # 附件读取失败时跳过该文件，避免整封邮件发送失败
                    continue

        raw = msg.as_string()

        if self._account.use_ssl and self._account.smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(self._account.smtp_host, self._account.smtp_port, context=ctx) as smtp:
                smtp.login(self._account.email, self._account.password)
                smtp.sendmail(self._account.email, [to], raw)
        else:
            with smtplib.SMTP(self._account.smtp_host, self._account.smtp_port) as smtp:
                smtp.starttls()
                smtp.login(self._account.email, self._account.password)
                smtp.sendmail(self._account.email, [to], raw)

    def disconnect(self) -> None:
        try:
            if self._imap:
                self._imap.logout()
        except Exception:
            pass
        self._imap = None
        self._smtp = None
