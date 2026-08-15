from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.backup import BackupJob, BackupStats
from app.catalog import Catalog
from app.enrich import enrich_library
from app.gallery import ensure_thumb, files_for_month
from app.paths import (
    LOW_SPACE_WARN_BYTES,
    assess_library_space,
    format_bytes,
    is_removable_drive,
    library_root,
)
from app.people import face_engine_available
from app.settings import AppSettings
from app.suggestions import (
    Suggestion,
    apply_suggestion,
    month_suggestions,
    people_suggestions,
    place_suggestions,
    screenshot_suggestions,
)

PAGE_HOME = 0
PAGE_PROGRESS = 1
PAGE_SUMMARY = 2
PAGE_GALLERY = 3
PAGE_ORGANIZE = 4
PAGE_SETTINGS = 5
PAGE_REVIEW = 6

_PAGE_NAMES = {
    PAGE_HOME: "home",
    PAGE_GALLERY: "gallery",
    PAGE_ORGANIZE: "organize",
    PAGE_SETTINGS: "settings",
    PAGE_REVIEW: "review",
}
_NAME_PAGES = {v: k for k, v in _PAGE_NAMES.items()}


class BackupWorker(QObject):
    progress = Signal(object)
    finished = Signal(object)

    def __init__(self, job: BackupJob) -> None:
        super().__init__()
        self.job = job

    def run(self) -> None:
        stats = self.job.run(on_progress=self.progress.emit)
        self.finished.emit(stats)


class EnrichWorker(QObject):
    finished = Signal(object)

    def __init__(self, catalog: Catalog) -> None:
        super().__init__()
        self.catalog = catalog

    def run(self) -> None:
        self.finished.emit(enrich_library(self.catalog))


class MainWindow(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Piczop")
        self.resize(1180, 780)
        self.settings = AppSettings.load()
        self.catalog = Catalog()
        self.job: BackupJob | None = None
        self.thread: QThread | None = None
        self.last_stats: BackupStats | None = None
        self.gallery_mode = self.catalog.get_ui("gallery_filter", "timeline") or "timeline"
        self.gallery_person = self.catalog.get_ui("gallery_person")
        self.gallery_place = self.catalog.get_ui("gallery_place")
        self.review_choice: dict[int, str] = {}
        self._review_index = 0
        saved_primary = self.catalog.get_ui("review_primary_sha")
        saved_gid = self.catalog.get_ui("review_group_id")
        if saved_gid and saved_primary:
            try:
                self.review_choice[int(saved_gid)] = saved_primary
            except ValueError:
                pass

        self.setStyleSheet(
            """
            QWidget { background: #0e1014; color: #e8eaed; font-size: 14px; }
            QPushButton {
                background: #1a73e8; color: white; border: none;
                padding: 10px 16px; border-radius: 20px;
            }
            QPushButton:hover { background: #4285f4; }
            QPushButton#go {
                background: #1e8e3e; font-size: 20px; padding: 16px 40px;
                font-weight: 700; border-radius: 28px;
            }
            QPushButton#go:hover { background: #34a853; }
            QPushButton#ghost, QPushButton#nav {
                background: transparent; color: #c4c7cc; border-radius: 12px;
                padding: 10px 14px; text-align: left;
            }
            QPushButton#nav:checked, QPushButton#nav:hover {
                background: #1f2128; color: #fff;
            }
            QPushButton#filter {
                background: #1f2128; color: #c4c7cc; padding: 8px 16px;
                border-radius: 18px;
            }
            QPushButton#filter:checked { background: #1a73e8; color: white; }
            QPushButton#pick {
                background: #1a1d24; color: #e8eaed;
                border: 3px solid transparent; border-radius: 16px;
            }
            QPushButton#pick:checked {
                border: 3px solid #81c995;
                background: #16351f;
            }
            QPushButton#danger { background: #c5221f; border-radius: 20px; }
            QPushButton#danger:hover { background: #e94235; }
            QPushButton:disabled { background: #2a2d35; color: #80868b; }
            QFrame#card {
                background: #171a21; border-radius: 16px;
            }
            QFrame#sidebar {
                background: #12141a; border-radius: 0px;
            }
            QLineEdit, QListWidget {
                background: #171a21; border: 1px solid #2d323c; border-radius: 10px;
                padding: 8px;
            }
            QProgressBar {
                border: none; background: #2d323c; height: 12px; border-radius: 6px;
                text-align: center;
            }
            QProgressBar::chunk { background: #34a853; border-radius: 6px; }
            QScrollArea { border: none; background: transparent; }
            QLabel#muted { color: #9aa0a6; }
            QLabel#chip {
                background: #1f2128; color: #e8eaed; padding: 4px 10px;
                border-radius: 12px;
            }
            """
        )

        self.stack = QStackedWidget()
        self.page_home = QWidget()
        self.page_progress = QWidget()
        self.page_summary = QWidget()
        self.page_gallery = QWidget()
        self.page_organize = QWidget()
        self.page_settings = QWidget()
        self.page_review = QWidget()
        self._build_home()
        self._build_progress()
        self._build_summary()
        self._build_gallery()
        self._build_organize()
        self._build_settings()
        self._build_review()
        for page in (
            self.page_home,
            self.page_progress,
            self.page_summary,
            self.page_gallery,
            self.page_organize,
            self.page_settings,
            self.page_review,
        ):
            self.stack.addWidget(page)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(168)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(12, 20, 12, 20)
        brand = QLabel("Piczop")
        brand.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        nav.addWidget(brand)
        nav.addSpacing(12)
        self.nav_buttons: dict[int, QPushButton] = {}
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for idx, label in [
            (PAGE_HOME, "Home"),
            (PAGE_GALLERY, "Gallery"),
            (PAGE_REVIEW, "Review"),
            (PAGE_ORGANIZE, "Organize"),
            (PAGE_SETTINGS, "Settings"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, i=idx: self._open_page(i))
            self.nav_group.addButton(btn)
            self.nav_buttons[idx] = btn
            nav.addWidget(btn)
        nav.addStretch()
        root.addWidget(sidebar)
        content = QVBoxLayout()
        content.setContentsMargins(28, 20, 28, 20)
        content.addWidget(self.stack)
        wrap = QWidget()
        wrap.setLayout(content)
        root.addWidget(wrap, 1)

        start = _NAME_PAGES.get(self.catalog.get_ui("page", "home") or "home", PAGE_HOME)
        self._open_page(start)

    def _open_page(self, index: int) -> None:
        if index == PAGE_GALLERY:
            self._open_gallery()
            return
        if index == PAGE_REVIEW:
            self._open_review()
            return
        if index == PAGE_ORGANIZE:
            self._reload_organize()
            self._show(PAGE_ORGANIZE)
            return
        self._show(index)

    def _show(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        name = _PAGE_NAMES.get(index)
        if name:
            self.catalog.set_ui("page", name)
        btn = self.nav_buttons.get(index)
        if btn:
            btn.setChecked(True)
        if index == PAGE_HOME:
            self.refresh_home()

    def _build_home(self) -> None:
        layout = QVBoxLayout(self.page_home)
        layout.setSpacing(18)
        title = QLabel("Your photos, on this stick")
        title.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        subtitle = QLabel(
            "Back up locally. Similar copies wait for review. Screenshots stay out of People. No cloud."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        self.lbl_location = QLabel()
        self.lbl_space = QLabel()
        self.lbl_last = QLabel()
        self.lbl_count = QLabel()
        self.lbl_review = QLabel()
        self.btn_home_review = QPushButton("Continue review")
        self.btn_home_review.setObjectName("ghost")
        self.btn_home_review.clicked.connect(self._open_review)
        card = QFrame()
        card.setObjectName("card")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(20, 20, 20, 20)
        card_l.setSpacing(8)
        card_l.addWidget(self.lbl_location)
        card_l.addWidget(self.lbl_space)
        card_l.addWidget(self.lbl_last)
        card_l.addWidget(self.lbl_count)
        card_l.addWidget(self.lbl_review)
        card_l.addWidget(self.btn_home_review)
        go = QPushButton("Back up now")
        go.setObjectName("go")
        go.clicked.connect(self.start_backup)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(card)
        layout.addStretch()
        layout.addWidget(go, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    def refresh_home(self) -> None:
        lib = library_root()
        removable = is_removable_drive()
        where = "USB stick" if removable else "this folder (copy Piczop onto a USB for portable use)"
        self.lbl_location.setText(f"Library: {lib}\nRunning from {where}")
        try:
            level, free, total, message = assess_library_space()
            space_text = f"Drive space: {format_bytes(free)} free of {format_bytes(total)}"
            if level == "block":
                space_text += f"\nNot enough free space — free up room before backing up."
            elif level == "warn":
                space_text += (
                    f"\nLow space (under {format_bytes(LOW_SPACE_WARN_BYTES)}) — "
                    "backup may fail if the drive fills up."
                )
            self.lbl_space.setText(space_text)
            if level in ("warn", "block"):
                self.lbl_space.setToolTip(message)
                self.lbl_space.setStyleSheet("color: #b45309;")
            else:
                self.lbl_space.setToolTip("")
                self.lbl_space.setStyleSheet("")
        except OSError as exc:
            self.lbl_space.setText(
                "Drive space: unavailable — is the library drive connected?"
            )
            self.lbl_space.setToolTip(str(exc))
            self.lbl_space.setStyleSheet("color: #b45309;")
        last = self.catalog.last_backup()
        if last:
            self.lbl_last.setText(
                f"Last backup: {last['finished_at']}  "
                f"({last['copied']} copied, {last['skipped']} skipped)"
            )
        else:
            self.lbl_last.setText("Last backup: never")
        self.lbl_count.setText(f"Items in library: {self.catalog.file_count()}")
        pending = self.catalog.pending_review_count()
        if pending:
            self.lbl_review.setText(
                f"{pending} duplicate group{'s' if pending != 1 else ''} need your review"
            )
        else:
            self.lbl_review.setText("No duplicate groups waiting for review")
        self.nav_buttons[PAGE_REVIEW].setText(f"Review ({pending})" if pending else "Review")

    def _build_progress(self) -> None:
        layout = QVBoxLayout(self.page_progress)
        self.lbl_phase = QLabel("Starting…")
        self.lbl_phase.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        self.lbl_current = QLabel("")
        self.lbl_current.setWordWrap(True)
        self.lbl_current.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_counts = QLabel("")
        self.lbl_counts.setWordWrap(True)
        self.lbl_eta = QLabel("")
        self.lbl_eta.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)
        row = QHBoxLayout()
        self.btn_pause = QPushButton("Pause")
        self.btn_pause.setObjectName("ghost")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("ghost")
        self.btn_pause.clicked.connect(self._toggle_pause)
        self.btn_cancel.clicked.connect(self._cancel_backup)
        row.addWidget(self.btn_pause)
        row.addWidget(self.btn_cancel)
        row.addStretch()
        layout.addWidget(self.lbl_phase)
        layout.addWidget(self.bar)
        layout.addWidget(self.lbl_counts)
        layout.addWidget(self.lbl_eta)
        layout.addWidget(self.lbl_current)
        layout.addStretch()
        layout.addLayout(row)

    def _build_summary(self) -> None:
        layout = QVBoxLayout(self.page_summary)
        self.lbl_summary = QLabel()
        self.lbl_summary.setWordWrap(True)
        self.lbl_summary.setFont(QFont("Segoe UI", 16))
        again = QPushButton("Back to home")
        again.clicked.connect(lambda: self._show(PAGE_HOME))
        self.btn_summary_review = QPushButton("Review duplicates")
        self.btn_summary_review.clicked.connect(self._open_review)
        layout.addWidget(self.lbl_summary)
        layout.addStretch()
        layout.addWidget(self.btn_summary_review)
        layout.addWidget(again)

    def _build_gallery(self) -> None:
        layout = QVBoxLayout(self.page_gallery)
        layout.setSpacing(12)
        heading = QLabel("Library")
        heading.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        layout.addWidget(heading)
        filters = QHBoxLayout()
        self.filter_buttons: dict[str, QPushButton] = {}
        for key, label in [
            ("timeline", "Date"),
            ("people", "People"),
            ("places", "Places"),
            ("screenshots", "Screenshots"),
            ("pending", "Review pending"),
            ("videos", "Videos"),
        ]:
            btn = QPushButton(label)
            btn.setObjectName("filter")
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, k=key: self._set_gallery_mode(k))
            self.filter_buttons[key] = btn
            filters.addWidget(btn)
        filters.addStretch()
        layout.addLayout(filters)
        self.gallery_hint = QLabel()
        self.gallery_hint.setObjectName("muted")
        self.gallery_hint.setWordWrap(True)
        layout.addWidget(self.gallery_hint)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.side_list = QListWidget()
        self.side_list.currentTextChanged.connect(self._reload_thumbs)
        self.side_label = QLabel("Months")
        left.addWidget(self.side_label)
        left.addWidget(self.side_list)
        self.side_panel = QWidget()
        self.side_panel.setLayout(left)
        self.side_panel.setFixedWidth(220)
        self.gallery_scroll = QScrollArea()
        self.gallery_scroll.setWidgetResizable(True)
        self.gallery_host = QWidget()
        self.gallery_grid = QGridLayout(self.gallery_host)
        self.gallery_grid.setSpacing(14)
        self.gallery_scroll.setWidget(self.gallery_host)
        body.addWidget(self.side_panel)
        body.addWidget(self.gallery_scroll, 1)
        layout.addLayout(body)

    def _set_gallery_mode(self, mode: str) -> None:
        self.gallery_mode = mode
        self.catalog.set_ui("gallery_filter", mode)
        for key, btn in self.filter_buttons.items():
            btn.setChecked(key == mode)
        self._fill_side_list()
        self._reload_thumbs()

    def _fill_side_list(self) -> None:
        self.side_list.blockSignals(True)
        self.side_list.clear()
        mode = self.gallery_mode
        show = mode in {"timeline", "people", "places"}
        self.side_panel.setVisible(show)
        if mode == "timeline":
            self.side_label.setText("Timeline")
            self.side_list.addItem("All dates")
            for ym, n in self.catalog.months():
                self.side_list.addItem(QListWidgetItem(f"{ym}  ·  {n}"))
        elif mode == "people":
            self.side_label.setText("People (not screenshots)")
            self.side_list.addItem("All people")
            for pid, label, n in self.catalog.person_groups():
                item = QListWidgetItem(f"{label}  ·  {n}")
                item.setData(Qt.ItemDataRole.UserRole, pid)
                self.side_list.addItem(item)
        elif mode == "places":
            self.side_label.setText("Places (GPS clusters)")
            self.side_list.addItem("Has location")
            self.side_list.addItem("No location")
            for key, n in self.catalog.location_groups():
                if key == "none":
                    continue
                item = QListWidgetItem(f"{key}  ·  {n}")
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.side_list.addItem(item)
        self.side_list.setCurrentRow(0)
        self.side_list.blockSignals(False)

    def _build_organize(self) -> None:
        layout = QVBoxLayout(self.page_organize)
        title = QLabel("Organize")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        hint = QLabel(
            "Suggestions only. Applying moves files on this stick into folders. "
            "PC originals are never deleted. Screenshots are a separate album from People."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        row = QHBoxLayout()
        scan = QPushButton("Scan library (dates, GPS, people, screenshots)")
        scan.clicked.connect(self._run_enrich)
        self.lbl_face = QLabel()
        self.lbl_face.setObjectName("muted")
        row.addWidget(scan)
        row.addWidget(self.lbl_face, 1)
        self.organize_scroll = QScrollArea()
        self.organize_scroll.setWidgetResizable(True)
        self.organize_host = QWidget()
        self.organize_layout = QVBoxLayout(self.organize_host)
        self.organize_scroll.setWidget(self.organize_host)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(row)
        layout.addWidget(self.organize_scroll)

    def _reload_organize(self) -> None:
        self._clear_layout(self.organize_layout)
        opencv = face_engine_available()
        self.lbl_face.setText(
            "Face clustering: OpenCV Haar cascade available (local)."
            if opencv
            else "Face clustering off until you install optional opencv-python-headless. "
            "EXIF/XMP people tags and GPS still work. Unknown people can be named after a scan."
        )
        groups = [
            ("By date", month_suggestions(self.catalog)),
            ("Screenshots (not People)", screenshot_suggestions(self.catalog)),
            ("By person", people_suggestions(self.catalog)),
            ("By location (rounded GPS)", place_suggestions(self.catalog)),
        ]
        for heading, items in groups:
            lab = QLabel(heading)
            lab.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
            self.organize_layout.addWidget(lab)
            if not items:
                empty = QLabel("Nothing to suggest yet. Back up, then scan the library.")
                empty.setObjectName("muted")
                self.organize_layout.addWidget(empty)
                continue
            for sug in items[:40]:
                self.organize_layout.addWidget(self._suggestion_card(sug))
        self.organize_layout.addStretch()

    def _suggestion_card(self, sug: Suggestion) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        box = QHBoxLayout(card)
        box.setContentsMargins(16, 14, 16, 14)
        text = QVBoxLayout()
        title = QLabel(f"{sug.title}")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        meta = QLabel(f"{sug.count} files → {sug.target}")
        meta.setObjectName("muted")
        meta.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(meta)
        box.addLayout(text, 1)
        if sug.kind == "person":
            rename = QPushButton("Rename")
            rename.setObjectName("ghost")
            rename.clicked.connect(lambda _, s=sug: self._rename_person(s))
            box.addWidget(rename)
        apply = QPushButton("Apply…")
        apply.clicked.connect(lambda _, s=sug: self._apply_sug(s))
        if sug.kind == "place" and sug.key == "none":
            apply.setEnabled(False)
        box.addWidget(apply)
        return card

    def _rename_person(self, sug: Suggestion) -> None:
        label, ok = QInputDialog.getText(self, "Name this person", "Display name:", text=sug.title.split(" ·")[0])
        if not ok or not label.strip():
            return
        self.catalog.rename_person(sug.key, label.strip())
        self._reload_organize()

    def _apply_sug(self, sug: Suggestion) -> None:
        ok = QMessageBox.question(
            self,
            "Apply organization",
            f"Move {sug.count} stick files into:\n{sug.target}\n\n"
            "PC originals are not touched. Nothing is deleted.\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return
        n = apply_suggestion(self.catalog, sug)
        QMessageBox.information(self, "Piczop", f"Moved {n} files on this stick.")
        self._reload_organize()

    def _run_enrich(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        self.thread = QThread()
        self.enrich_worker = EnrichWorker(self.catalog)
        self.enrich_worker.moveToThread(self.thread)
        self.thread.started.connect(self.enrich_worker.run)
        self.enrich_worker.finished.connect(self._on_enrich_done)
        self.enrich_worker.finished.connect(self.thread.quit)
        self.lbl_face.setText("Scanning library locally…")
        self.thread.start()

    def _on_enrich_done(self, info: dict) -> None:
        extra = (
            f"OpenCV clustered {info.get('clusters', 0)} people from {info.get('faces', 0)} faces."
            if info.get("opencv")
            else "No OpenCV — people come from EXIF/XMP tags only; remaining faces are unnamed."
        )
        QMessageBox.information(
            self,
            "Scan finished",
            f"Files: {info.get('files')}\n"
            f"GPS: {info.get('gps')}\n"
            f"Screenshots tagged: {info.get('screenshots')}\n"
            f"Named people tags: {info.get('named_tags')}\n{extra}",
        )
        self._reload_organize()

    def _build_settings(self) -> None:
        layout = QVBoxLayout(self.page_settings)
        self.cb_pictures = QCheckBox("Pictures folder")
        self.cb_videos_folder = QCheckBox("Videos folder")
        self.cb_desktop = QCheckBox("Desktop")
        self.cb_downloads = QCheckBox("Downloads")
        self.cb_documents = QCheckBox("Documents")
        self.cb_include_videos = QCheckBox("Include video files")
        self.rb_copy_all = QRadioButton("Copy all, I'll review later")
        self.rb_hold_similar = QRadioButton("Don't copy similar photos until I review")
        self.dup_mode = QButtonGroup(self)
        self.dup_mode.addButton(self.rb_copy_all)
        self.dup_mode.addButton(self.rb_hold_similar)
        if self.settings.copy_similar_before_review:
            self.rb_copy_all.setChecked(True)
        else:
            self.rb_hold_similar.setChecked(True)
        hint = QLabel(
            "Exact byte copies (SHA-256) are still skipped automatically. "
            "Similar photos (pHash) are only proposals: Piczop never merges or deletes "
            "until you confirm on the Review page. PC originals are never deleted. "
            "If you hold similar photos, they go to PiczopLibrary/review/ until you decide."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        for cb, attr in [
            (self.cb_pictures, "scan_pictures"),
            (self.cb_videos_folder, "scan_videos"),
            (self.cb_desktop, "scan_desktop"),
            (self.cb_downloads, "scan_downloads"),
            (self.cb_documents, "scan_documents"),
            (self.cb_include_videos, "include_videos"),
        ]:
            cb.setChecked(getattr(self.settings, attr))
            layout.addWidget(cb)
        layout.addWidget(QLabel("Similar photos"))
        layout.addWidget(self.rb_copy_all)
        layout.addWidget(self.rb_hold_similar)
        layout.addWidget(hint)
        layout.addWidget(QLabel("Extra folders"))
        self.extra_list = QListWidget()
        for p in self.settings.extra_folders:
            self.extra_list.addItem(p)
        row = QHBoxLayout()
        add = QPushButton("Add folder")
        add.setObjectName("ghost")
        remove = QPushButton("Remove selected")
        remove.setObjectName("ghost")
        add.clicked.connect(self._add_folder)
        remove.clicked.connect(self._remove_folder)
        row.addWidget(add)
        row.addWidget(remove)
        save = QPushButton("Save settings")
        save.clicked.connect(self._save_settings)
        layout.addWidget(self.extra_list)
        layout.addLayout(row)
        layout.addWidget(save)
        layout.addStretch()

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Add scan folder")
        if folder:
            self.extra_list.addItem(folder)

    def _remove_folder(self) -> None:
        row = self.extra_list.currentRow()
        if row >= 0:
            self.extra_list.takeItem(row)

    def _save_settings(self) -> None:
        self.settings.scan_pictures = self.cb_pictures.isChecked()
        self.settings.scan_videos = self.cb_videos_folder.isChecked()
        self.settings.scan_desktop = self.cb_desktop.isChecked()
        self.settings.scan_downloads = self.cb_downloads.isChecked()
        self.settings.scan_documents = self.cb_documents.isChecked()
        self.settings.include_videos = self.cb_include_videos.isChecked()
        self.settings.copy_similar_before_review = self.rb_copy_all.isChecked()
        self.settings.extra_folders = [
            self.extra_list.item(i).text() for i in range(self.extra_list.count())
        ]
        self.settings.save()
        QMessageBox.information(self, "Piczop", "Settings saved.")

    def start_backup(self) -> None:
        if self.thread and self.thread.isRunning():
            return
        try:
            level, _free, _total, message = assess_library_space()
        except OSError as exc:
            QMessageBox.warning(
                self,
                "Piczop",
                "Cannot read free space on the library drive. "
                "Is the USB still connected?\n\n"
                f"({exc})",
            )
            return
        if level == "block":
            QMessageBox.warning(self, "Piczop", message)
            return
        if level == "warn":
            reply = QMessageBox.question(
                self,
                "Piczop",
                f"{message}\n\nContinue anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.job = BackupJob(self.catalog, self.settings)
        self.thread = QThread()
        self.worker = BackupWorker(self.job)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.finished.connect(self.thread.quit)
        self.bar.setRange(0, 0)
        self.btn_pause.setText("Pause")
        self.lbl_phase.setText("Starting…")
        self.lbl_counts.setText("")
        self.lbl_eta.setText("Estimating…")
        self.lbl_current.setText("")
        self.lbl_current.setToolTip("")
        self._show(PAGE_PROGRESS)
        self.thread.start()

    def _toggle_pause(self) -> None:
        if not self.job:
            return
        paused = self.job.toggle_pause()
        self.btn_pause.setText("Resume" if paused else "Pause")

    def _cancel_backup(self) -> None:
        if self.job:
            self.job.cancel()

    def _on_progress(self, stats: BackupStats) -> None:
        if stats.abort_reason:
            self.lbl_phase.setText("Backup stopped")
            self.lbl_eta.setText("")
            self.lbl_current.setText(stats.abort_reason)
            self.lbl_current.setToolTip(stats.abort_reason)
            return
        if stats.phase == "scan":
            self.lbl_phase.setText("Finding photos and videos…")
            self.bar.setRange(0, 0)
            self.lbl_counts.setText(f"Found {stats.found} so far…")
            self.lbl_eta.setText("Estimating…")
        elif stats.phase == "copy":
            self.lbl_phase.setText("Copying to this stick…")
            total = stats.total if stats.total is not None else max(stats.found, 1)
            done = stats.processed
            remaining = (
                stats.remaining
                if stats.remaining is not None
                else max(0, total - done)
            )
            self.bar.setRange(0, max(total, 1))
            self.bar.setValue(min(done, total))
            self.lbl_counts.setText(
                f"Total {total}  ·  Done {done}  ·  Remaining {remaining}\n"
                f"Copied {stats.copied}  ·  Skipped exact {stats.skipped}  ·  "
                f"Similar to review {stats.proposed_near}  ·  "
                f"Held in review folder {stats.held_for_review}  ·  "
                f"Errors {stats.errors}  ·  {format_bytes(stats.bytes_copied)}"
            )
            eta = stats.eta_text
            if stats.space_warning:
                eta = f"{eta}  ·  {stats.space_warning}" if eta else stats.space_warning
            self.lbl_eta.setText(eta)
        else:
            # done / cancelled final tick
            self.lbl_phase.setText("Finishing…")
            if stats.total is not None:
                self.bar.setRange(0, max(stats.total, 1))
                self.bar.setValue(min(stats.processed, stats.total))
            self.lbl_counts.setText(
                f"Total {stats.total if stats.total is not None else stats.found}  ·  "
                f"Done {stats.processed}  ·  Remaining {stats.remaining or 0}"
            )
            self.lbl_eta.setText(stats.eta_text if stats.remaining else "")

        self.lbl_current.setText(self._format_current_file(stats.current))
        self.lbl_current.setToolTip(stats.current if stats.current else "")

    @staticmethod
    def _format_current_file(current: str) -> str:
        if not current or current == "Cancelled":
            return current
        try:
            path = Path(current)
            name = path.name
            if name and name != current:
                return f"Reviewing: {name}\n{current}"
        except Exception:
            pass
        return f"Reviewing: {current}"

    def _on_finished(self, stats: BackupStats) -> None:
        self.last_stats = stats
        pending = self.catalog.pending_review_count()
        if stats.abort_reason:
            self.lbl_summary.setText(
                f"Backup stopped.\n\n"
                f"{stats.abort_reason}\n\n"
                f"Found: {stats.found}\n"
                f"Copied before stop: {stats.copied}\n"
                f"Skipped (exact match): {stats.skipped}\n"
                f"Errors: {stats.errors}\n"
                f"Bytes copied: {format_bytes(stats.bytes_copied)}"
            )
            self.btn_summary_review.setVisible(pending > 0)
            self._show(PAGE_SUMMARY)
            self.refresh_home()
            return
        extra = ""
        if stats.error_messages:
            extra = "\n\nSome files could not be copied:\n" + "\n".join(
                stats.error_messages[:8]
            )
        warn = ""
        if stats.space_warning:
            warn = f"\n\nNote: {stats.space_warning}"
        self.lbl_summary.setText(
            f"Backup finished.\n\n"
            f"Found: {stats.found}\n"
            f"Copied: {stats.copied}\n"
            f"Skipped (exact SHA-256 match already on the stick): {stats.skipped}\n"
            f"Similar photos queued for review: {stats.proposed_near}\n"
            f"Copied into review folder (held until you decide): {stats.held_for_review}\n"
            f"{pending} duplicate group{'s' if pending != 1 else ''} need your review.\n"
            f"Errors: {stats.errors}\n"
            f"Bytes copied: {format_bytes(stats.bytes_copied)}"
            f"{warn}"
            f"{extra}"
        )
        self.btn_summary_review.setVisible(pending > 0)
        self._show(PAGE_SUMMARY)
        self.refresh_home()

    def _open_gallery(self) -> None:
        self._set_gallery_mode(self.gallery_mode)
        self._show(PAGE_GALLERY)

    def _clear_gallery_grid(self) -> None:
        while self.gallery_grid.count():
            item = self.gallery_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _thumb_button(self, rec, caption: str | None = None) -> QPushButton:
        dest = Path(rec["dest_path"])
        thumb = ensure_thumb(rec["sha256"], dest, size=320) if rec["kind"] == "photo" else None
        btn = QPushButton()
        btn.setFixedSize(176, 176)
        btn.setObjectName("ghost")
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        if thumb and thumb.exists():
            pix = QPixmap(str(thumb)).scaled(
                164,
                164,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            btn.setIcon(QIcon(pix))
            btn.setIconSize(pix.size())
        else:
            btn.setText(caption or rec["original_name"] or dest.name)
        tip = rec["original_name"] or dest.name
        if rec["loc_key"] if "loc_key" in rec.keys() else None:
            tip += f"\nGPS {rec['loc_key']}"
        if rec["person_label"] if "person_label" in rec.keys() else None:
            tip += f"\n{rec['person_label']}"
        btn.setToolTip(tip)
        btn.clicked.connect(lambda _, p=dest: QDesktopServices.openUrl(QUrl.fromLocalFile(str(p))))
        return btn

    def _reload_thumbs(self) -> None:
        self._clear_gallery_grid()
        mode = self.gallery_mode
        rows = []
        hint = ""
        if mode == "screenshots":
            rows = self.catalog.list_files(origin="screenshot", primaries_only=True, limit=2000)
            hint = "Screenshots only — never mixed with People."
        elif mode == "videos":
            rows = self.catalog.list_files(kind="video", limit=2000)
            hint = "Videos"
        elif mode == "pending":
            rows = self.catalog.list_files(review_pending=True, primaries_only=False, limit=2000)
            hint = "Files still marked pending review."
        elif mode == "people":
            item = self.side_list.currentItem()
            pid = item.data(Qt.ItemDataRole.UserRole) if item else None
            if pid:
                rows = self.catalog.list_files(person_id=pid, primaries_only=True, limit=2000)
                self.catalog.set_ui("gallery_person", str(pid))
            else:
                shas = []
                for pid, _, _ in self.catalog.person_groups():
                    shas.extend(self.catalog.list_files(person_id=pid, primaries_only=True, limit=500))
                rows = shas
            hint = "Camera photos with people tags or face clusters. Screenshots excluded."
        elif mode == "places":
            item = self.side_list.currentItem()
            text = item.text() if item else ""
            key = item.data(Qt.ItemDataRole.UserRole) if item else None
            if text.startswith("No location"):
                rows = self.catalog.list_files(has_gps=False, primaries_only=True, limit=2000)
            elif key:
                rows = self.catalog.list_files(loc_key=key, primaries_only=True, limit=2000)
                self.catalog.set_ui("gallery_place", str(key))
            else:
                rows = self.catalog.list_files(has_gps=True, primaries_only=True, limit=2000)
            hint = "Grouped by rounded GPS (about 1 km). No reverse geocoding, no network."
        else:
            item = self.side_list.currentItem()
            text = item.text() if item else "All"
            ym = None if (not text or text.startswith("All")) else text.split(" ")[0]
            rows = files_for_month(self.catalog, ym)
            hint = "Timeline by capture/created date."
        self.gallery_hint.setText(hint)
        last_month = None
        grid_row = 0
        col = 0
        for rec in rows[:240]:
            stamp = rec["taken_at"] or rec["created_at"] or rec["copied_at"] or ""
            ym = stamp[:7] if stamp else "Unknown"
            if mode == "timeline" and ym != last_month:
                if col:
                    grid_row += 1
                    col = 0
                header = QLabel(ym)
                header.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
                self.gallery_grid.addWidget(header, grid_row, 0, 1, 5)
                grid_row += 1
                last_month = ym
            self.gallery_grid.addWidget(self._thumb_button(rec), grid_row, col)
            col += 1
            if col >= 5:
                col = 0
                grid_row += 1

    def _build_review(self) -> None:
        layout = QVBoxLayout(self.page_review)
        title = QLabel("Review")
        title.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
        hint = QLabel(
            "One group at a time. Your place is saved if you leave or quit. "
            "Merge/delete only affect this stick after Confirm. PC originals are never deleted."
        )
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        nav = QHBoxLayout()
        self.btn_rev_prev = QPushButton("Previous")
        self.btn_rev_prev.setObjectName("ghost")
        self.btn_rev_next = QPushButton("Next")
        self.btn_rev_next.setObjectName("ghost")
        self.lbl_rev_pos = QLabel()
        self.btn_rev_prev.clicked.connect(lambda: self._step_review(-1))
        self.btn_rev_next.clicked.connect(lambda: self._step_review(1))
        nav.addWidget(self.btn_rev_prev)
        nav.addWidget(self.lbl_rev_pos)
        nav.addWidget(self.btn_rev_next)
        nav.addStretch()
        self.review_host = QWidget()
        self.review_layout = QVBoxLayout(self.review_host)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addLayout(nav)
        layout.addWidget(self.review_host, 1)

    def _open_review(self) -> None:
        self._reload_review()
        self._show(PAGE_REVIEW)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _step_review(self, delta: int) -> None:
        groups = self.catalog.pending_review_groups()
        if not groups:
            return
        self._review_index = max(0, min(self._review_index + delta, len(groups) - 1))
        gid = groups[self._review_index][0]
        self.catalog.set_ui("review_group_id", str(gid))
        self._reload_review()

    def _reload_review(self) -> None:
        self._clear_layout(self.review_layout)
        self._review_cards = {}
        groups = self.catalog.pending_review_groups()
        if not groups:
            empty = QLabel("No duplicate groups need review.")
            empty.setObjectName("muted")
            self.review_layout.addWidget(empty)
            self.lbl_rev_pos.setText("0 of 0")
            self.catalog.set_ui("review_group_id", None)
            self.refresh_home()
            return
        saved = self.catalog.get_ui("review_group_id")
        ids = [g[0] for g in groups]
        if saved and saved.isdigit() and int(saved) in ids:
            self._review_index = ids.index(int(saved))
        self._review_index = max(0, min(self._review_index, len(groups) - 1))
        gid, members = groups[self._review_index]
        self.catalog.set_ui("review_group_id", str(gid))
        self.lbl_rev_pos.setText(f"Group {self._review_index + 1} of {len(groups)}")
        self.review_layout.addWidget(self._review_group_card(self._review_index + 1, gid, members))
        sha = self.review_choice.get(gid) or self.catalog.get_ui("review_primary_sha")
        if sha:
            self.review_choice[gid] = sha
            self._select_review(gid, sha)
        trash = self.catalog.trashed_files(limit=20)
        if trash:
            header = QLabel("Trash on this stick (restore anytime)")
            header.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
            self.review_layout.addWidget(header)
            for rec in trash:
                row = QHBoxLayout()
                name = QLabel(rec["original_name"] or Path(rec["dest_path"]).name)
                btn = QPushButton("Restore")
                btn.setObjectName("ghost")
                btn.clicked.connect(lambda _, s=rec["sha256"]: self._restore_trashed(s))
                wrap = QWidget()
                row.addWidget(name)
                row.addWidget(btn)
                wrap.setLayout(row)
                self.review_layout.addWidget(wrap)
        self.review_layout.addStretch()
        self.refresh_home()

    def _review_group_card(self, index: int, group_id: int, members) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 18, 20, 18)
        box.setSpacing(14)
        box.addWidget(QLabel(f"{len(members)} similar photos — pick the one to keep as primary"))
        thumbs = QHBoxLayout()
        thumbs.setSpacing(16)
        bg = QButtonGroup(card)
        bg.setExclusive(True)
        saved = self.review_choice.get(group_id)
        for rec in members:
            wrap = QVBoxLayout()
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setObjectName("pick")
            btn.setFixedSize(220, 220)
            dest = Path(rec["dest_path"])
            thumb = ensure_thumb(rec["sha256"], dest, size=360) if rec["kind"] == "photo" else None
            if thumb and thumb.exists():
                pix = QPixmap(str(thumb)).scaled(
                    200,
                    200,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                btn.setIcon(QIcon(pix))
                btn.setIconSize(pix.size())
            else:
                btn.setText(rec["original_name"] or dest.name)
            btn.setToolTip(
                f"{rec['original_name'] or dest.name}\n{dest}\n{rec['size']} bytes"
            )
            sha = rec["sha256"]
            if saved == sha:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, g=group_id, s=sha: self._select_review(g, s))
            bg.addButton(btn)
            cap = QLabel(rec["original_name"] or dest.name)
            cap.setObjectName("muted")
            cap.setWordWrap(True)
            wrap.addWidget(btn)
            wrap.addWidget(cap)
            cell = QWidget()
            cell.setLayout(wrap)
            thumbs.addWidget(cell)
        thumbs.addStretch()
        box.addLayout(thumbs)
        actions = QHBoxLayout()
        keep_all = QPushButton("Keep all")
        keep_all.setObjectName("ghost")
        keep_pri = QPushButton("Keep this as primary")
        keep_pri.setEnabled(False)
        merge = QPushButton("Merge (remove extras on stick)")
        merge.setObjectName("ghost")
        merge.setEnabled(False)
        delete = QPushButton("Delete extras on stick")
        delete.setObjectName("danger")
        delete.setEnabled(False)
        keep_all.clicked.connect(lambda _, g=group_id: self._act_keep_all(g))
        keep_pri.clicked.connect(lambda _, g=group_id: self._act_keep_primary(g))
        merge.clicked.connect(lambda _, g=group_id: self._act_merge(g))
        delete.clicked.connect(lambda _, g=group_id: self._act_delete_extras(g))
        card.keep_pri = keep_pri
        card.merge = merge
        card.delete = delete
        self._review_cards = getattr(self, "_review_cards", {})
        self._review_cards[group_id] = card
        actions.addWidget(keep_all)
        actions.addWidget(keep_pri)
        actions.addWidget(merge)
        actions.addWidget(delete)
        actions.addStretch()
        box.addLayout(actions)
        return card

    def _select_review(self, group_id: int, sha: str) -> None:
        self.review_choice[group_id] = sha
        self.catalog.set_ui("review_group_id", str(group_id))
        self.catalog.set_ui("review_primary_sha", sha)
        card = getattr(self, "_review_cards", {}).get(group_id)
        if card:
            card.keep_pri.setEnabled(True)
            card.merge.setEnabled(True)
            card.delete.setEnabled(True)

    def _after_review_action(self) -> None:
        self.catalog.set_ui("review_primary_sha", None)
        groups = self.catalog.pending_review_groups()
        if groups:
            self.catalog.set_ui("review_group_id", str(groups[min(self._review_index, len(groups) - 1)][0]))
        self._reload_review()

    def _act_keep_all(self, group_id: int) -> None:
        self.catalog.keep_all(group_id)
        self._after_review_action()

    def _act_keep_primary(self, group_id: int) -> None:
        sha = self.review_choice.get(group_id)
        if not sha:
            return
        self.catalog.keep_primary(group_id, sha)
        self._after_review_action()

    def _confirm_stick_delete(self, group_id: int, title: str) -> str | None:
        sha = self.review_choice.get(group_id)
        if not sha:
            return None
        rows = [r for r in self.catalog.group_members(group_id) if not r["trashed"]]
        extras = [
            r["original_name"] or Path(r["dest_path"]).name
            for r in rows
            if r["sha256"] != sha
        ]
        if not extras:
            QMessageBox.information(self, "Piczop", "No extra copies to remove.")
            return None
        listed = "\n".join(extras)
        ok = QMessageBox.question(
            self,
            title,
            f"These files will be moved to PiczopLibrary/trash/ on this stick only.\n"
            f"PC originals are not touched.\n\n{listed}\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ok != QMessageBox.StandardButton.Yes:
            return None
        return sha

    def _act_merge(self, group_id: int) -> None:
        sha = self._confirm_stick_delete(group_id, "Confirm merge")
        if not sha:
            return
        self.catalog.merge_or_delete_extras(group_id, sha)
        self._after_review_action()

    def _act_delete_extras(self, group_id: int) -> None:
        sha = self._confirm_stick_delete(group_id, "Confirm delete extras")
        if not sha:
            return
        self.catalog.merge_or_delete_extras(group_id, sha)
        self._after_review_action()

    def _restore_trashed(self, sha: str) -> None:
        self.catalog.restore_file(sha)
        self._reload_review()
