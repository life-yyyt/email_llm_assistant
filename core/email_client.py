# -*- coding: utf-8 -*-
"""
邮件客户端：基于 IMAP 拉取邮件，基于 SMTP 发送邮件。
"""

import imaplib
import os
import smtplib
import ssl
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Optional

from core.account_store import AccountItem
from utils.email_parser import MailItem, parse_email_message


class EmailClient:
    """单账号邮件客户端。"""

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
        try:
            self._imap = imaplib.IMAP4_SSL(
                self._account.imap_host,
                self._account.imap_port,
                ssl_context=ssl_ctx,
            )
            self._send_imap_id(self._imap)
            self._imap.login(self._account.email, self._account.password)
            self._send_imap_id(self._imap)
            return self._imap
        except imaplib.IMAP4.error as exc:
            self._imap = None
            raise RuntimeError(self._build_login_error_hint(str(exc))) from exc
        except Exception:
            self._imap = None
            raise

    def _send_imap_id(self, imap: imaplib.IMAP4_SSL) -> None:
        """
        某些邮箱服务会参考 IMAP ID 判断客户端来源，这里尽量补发一次。
        即使发送失败也不影响主流程。
        """
        try:
            if "ID" not in imaplib.Commands:
                imaplib.Commands["ID"] = ("NONAUTH", "AUTH", "SELECTED", "LOGOUT")
            imap._simple_command(
                "ID",
                '("name" "EmailLLMAssistant" "version" "1.0" "vendor" "LocalDesktopClient")',
            )
        except Exception:
            pass

    def _format_imap_response(self, data) -> str:
        """将 IMAP 响应转换为可读字符串。"""
        if data is None:
            return ""
        if isinstance(data, (list, tuple)):
            parts = []
            for item in data:
                if isinstance(item, bytes):
                    parts.append(item.decode("utf-8", errors="replace"))
                else:
                    parts.append(str(item))
            return " ".join(parts).strip()
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace").strip()
        return str(data).strip()

    def _build_login_error_hint(self, server_msg: str) -> str:
        host = (self._account.imap_host or "").lower()
        server_msg = (server_msg or "").strip()

        lines = [
            "邮箱登录失败，无法建立 IMAP 连接。",
            f"服务器返回：{server_msg}" if server_msg else "服务器未返回详细错误信息。",
            "",
            "常见原因：",
            "1. 邮箱地址或密码/授权码填写错误；",
            "2. 对应邮箱尚未开启 IMAP 服务；",
            "3. 第三方客户端登录被服务商拦截；",
        ]

        if "gmail" in host or "google" in host:
            lines.extend(
                [
                    "",
                    "Gmail 排查建议：",
                    "1. 请先在 Gmail 网页端开启 IMAP；",
                    "2. 必须开启 Google 两步验证；",
                    "3. 程序里填写的密码必须是 16 位应用专用密码，而不是 Gmail 登录密码；",
                    "4. 如果刚修改过安全设置，建议重新生成应用专用密码后再绑定；",
                ]
            )
        elif any(token in host for token in ("163", "126", "yeah", "qq")):
            lines.extend(
                [
                    "",
                    "网易/QQ 邮箱排查建议：",
                    "1. 请在网页端开启 IMAP/SMTP；",
                    "2. 请使用客户端授权码，而不是网页登录密码；",
                    "3. 若提示 Unsafe Login，请重新生成授权码后再试；",
                ]
            )

        return "\n".join(lines)

    def _build_folder_error_hint(self, folder: str, status: str, server_msg: str) -> str:
        if "NONAUTH" in (server_msg or "").upper():
            return self._build_login_error_hint(server_msg)

        return (
            f"无法打开邮箱文件夹 {folder}。\n\n"
            f"服务器返回：{status}" + (f" - {server_msg}" if server_msg else "") + "\n\n"
            "建议检查：\n"
            "1. 当前邮箱是否已开启 IMAP；\n"
            "2. 账号密码或授权码是否仍然有效；\n"
            "3. 收件箱名称是否为 INBOX，或服务商是否对默认文件夹做了限制。"
        )

    def fetch_recent(self, n: int = 50, folder: str = "INBOX") -> List[MailItem]:
        """拉取最近 N 封邮件。"""
        imap = self._imap_connect()
        status, data = imap.select(folder, readonly=True)
        if status != "OK":
            server_msg = self._format_imap_response(data)
            raise RuntimeError(self._build_folder_error_hint(folder, status, server_msg))

        status, numbers = imap.search(None, "ALL")
        if status != "OK":
            raise RuntimeError("邮箱搜索失败，IMAP 服务暂不可用或邮箱尚未正确开启 IMAP。")

        uid_list = numbers[0].split()
        if not uid_list:
            return []

        uid_list = uid_list[-n:] if len(uid_list) >= n else uid_list
        uid_list = list(reversed(uid_list))

        result: List[MailItem] = []
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
                    item = parse_email_message(
                        uid,
                        raw.encode("latin1", errors="replace"),
                        message_id_fallback=str(uid),
                    )
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
        """发送邮件，支持正文与附件。"""
        has_attachments = bool(attachments)
        msg = MIMEMultipart("mixed" if has_attachments else "alternative")
        msg["Subject"] = subject
        msg["From"] = self._account.email
        msg["To"] = to

        if reply_to_message_id:
            msg["In-Reply-To"] = reply_to_message_id
            msg["References"] = reply_to_message_id

        msg.attach(MIMEText(body_plain, "plain", "utf-8"))

        if has_attachments:
            for path in attachments or []:
                if not path:
                    continue
                try:
                    filename = os.path.basename(path)
                    with open(path, "rb") as file_obj:
                        part = MIMEApplication(file_obj.read(), Name=filename or "attachment")
                    part.add_header(
                        "Content-Disposition",
                        "attachment",
                        filename=filename or "attachment",
                    )
                    msg.attach(part)
                except Exception:
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
