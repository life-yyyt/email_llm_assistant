# -*- coding: utf-8 -*-
"""添加/编辑邮箱账号对话框：邮箱、授权码、自动解析 IMAP/SMTP。"""

from PyQt5.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QMessageBox,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from config import get_imap_smtp_config


class AddAccountDialog(QDialog):
    """添加邮箱账号：输入邮箱与密码（或授权码），自动匹配服务器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加邮箱账号")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.email_edit = QLineEdit()
        self.email_edit.setPlaceholderText("例如: user@qq.com")
        self.email_edit.textChanged.connect(self._on_email_changed)
        form.addRow("邮箱地址：", self.email_edit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setPlaceholderText("QQ/163 等请使用授权码")
        form.addRow("密码/授权码：", self.password_edit)

        self.server_label = QLabel("（输入邮箱后将自动匹配服务器）")
        self.server_label.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow("", self.server_label)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def _on_email_changed(self):
        email = self.email_edit.text().strip()
        cfg = get_imap_smtp_config(email) if email and "@" in email else None
        if cfg:
            imap_h, imap_p, smtp_h, smtp_p, _ = cfg
            self.server_label.setText(f"IMAP: {imap_h}:{imap_p}  |  SMTP: {smtp_h}:{smtp_p}")
        else:
            self.server_label.setText("（未识别的邮箱域名，请确认或手动配置）")

    def _on_ok(self):
        email = self.email_edit.text().strip()
        password = self.password_edit.text()
        if not email or "@" not in email:
            QMessageBox.warning(self, "提示", "请输入有效的邮箱地址。")
            return
        if not password:
            QMessageBox.warning(self, "提示", "请输入密码或授权码。")
            return
        cfg = get_imap_smtp_config(email)
        if not cfg:
            QMessageBox.warning(
                self,
                "提示",
                "无法识别该邮箱的服务器配置，请使用已支持的邮箱（QQ、163、Gmail、Outlook 等）。",
            )
            return
        self._email = email
        self._password = password
        self._config = cfg
        self.accept()

    def get_account_item(self):
        """在 accept 后调用，返回 (email, password, imap_host, imap_port, smtp_host, smtp_port, use_ssl)。"""
        if not hasattr(self, "_config"):
            return None
        imap_h, imap_p, smtp_h, smtp_p, use_ssl = self._config
        from core.account_store import AccountItem
        return AccountItem(
            email=self._email,
            password=self._password,
            imap_host=imap_h,
            imap_port=imap_p,
            smtp_host=smtp_h,
            smtp_port=smtp_p,
            use_ssl=use_ssl,
        )
