# -*- coding: utf-8 -*-
"""
邮箱服务器配置：根据邮箱后缀自动匹配 IMAP/SMTP 服务器与端口。
支持 QQ、Gmail、Outlook、网易等常见邮箱。
"""

from typing import Optional, Tuple

# 邮箱后缀 -> (imap_server, imap_port, smtp_server, smtp_port, use_ssl)
# 端口 993/465 为 SSL，143/587 为 STARTTLS
EMAIL_SERVERS = {
    # QQ 邮箱
    "qq.com": ("imap.qq.com", 993, "smtp.qq.com", 465, True),
    # Gmail（需应用专用密码或 OAuth，此处为 IMAP/SMTP 地址）
    "gmail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, True),
    "googlemail.com": ("imap.gmail.com", 993, "smtp.gmail.com", 465, True),
    # Outlook / Microsoft
    "outlook.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    "hotmail.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    "live.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    "msn.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    "office365.com": ("outlook.office365.com", 993, "smtp.office365.com", 587, True),
    # 网易
    "163.com": ("imap.163.com", 993, "smtp.163.com", 465, True),
    "126.com": ("imap.126.com", 993, "smtp.126.com", 465, True),
    "yeah.net": ("imap.yeah.net", 993, "smtp.yeah.net", 465, True),
    # 新浪
    "sina.com": ("imap.sina.com", 993, "smtp.sina.com", 465, True),
    "sina.cn": ("imap.sina.cn", 993, "smtp.sina.cn", 465, True),
    # 搜狐
    "sohu.com": ("imap.sohu.com", 993, "smtp.sohu.com", 465, True),
    # 雅虎
    "yahoo.com": ("imap.mail.yahoo.com", 993, "smtp.mail.yahoo.com", 465, True),
    "yahoo.com.cn": ("imap.mail.yahoo.cn", 993, "smtp.mail.yahoo.cn", 465, True),
    # 阿里 / 阿里云邮箱
    "aliyun.com": ("imap.aliyun.com", 993, "smtp.aliyun.com", 465, True),
    "foxmail.com": ("imap.qq.com", 993, "smtp.qq.com", 465, True),
    # 139 邮箱
    "139.com": ("imap.139.com", 993, "smtp.139.com", 465, True),
    # 189 邮箱
    "189.cn": ("imap.189.cn", 993, "smtp.189.cn", 465, True),
}


def _extract_domain(email: str) -> str:
    """从邮箱地址提取域名（小写）。"""
    if "@" in email:
        return email.split("@", 1)[1].strip().lower()
    return ""


def get_imap_smtp_config(email: str) -> Optional[Tuple[str, int, str, int, bool]]:
    """
    根据邮箱地址获取 IMAP/SMTP 配置。
    :param email: 完整邮箱地址
    :return: (imap_host, imap_port, smtp_host, smtp_port, use_ssl) 或 None
    """
    domain = _extract_domain(email)
    return EMAIL_SERVERS.get(domain)
