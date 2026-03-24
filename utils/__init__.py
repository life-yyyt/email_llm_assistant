# -*- coding: utf-8 -*-
"""工具包：邮件解析、缓存等。"""

from .email_parser import parse_email_message, MailItem
from .cache import SimpleCache

__all__ = ["parse_email_message", "MailItem", "SimpleCache"]
