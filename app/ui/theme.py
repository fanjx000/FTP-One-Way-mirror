"""Dark theme: colour tokens + stylesheet for the whole application."""
from __future__ import annotations

BG = "#12151a"
PANEL = "#191d24"
PANEL_2 = "#1f242d"
BORDER = "#2b323d"
TEXT = "#e7ebf2"
TEXT_MUTED = "#8b97a8"
ACCENT = "#4d9cff"
ACCENT_DIM = "#2b5ea8"
OK = "#3ddc97"
WARN = "#f5b544"
ERR = "#ff6b6b"
PURPLE = "#a78bfa"
BLUE = "#5fb0ff"

ACTION_COLORS = {
    "upload_new": OK,
    "upload_update": BLUE,
    "delete": ERR,
    "mkdir": PURPLE,
    "skip": TEXT_MUTED,
    "error": ERR,
}

QSS = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, QDialog {{ background: {BG}; }}

QFrame#card {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#hsep {{ background: {BORDER}; max-height: 1px; border: none; }}

QLabel#title {{ font-size: 19px; font-weight: 600; color: {TEXT}; }}
QLabel#subtitle {{ font-size: 12px; color: {TEXT_MUTED}; }}
QLabel#sectionTitle {{ font-size: 13px; font-weight: 600; color: {TEXT}; }}
QLabel#muted {{ color: {TEXT_MUTED}; }}
QLabel#mono {{ font-family: "Cascadia Mono", "Consolas", monospace; color: {TEXT_MUTED}; }}

QPushButton {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 7px 14px;
    color: {TEXT};
}}
QPushButton:hover {{ background: #262d38; border-color: #3a4353; }}
QPushButton:pressed {{ background: #1a1f27; }}
QPushButton:disabled {{ color: #59637a; border-color: #242a33; background: #171b21; }}
QPushButton#primary {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
    color: #07131f;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: #6aaeff; border-color: #6aaeff; }}
QPushButton#primary:disabled {{ background: #2a3a52; border-color: #2a3a52; color: #6c7d95; }}
QPushButton#ghost {{ background: transparent; border: 1px solid {BORDER}; }}
QPushButton#ghost:hover {{ background: {PANEL_2}; }}
QPushButton#danger {{ color: {ERR}; border-color: #4a2b2b; }}
QPushButton#danger:hover {{ background: #2a1c1c; }}
QPushButton#link {{ background: transparent; border: none; color: {ACCENT}; padding: 4px 6px; }}
QPushButton#link:hover {{ text-decoration: underline; }}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit {{
    background: #10131a;
    border: 1px solid {BORDER};
    border-radius: 7px;
    padding: 6px 9px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled {{ color: #5d6779; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_2};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    outline: none;
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; background: {PANEL_2}; border: none; }}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px; border-radius: 4px;
    border: 1px solid #3d4657; background: #10131a;
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled {{ border-color: #2b323d; background: #171b21; }}

QTableView, QTableWidget {{
    background: {PANEL};
    alternate-background-color: #1c212a;
    border: 1px solid {BORDER};
    border-radius: 9px;
    gridline-color: transparent;
    selection-background-color: #23324a;
    selection-color: {TEXT};
    outline: none;
}}
QTableView::item, QTableWidget::item {{ padding: 5px 8px; border: none; }}
QHeaderView::section {{
    background: {PANEL_2};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 8px;
    font-size: 12px;
    font-weight: 600;
}}
QHeaderView::section:horizontal {{ border-right: 1px solid {BORDER}; }}
QTableCornerButton::section {{ background: {PANEL_2}; border: none; }}

QTabWidget::pane {{ border: none; }}
QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    padding: 8px 16px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{ color: {TEXT}; border-bottom: 2px solid {ACCENT}; }}
QTabBar::tab:hover {{ color: {TEXT}; }}

QProgressBar {{
    background: #10131a;
    border: 1px solid {BORDER};
    border-radius: 6px;
    height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #333c49; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #445064; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #333c49; border-radius: 5px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: transparent; width: 10px; }}
QToolTip {{
    background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER};
    padding: 5px 8px; border-radius: 6px;
}}
QMenu {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 8px; padding: 5px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 5px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}
QListWidget {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 8px; outline: none;
}}
QListWidget::item {{ padding: 7px 9px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {ACCENT_DIM}; color: {TEXT}; }}
QListWidget::item:hover {{ background: {PANEL_2}; }}
"""
