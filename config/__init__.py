# -*- coding: utf-8 -*-
"""配置包：邮箱服务器映射、应用常量等。"""

from .email_servers import EMAIL_SERVERS, get_imap_smtp_config

__all__ = ["EMAIL_SERVERS", "get_imap_smtp_config"]
