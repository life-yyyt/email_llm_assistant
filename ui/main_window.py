# -*- coding: utf-8 -*-
"""
主窗口：顶部邮箱选择与管理、左侧邮件列表、右侧正文与分类标签、自动回复/润色/发送。
"""

import os
import sys
from typing import Optional, List

from PyQt5.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QComboBox,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QTextEdit,
    QLabel,
    QMessageBox,
    QProgressBar,
    QFrame,
    QScrollArea,
    QDialog,
    QFileDialog,
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QColor, QFont

# 在运行前由 main 将项目根目录加入 path
from core.account_store import AccountStore, AccountItem
from core.email_client import EmailClient
from core.local_llm import LocalLLM
from utils.email_parser import MailItem

from .add_account_dialog import AddAccountDialog


def _extract_reply_to_address(mail: MailItem) -> str:
    """从发件人字符串中提取邮箱地址。"""
    s = mail.sender
    if "<" in s and ">" in s:
        return s.split("<")[1].split(">")[0].strip()
    return s.strip()


class WorkerThread(QThread):
    """后台执行耗时操作，避免卡 UI。"""
    finished_signal = pyqtSignal(object)   # 可选：传递结果
    error_signal = pyqtSignal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self._func = func
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            result = self._func(*self._args, **self._kwargs)
            self.finished_signal.emit(result)
        except Exception as e:
            self.error_signal.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("基于 Llama3.2 1B 的本地智能邮件分类与回复助手")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)

        self._account_store = AccountStore()
        self._account_store.load_from_file()  # 启动时加载已记忆的邮箱账号
        self._email_client: Optional[EmailClient] = None
        self._llm: Optional[LocalLLM] = None
        self._mails: List[MailItem] = []
        self._current_mail: Optional[MailItem] = None
        self._classify_cache = {}  # message_id -> "正常邮件" | "垃圾邮件"
        self._mail_list_filter = "全部"  # "全部" | "正常邮件" | "垃圾邮件"
        self._worker: Optional[WorkerThread] = None
        self._outgoing_attachments: List[str] = []

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        # ---------- 顶部：邮箱选择与管理 + 模型选择 ----------
        top = QHBoxLayout()
        top.addWidget(QLabel("当前邮箱："))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(220)
        self.account_combo.currentIndexChanged.connect(self._on_account_changed)
        top.addWidget(self.account_combo)

        top.addWidget(QLabel("当前模型："))
        self.model_combo = QComboBox()
        self.model_combo.setMinimumWidth(200)
        self.model_combo.currentIndexChanged.connect(self._on_model_changed)
        top.addWidget(self.model_combo)

        self.btn_refresh = QPushButton("刷新邮件")
        self.btn_refresh.clicked.connect(self._fetch_mails)
        top.addWidget(self.btn_refresh)

        self.btn_add_account = QPushButton("添加账号")
        self.btn_add_account.clicked.connect(self._add_account)
        top.addWidget(self.btn_add_account)

        self.btn_remove_account = QPushButton("删除当前账号")
        self.btn_remove_account.clicked.connect(self._remove_current_account)
        top.addWidget(self.btn_remove_account)

        top.addStretch()
        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: gray;")
        top.addWidget(self.status_label)
        layout.addLayout(top)

        # ---------- 中部：左右分栏 ----------
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：邮件列表（支持按分类筛选：全部 / 正常邮件 / 垃圾邮件）
        left_w = QFrame()
        left_w.setFrameStyle(QFrame.StyledPanel)
        left_layout = QVBoxLayout(left_w)
        left_layout.addWidget(QLabel("邮件列表"))
        self.mail_list_filter = QComboBox()
        self.mail_list_filter.addItems(["全部", "正常邮件", "垃圾邮件"])
        self.mail_list_filter.currentTextChanged.connect(self._on_mail_list_filter_changed)
        left_layout.addWidget(self.mail_list_filter)
        self.mail_list = QListWidget()
        self.mail_list.setMinimumWidth(320)
        self.mail_list.itemClicked.connect(self._on_mail_clicked)
        left_layout.addWidget(self.mail_list)
        splitter.addWidget(left_w)

        # 右侧：正文 + 分类 + 操作
        right_w = QWidget()
        right_layout = QVBoxLayout(right_w)

        # 分类结果 + 纠正按钮 + 发送时间
        classify_row = QHBoxLayout()
        self.classify_label = QLabel("分类：未分类")
        self.classify_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        classify_row.addWidget(self.classify_label)
        classify_row.addStretch()
        self.btn_mark_normal = QPushButton("标为正常邮件")
        self.btn_mark_normal.setStyleSheet("font-size: 11px;")
        self.btn_mark_normal.clicked.connect(self._mark_current_as_normal)
        self.btn_mark_spam = QPushButton("标为垃圾邮件")
        self.btn_mark_spam.setStyleSheet("font-size: 11px;")
        self.btn_mark_spam.clicked.connect(self._mark_current_as_spam)
        classify_row.addWidget(self.btn_mark_normal)
        classify_row.addWidget(self.btn_mark_spam)
        right_layout.addLayout(classify_row)
        self.send_time_label = QLabel("发送时间：—")
        self.send_time_label.setStyleSheet("color: #555; font-size: 11px;")
        right_layout.addWidget(self.send_time_label)

        # 附件与链接
        self.attachments_label = QLabel("附件：无")
        self.attachments_label.setStyleSheet("color: #555; font-size: 11px;")
        right_layout.addWidget(self.attachments_label)

        self.links_label = QLabel("链接：无")
        self.links_label.setOpenExternalLinks(True)
        self.links_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.links_label.setStyleSheet("color: #0066cc; font-size: 11px;")
        right_layout.addWidget(self.links_label)

        # 正文展示
        self.body_edit = QTextEdit()
        self.body_edit.setPlaceholderText("点击左侧邮件查看正文…")
        self.body_edit.setReadOnly(True)
        right_layout.addWidget(self.body_edit)

        # 回复编辑区（可写）
        right_layout.addWidget(QLabel("回复内容："))
        self.reply_edit = QTextEdit()
        self.reply_edit.setPlaceholderText("在此编辑回复，或使用「生成回复」/「润色」")
        self.reply_edit.textChanged.connect(self._update_buttons_state)
        right_layout.addWidget(self.reply_edit)

        self.outgoing_attachments_label = QLabel("待发送附件：无")
        self.outgoing_attachments_label.setStyleSheet("color: #555; font-size: 11px;")
        right_layout.addWidget(self.outgoing_attachments_label)

        # 操作按钮
        btn_row = QHBoxLayout()
        self.btn_classify = QPushButton("智能分类")
        self.btn_classify.clicked.connect(self._do_classify)
        btn_row.addWidget(self.btn_classify)

        self.btn_gen_reply = QPushButton("生成回复")
        self.btn_gen_reply.clicked.connect(self._do_generate_reply)
        btn_row.addWidget(self.btn_gen_reply)

        self.polish_style_combo = QComboBox()
        self.polish_style_combo.addItems(["自然", "正式", "商务"])
        self.polish_style_combo.setToolTip("润色场合：自然 / 正式 / 商务")
        btn_row.addWidget(self.polish_style_combo)
        self.btn_polish = QPushButton("润色")
        self.btn_polish.clicked.connect(self._do_polish)
        btn_row.addWidget(self.btn_polish)

        self.btn_save_attachments = QPushButton("保存附件…")
        self.btn_save_attachments.clicked.connect(self._save_attachments)
        btn_row.addWidget(self.btn_save_attachments)

        self.btn_add_outgoing_attachment = QPushButton("添加发送附件…")
        self.btn_add_outgoing_attachment.clicked.connect(self._add_outgoing_attachments)
        btn_row.addWidget(self.btn_add_outgoing_attachment)

        self.btn_send = QPushButton("发送")
        self.btn_send.clicked.connect(self._do_send)
        btn_row.addWidget(self.btn_send)

        btn_row.addStretch()
        right_layout.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximum(0)  # 无限进度
        self.progress_bar.setVisible(False)
        right_layout.addWidget(self.progress_bar)

        splitter.addWidget(right_w)
        splitter.setSizes([350, 650])
        layout.addWidget(splitter)

        self._refresh_account_combo()
        self._init_model_combo()
        self._update_buttons_state()

    def _models_root_dir(self) -> str:
        """返回项目内 models 目录路径。"""
        # ui/ 在项目根目录下，所以向上一层
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(root, "models")

    def _init_model_combo(self):
        """初始化模型下拉框：扫描 models 子目录，以及当前环境变量指定的模型。"""
        self.model_combo.blockSignals(True)
        self.model_combo.clear()

        # 默认项：自动（环境变量 / Ollama）
        self.model_combo.addItem("自动（环境变量 / Ollama）", None)

        # 如果环境变量中已有 LLAMA_MODEL_PATH，但不在 models 目录中，也显示一项方便识别
        env_path = (os.environ.get("LLAMA_MODEL_PATH") or "").strip()
        added_env = False

        models_dir = self._models_root_dir()
        if os.path.isdir(models_dir):
            try:
                for name in sorted(os.listdir(models_dir)):
                    path = os.path.join(models_dir, name)
                    if os.path.isdir(path):
                        self.model_combo.addItem(f"{name}", path)
                        if env_path and os.path.normpath(env_path) == os.path.normpath(path):
                            # 若环境变量刚好指向此目录，后面直接选中
                            added_env = True
            except Exception:
                pass

        if env_path and not added_env:
            # 单独给环境变量路径增加一项
            display = os.path.basename(env_path.rstrip("\\/")) or env_path
            self.model_combo.addItem(f"环境变量：{display}", env_path)

        # 根据当前环境变量预选
        current_index = 0
        if env_path:
            for i in range(self.model_combo.count()):
                if os.path.normpath(self.model_combo.itemData(i) or "") == os.path.normpath(env_path):
                    current_index = i
                    break
        self.model_combo.setCurrentIndex(current_index)
        self.model_combo.blockSignals(False)

    def _refresh_account_combo(self):
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        for a in self._account_store.get_all():
            self.account_combo.addItem(a.email, a)
        idx = 0
        cur = self._account_store.get_current()
        if cur:
            for i in range(self.account_combo.count()):
                if self.account_combo.itemData(i) == cur:
                    idx = i
                    break
        self.account_combo.setCurrentIndex(idx)
        self.account_combo.blockSignals(False)

    def _update_buttons_state(self):
        has_account = self._account_store.count() > 0
        has_mail = self._current_mail is not None
        self.btn_refresh.setEnabled(has_account)
        self.btn_remove_account.setEnabled(has_account)
        self.btn_classify.setEnabled(has_mail)
        self.btn_gen_reply.setEnabled(has_mail)
        self.btn_polish.setEnabled(has_mail)
        self.btn_send.setEnabled(has_mail and bool(self.reply_edit.toPlainText().strip()))
        self.btn_mark_normal.setEnabled(has_mail)
        self.btn_mark_spam.setEnabled(has_mail)
        has_attachments = bool(self._current_mail and getattr(self._current_mail, "attachments", None))
        self.btn_save_attachments.setEnabled(has_mail and has_attachments)
        self.btn_add_outgoing_attachment.setEnabled(has_mail)

    def _on_model_changed(self, index: int):
        """切换当前使用的本地模型目录。"""
        if index < 0:
            return
        path = self.model_combo.itemData(index)
        # None 表示自动（环境变量 / Ollama）——不强制覆盖 LLAMA_MODEL_PATH，仅重置实例
        if path:
            os.environ["LLAMA_MODEL_PATH"] = path
            self.status_label.setText(f"已切换模型：{os.path.basename(path.rstrip(os.sep))}")
        else:
            # 清空环境变量，回到自动模式
            if "LLAMA_MODEL_PATH" in os.environ:
                del os.environ["LLAMA_MODEL_PATH"]
            self.status_label.setText("已切换模型：自动（环境变量 / Ollama）")

        # 切换模型后重置已加载的 LLM，下一次调用时会按新路径/策略重新加载
        try:
            LocalLLM.reset_instance()
        except Exception:
            pass
        self._llm = None

    def _on_account_changed(self, index: int):
        if index < 0:
            return
        self._account_store.set_current_index(index)
        self._email_client = None
        self._fetch_mails()

    def _add_account(self):
        dlg = AddAccountDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        item = dlg.get_account_item()
        if item:
            self._account_store.add(item)
            self._account_store.save_to_file()  # 记忆账号到本地
            self._refresh_account_combo()
            self._account_store.set_current_by_email(item.email)
            self._refresh_account_combo()
            self._fetch_mails()
            self.status_label.setText(f"已添加账号: {item.email}")

    def _remove_current_account(self):
        cur = self._account_store.get_current()
        if not cur:
            return
        if QMessageBox.question(
            self,
            "确认",
            f"确定要删除账号 {cur.email} 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) != QMessageBox.Yes:
            return
        self._account_store.remove_by_email(cur.email)
        self._account_store.save_to_file()  # 从记忆中移除该账号
        self._email_client = None
        self._current_mail = None
        self._mails = []
        self._refresh_account_combo()
        self._repaint_mail_list()
        self.body_edit.clear()
        self.reply_edit.clear()
        self.classify_label.setText("分类：未分类")
        self.send_time_label.setText("发送时间：—")
        self._update_buttons_state()
        self.status_label.setText("已删除账号")

    def _get_client(self) -> Optional[EmailClient]:
        cur = self._account_store.get_current()
        if not cur:
            return None
        if self._email_client is None or self._email_client._account != cur:
            self._email_client = EmailClient(cur)
        return self._email_client

    def _fetch_mails(self):
        client = self._get_client()
        if not client:
            self._mails = []
            self._repaint_mail_list()
            return
        self.status_label.setText("正在拉取邮件…")
        self.progress_bar.setVisible(True)

        def do_fetch():
            return client.fetch_recent(50)

        self._worker = WorkerThread(do_fetch)
        self._worker.finished_signal.connect(self._on_fetch_finished)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_fetch_finished(self, result):
        self.progress_bar.setVisible(False)
        self._mails = result if isinstance(result, list) else []
        self._repaint_mail_list()
        self.status_label.setText(f"已加载 {len(self._mails)} 封邮件")
        self._start_auto_classify()

    def _start_auto_classify(self):
        """拉取邮件后，在后台对未分类的邮件逐封做智能分类，结果写入缓存并刷新列表。"""
        if not self._mails:
            return

        def run():
            self._ensure_llm()
            done = set(self._classify_cache.keys())
            out = []
            for m in self._mails:
                if m.message_id in done:
                    continue
                try:
                    label = self._llm.classify_spam(m.subject, m.get_display_body(), use_cache=True)
                    out.append((m.message_id, label))
                except Exception:
                    pass
            return out

        self.progress_bar.setVisible(True)
        self.status_label.setText("正在自动分类邮件…")
        self._worker = WorkerThread(run)
        self._worker.finished_signal.connect(self._on_auto_classify_finished)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_auto_classify_finished(self, result):
        self.progress_bar.setVisible(False)
        for mid, label in result or []:
            self._classify_cache[mid] = label
        self._repaint_mail_list()
        n_total, n_done = len(self._mails), len(result) if result else 0
        self.status_label.setText(f"已加载 {n_total} 封，已自动分类 {n_done} 封")

    def _on_worker_error(self, err: str):
        self.progress_bar.setVisible(False)
        self.status_label.setText("错误")
        if err and ("connection" in err.lower() or "refused" in err.lower() or "11434" in err or "连接" in err):
            err = (
                "无法连接 Ollama 服务（可能未启动或未安装模型）。\n\n"
                "请先启动 Ollama，并在终端执行：\n  ollama run llama3.2:1b\n"
                "再重试「智能分类」或「生成回复」。"
            )
        elif err and "illegal in state auth" in err.lower():
            err = (
                "IMAP 服务器拒绝执行操作：当前会话处于 AUTH 状态，但未成功选择邮箱文件夹。\n\n"
                "可能原因：\n"
                "1. 邮箱尚未在网页版设置中开启 IMAP/POP3 服务；\n"
                "2. 账号或授权码配置有误，虽然登录通过但无法选择收件箱；\n"
                "3. 邮箱服务器暂时异常。\n\n"
                "请在邮箱安全设置中确认已开启 IMAP，并使用正确的授权码重新添加账号后再试。"
            )
        else:
            err = f"操作失败：{err}"
        QMessageBox.critical(self, "错误", err)

    def _on_mail_list_filter_changed(self, text: str):
        self._mail_list_filter = text or "全部"
        self._repaint_mail_list()

    def _repaint_mail_list(self):
        self.mail_list.clear()
        for m in self._mails:
            label = self._classify_cache.get(m.message_id)
            if self._mail_list_filter == "正常邮件" and label != "正常邮件":
                continue
            if self._mail_list_filter == "垃圾邮件" and label != "垃圾邮件":
                continue
            item = QListWidgetItem(f"{m.subject or '(无主题)'} — {m.sender}")
            item.setData(Qt.UserRole, m)
            if label == "垃圾邮件":
                item.setForeground(QColor("red"))
            self.mail_list.addItem(item)

    def _on_mail_clicked(self, list_item: QListWidgetItem):
        mail = list_item.data(Qt.UserRole)
        if not mail:
            return
        self._current_mail = mail
        self.body_edit.setPlainText(mail.get_display_body())
        self.reply_edit.clear()
        # 显示发送时间
        self.send_time_label.setText(f"发送时间：{mail.date_str or '—'}")
        # 显示附件信息
        atts = getattr(mail, "attachments", None) or []
        if atts:
            parts = []
            for a in atts:
                size_kb = (a.size or 0) / 1024.0
                parts.append(f"{a.filename} ({size_kb:.1f} KB)")
            self.attachments_label.setText("附件：" + "； ".join(parts))
        else:
            self.attachments_label.setText("附件：无")
        # 显示正文中的链接
        links = getattr(mail, "links", None) or []
        if links:
            # 只展示前若干个，防止太长
            max_show = 5
            items = [f'<a href="{u}">{u}</a>' for u in links[:max_show]]
            if len(links) > max_show:
                items.append(f"等 {len(links)} 个链接…")
            self.links_label.setText("链接：" + "； ".join(items))
        else:
            self.links_label.setText("链接：无")
        # 显示已缓存分类
        label = self._classify_cache.get(mail.message_id)
        if label:
            self._set_classify_ui(label)
        else:
            self.classify_label.setText("分类：未分类")
            self.classify_label.setStyleSheet("font-weight: bold; font-size: 12px;")
        self._update_buttons_state()

    def _save_attachments(self):
        """将当前邮件的所有附件保存到用户选择的目录。"""
        if not self._current_mail or not getattr(self._current_mail, "attachments", None):
            QMessageBox.information(self, "提示", "当前邮件没有附件。")
            return
        dir_path = QFileDialog.getExistingDirectory(self, "选择保存附件的文件夹")
        if not dir_path:
            return
        errors = []
        for att in self._current_mail.attachments:
            filename = att.filename or "附件"
            safe_name = filename.replace("/", "_").replace("\\", "_")
            save_path = os.path.join(dir_path, safe_name)
            try:
                with open(save_path, "wb") as f:
                    f.write(att.payload or b"")
            except Exception as e:
                errors.append(f"{safe_name}: {e}")
        if errors:
            QMessageBox.warning(self, "提示", "部分附件保存失败：\n" + "\n".join(errors))
        else:
            QMessageBox.information(self, "提示", "附件已保存。")

    def _refresh_outgoing_attachments_label(self):
        if not self._outgoing_attachments:
            self.outgoing_attachments_label.setText("待发送附件：无")
            return
        names = [os.path.basename(p) for p in self._outgoing_attachments if p]
        if not names:
            self.outgoing_attachments_label.setText("待发送附件：无")
            return
        # 若过多则截断显示
        max_show = 3
        shown = names[:max_show]
        if len(names) > max_show:
            shown.append(f"等 {len(names)} 个文件…")
        self.outgoing_attachments_label.setText("待发送附件：" + "，".join(shown))

    def _add_outgoing_attachments(self):
        """选择要随回复发送的本地附件。"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择要发送的附件")
        if not files:
            return
        # 去重合并
        existing = set(self._outgoing_attachments)
        for p in files:
            if p and p not in existing:
                self._outgoing_attachments.append(p)
                existing.add(p)
        self._refresh_outgoing_attachments_label()

    def _set_classify_ui(self, label: str):
        self.classify_label.setText(f"分类：{label}")
        if label == "垃圾邮件":
            self.classify_label.setStyleSheet("font-weight: bold; font-size: 12px; color: red;")
        else:
            self.classify_label.setStyleSheet("font-weight: bold; font-size: 12px; color: green;")

    def _mark_current_as_normal(self):
        if not self._current_mail:
            return
        self._classify_cache[self._current_mail.message_id] = "正常邮件"
        self._set_classify_ui("正常邮件")
        self._repaint_mail_list()
        self.status_label.setText("已标为正常邮件")

    def _mark_current_as_spam(self):
        if not self._current_mail:
            return
        self._classify_cache[self._current_mail.message_id] = "垃圾邮件"
        self._set_classify_ui("垃圾邮件")
        self._repaint_mail_list()
        self.status_label.setText("已标为垃圾邮件")

    def _do_classify(self):
        if not self._current_mail:
            return
        mail = self._current_mail
        if self._classify_cache.get(mail.message_id):
            self._set_classify_ui(self._classify_cache[mail.message_id])
            return
        self.progress_bar.setVisible(True)
        self.status_label.setText("正在分类…")

        def run():
            self._ensure_llm()
            return self._llm.classify_spam(mail.subject, mail.get_display_body(), use_cache=True)

        self._worker = WorkerThread(run)
        self._worker.finished_signal.connect(self._on_classify_finished)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_classify_finished(self, result):
        self.progress_bar.setVisible(False)
        self.status_label.setText("就绪")
        if self._current_mail and result:
            self._classify_cache[self._current_mail.message_id] = result
            self._set_classify_ui(result)
            self._repaint_mail_list()

    def _ensure_llm(self):
        import os
        if self._llm is None:
            has_local_path = bool((os.environ.get("LLAMA_MODEL_PATH") or "").strip())
            err_transformers = None
            # 未设置 LLAMA_MODEL_PATH 时优先尝试 Ollama，避免先报 Transformers 错误
            if not has_local_path:
                try:
                    self._llm = LocalLLM(backend="ollama")
                    return
                except Exception:
                    LocalLLM.reset_instance()
            try:
                self._llm = LocalLLM(backend="transformers")
            except Exception as e:
                err_transformers = e
                LocalLLM.reset_instance()
                if not has_local_path:
                    try:
                        self._llm = LocalLLM(backend="ollama")
                        return
                    except Exception:
                        LocalLLM.reset_instance()
                raise RuntimeError(
                    "本地模型未就绪，请任选一种方式：\n\n"
                    "【方式一】使用 Ollama（推荐）\n"
                    "  1. 确保 Ollama 已启动（任务栏或服务中有 Ollama）\n"
                    "  2. 在终端执行：ollama run llama3.2:1b\n"
                    "  3. 再点击「智能分类」或「生成回复」\n\n"
                    "【方式二】使用本地 Transformers 模型\n"
                    "  设置环境变量：set LLAMA_MODEL_PATH=D:\\你的路径\\Llama-3.2-1B\n"
                    "（路径需为包含 config.json 的模型目录）"
                )

    def _do_generate_reply(self):
        if not self._current_mail:
            return
        self.progress_bar.setVisible(True)
        self.status_label.setText("正在生成回复…")
        mail = self._current_mail

        def run():
            self._ensure_llm()
            return self._llm.generate_reply(mail.subject, mail.get_display_body(), use_cache=False)

        self._worker = WorkerThread(run)
        self._worker.finished_signal.connect(lambda r: self._on_text_gen_finished(r, self.reply_edit))
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _do_polish(self):
        text = self.reply_edit.toPlainText().strip()
        if not text:
            QMessageBox.information(self, "提示", "请先在回复框中输入内容再润色。")
            return
        style = self.polish_style_combo.currentText().strip() or "自然"
        self.progress_bar.setVisible(True)
        self.status_label.setText("正在润色…")

        def run():
            self._ensure_llm()
            return self._llm.polish_email(text, style=style, use_cache=False)

        self._worker = WorkerThread(run)
        self._worker.finished_signal.connect(lambda r: self._on_text_gen_finished(r, self.reply_edit))
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_text_gen_finished(self, result, target_edit: QTextEdit):
        self.progress_bar.setVisible(False)
        self.status_label.setText("就绪")
        if result and target_edit:
            target_edit.setPlainText(result)
        self._update_buttons_state()

    def _do_send(self):
        if not self._current_mail:
            return
        to_addr = _extract_reply_to_address(self._current_mail)
        if not to_addr:
            QMessageBox.warning(self, "提示", "无法解析收件人地址。")
            return
        subject = self._current_mail.subject or ""
        if subject and not subject.lower().startswith("re:"):
            subject = "Re: " + subject
        body = self.reply_edit.toPlainText().strip()
        if not body:
            QMessageBox.warning(self, "提示", "回复内容为空。")
            return
        client = self._get_client()
        if not client:
            QMessageBox.warning(self, "提示", "当前无可用邮箱账号。")
            return
        self.progress_bar.setVisible(True)
        self.status_label.setText("正在发送…")

        def run():
            client.send_mail(
                to_addr,
                subject,
                body,
                reply_to_message_id=self._current_mail.message_id or None,
                attachments=self._outgoing_attachments or None,
            )

        self._worker = WorkerThread(run)
        self._worker.finished_signal.connect(self._on_send_finished)
        self._worker.error_signal.connect(self._on_worker_error)
        self._worker.start()

    def _on_send_finished(self, _):
        self.progress_bar.setVisible(False)
        self.status_label.setText("发送成功")
        self.reply_edit.clear()
        self._outgoing_attachments = []
        self._refresh_outgoing_attachments_label()
        self._update_buttons_state()
        QMessageBox.information(self, "提示", "邮件已发送。")

    def closeEvent(self, event):
        if self._email_client:
            self._email_client.disconnect()
        event.accept()
