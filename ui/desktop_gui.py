"""
PawConnect Desktop Admin Console (Unit 1: PyQt6 – QtWidgets, QtCore, QtGui).

For shelter managers working at the shelter PC, also offline:
dashboard with charts, rescue cases (incl. importing cases recorded offline),
donations and fund allocation, inventory, and the XML audit log.

Run from the project folder:   python ui/desktop_gui.py     (or: python main.py --desktop)

Like the web app, the console talks only to PawConnectClient: over HTTP when the
API is running (python main.py --api), otherwise in-process (PAWCONNECT_MODE=local).
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: E402
from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtGui import QAction, QColor, QFont, QPalette  # noqa: E402
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,  # noqa: E402
                             QDialogButtonBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                             QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QMainWindow, QMessageBox, QPushButton, QTableWidget,
                             QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from analytics import numpy_stats as ns  # noqa: E402
from analytics import pandas_engine as pe  # noqa: E402
from api.client import ApiError, PawConnectClient  # noqa: E402
from config import ALLOCATABLE_FUNDS, ALLOCATION_PURPOSES, APP_NAME, CASE_STATUSES, COLORS  # noqa: E402
from core.models import User  # noqa: E402
from services.notification_service import format_inr  # noqa: E402

def rgba(hex_color: str, alpha: float) -> str:
    """'#F5877F', 0.15 → 'rgba(245, 135, 127, 0.15)' for Qt style sheets."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


def qcolor(hex_color: str, alpha: float = 1.0) -> QColor:
    color = QColor(hex_color)
    color.setAlphaF(alpha)
    return color


def arrow_icon(color: str, direction: str = "down") -> str:
    """Small SVG triangle for combo/spin boxes (Qt style sheets can't draw one themselves)."""
    folder = Path(tempfile.gettempdir()) / "pawconnect-qss"
    folder.mkdir(exist_ok=True)
    path = folder / f"arrow-{direction}-{color.lstrip('#')}.svg"
    points = "2,4 10,4 6,9" if direction == "down" else "2,8 10,8 6,3"
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12">'
                    f'<polygon points="{points}" fill="{color}"/></svg>')
    return path.as_posix()


def dark_palette(c: dict = COLORS) -> QPalette:
    """Qt's own colours, so widgets the style sheet doesn't reach are dark too (no light flashes)."""
    palette = QPalette()
    roles = {QPalette.ColorRole.Window: c["bg"], QPalette.ColorRole.Base: c["surface"],
             QPalette.ColorRole.AlternateBase: c["raised"], QPalette.ColorRole.Text: c["text"],
             QPalette.ColorRole.WindowText: c["text"], QPalette.ColorRole.Button: c["raised"],
             QPalette.ColorRole.ButtonText: c["text"], QPalette.ColorRole.ToolTipBase: c["raised"],
             QPalette.ColorRole.ToolTipText: c["text"], QPalette.ColorRole.Highlight: c["accent"],
             QPalette.ColorRole.HighlightedText: c["on_accent"], QPalette.ColorRole.PlaceholderText: c["muted"],
             QPalette.ColorRole.Link: c["accent2"]}
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    return palette


def apply_theme(app: QApplication) -> None:
    app.setPalette(dark_palette())
    app.setStyleSheet(build_qss())


def build_qss(c: dict = COLORS) -> str:
    """The whole desktop look, generated from config.COLORS ("Dusk Rose")."""
    return f"""
* {{ font-family: 'Nunito Sans', 'Helvetica Neue', 'Segoe UI', Arial; font-size: 13px; color: {c['text']}; }}
QMainWindow, QDialog, QMessageBox, QFileDialog, QWidget#page {{ background: {c['bg']}; }}
QWidget {{ selection-background-color: {rgba(c['accent'], .28)}; selection-color: {c['text']}; }}
QTabWidget, QTabWidget > QWidget, QStackedWidget {{ background: {c['bg']}; }}
QTabWidget::pane > QWidget, QStackedWidget > QWidget {{ background: {c['surface']}; }}
QLabel {{ background: transparent; }}
QLabel#title {{ font-family: 'Fraunces', Georgia, serif; font-size: 20px; font-weight: 700; }}
QLabel#muted, QLabel#kpiLabel {{ color: {c['muted']}; }}
QLabel#kpiLabel {{ font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel#kpiValue {{ font-family: 'Fraunces', Georgia, serif; font-size: 23px; font-weight: 700; }}
QFrame#accent QLabel#kpiValue {{ color: {c['accent']}; }}

/* ---- tabs */
QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 14px; background: {c['surface']}; top: -1px; padding: 8px; }}
QTabBar {{ background: transparent; }}
QTabBar::tab {{ padding: 8px 16px; margin: 0 4px 6px 0; border-radius: 10px; background: transparent;
               color: {c['muted']}; font-weight: 700; border: 1px solid transparent; }}
QTabBar::tab:hover {{ color: {c['text']}; background: {c['raised']}; }}
QTabBar::tab:selected {{ background: {c['raised']}; color: {c['accent']}; border-color: {c['border']}; }}

/* ---- cards */
QFrame#card, QFrame#accent {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 16px; }}
QFrame#accent {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {rgba(c['accent'], .20)}, stop:0.75 {c['surface']}); }}
QFrame#card[tone="accent"]  {{ border-bottom: 2px solid {c['accent']}; }}
QFrame#card[tone="accent2"] {{ border-bottom: 2px solid {c['accent2']}; }}
QFrame#card[tone="accent3"] {{ border-bottom: 2px solid {c['accent3']}; }}
QFrame#card[tone="success"] {{ border-bottom: 2px solid {c['success']}; }}
QFrame#accent {{ border-bottom: 2px solid {c['accent']}; }}

/* ---- buttons */
QPushButton {{ background: transparent; border: 1px solid {c['border_strong']}; border-radius: 10px;
              padding: 7px 14px; font-weight: 700; color: {c['text']}; }}
QPushButton:hover {{ border-color: {c['accent']}; background: {c['raised']}; }}
QPushButton:pressed {{ background: {c['border']}; }}
QPushButton:focus {{ border: 2px solid {c['accent']}; }}
QPushButton:disabled {{ color: {c['muted']}; border-color: {c['border']}; background: transparent; }}
QPushButton#primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent_fill']}, stop:1 {c['accent_fill_deep']});
                      color: {c['on_accent']}; border: 1px solid {c['accent_fill_deep']}; }}
QPushButton#primary:hover {{ background: {c['accent_fill']}; border-color: {c['text']}; }}
QPushButton#primary:pressed {{ background: {c['accent_fill_deep']}; }}
QPushButton#primary:disabled {{ background: {c['raised']}; color: {c['muted']}; border-color: {c['border']}; }}
QDialogButtonBox QPushButton {{ min-width: 84px; }}

/* ---- inputs */
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit, QPlainTextEdit {{
  background: {c['bg']}; border: 1px solid {c['border']}; border-radius: 9px; padding: 6px 9px; color: {c['text']}; }}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus {{ border: 1px solid {c['accent']}; }}
QLineEdit[echoMode="2"] {{ lineedit-password-character: 9679; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox::down-arrow {{ image: url({arrow_icon(c['muted'])}); width: 12px; height: 12px; margin-right: 8px; }}
QComboBox QAbstractItemView {{ background: {c['raised']}; border: 1px solid {c['border_strong']}; border-radius: 8px;
                              color: {c['text']}; selection-background-color: {rgba(c['accent'], .25)}; outline: 0; padding: 4px; }}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ background: {c['raised']}; border: none; width: 18px; }}
QDoubleSpinBox::up-arrow {{ image: url({arrow_icon(c['muted'], 'up')}); width: 10px; height: 10px; }}
QDoubleSpinBox::down-arrow {{ image: url({arrow_icon(c['muted'])}); width: 10px; height: 10px; }}

/* ---- tables */
QTableWidget, QTableView {{ background: {c['surface']}; alternate-background-color: {rgba(c['raised'], .55)};
  gridline-color: {c['border']}; border: 1px solid {c['border']}; border-radius: 12px; color: {c['text']}; }}
QTableWidget::item:selected {{ background: {rgba(c['accent'], .25)}; color: {c['text']}; }}
QHeaderView {{ background: {c['raised']}; }}
QHeaderView::section {{ background: {c['raised']}; color: {c['muted']}; padding: 7px 8px; border: none;
  border-bottom: 1px solid {c['border']}; font-weight: 700; }}
QTableCornerButton::section {{ background: {c['raised']}; border: none; }}

/* ---- scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c['border_strong']}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {c['muted']}; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; border: none; width: 0; height: 0; }}

/* ---- menus, tooltips, status bar, message boxes */
QMenuBar {{ background: {c['bg']}; color: {c['text']}; }}
QMenuBar::item:selected {{ background: {c['raised']}; }}
QMenu {{ background: {c['raised']}; border: 1px solid {c['border_strong']}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {rgba(c['accent'], .25)}; }}
QToolTip {{ background: {c['raised']}; color: {c['text']}; border: 1px solid {c['border_strong']}; padding: 6px; border-radius: 6px; }}
QStatusBar {{ background: {c['surface']}; color: {c['muted']}; border-top: 1px solid {c['border']}; }}
QStatusBar QLabel {{ color: {c['muted']}; }}
QMessageBox QLabel {{ color: {c['text']}; min-width: 260px; }}
"""


QSS = build_qss()


# ======================================================================= helpers
def fill_table(table: QTableWidget, df: pd.DataFrame, editable_columns: set[str] | None = None,
               headers: list[str] | None = None) -> None:
    """Copy a DataFrame into a QTableWidget."""
    editable_columns = editable_columns or set()
    table.clear()
    table.setRowCount(len(df))
    table.setColumnCount(len(df.columns))
    table.setHorizontalHeaderLabels(headers or [c.replace("_", " ").title() for c in df.columns])
    for r, row in enumerate(df.itertuples(index=False)):
        for c, value in enumerate(row):
            text = "" if pd.isna(value) else str(value)
            item = QTableWidgetItem(text)
            if df.columns[c] not in editable_columns:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(r, c, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)


def table_to_frame(table: QTableWidget, columns: list[str]) -> pd.DataFrame:
    rows = []
    for r in range(table.rowCount()):
        rows.append([table.item(r, c).text() if table.item(r, c) else "" for c in range(table.columnCount())])
    return pd.DataFrame(rows, columns=columns)


def make_table() -> QTableWidget:
    table = QTableWidget()
    table.setAlternatingRowColors(True)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return table


def button(text: str, primary: bool = False) -> QPushButton:
    widget = QPushButton(text)
    if primary:
        widget.setObjectName("primary")
    return widget


def info(parent, text: str) -> None:
    QMessageBox.information(parent, APP_NAME, text)


def warn(parent, error) -> None:
    problems = getattr(error, "problems", [str(error)])
    QMessageBox.warning(parent, APP_NAME, "\n".join(problems))


class KpiCard(QFrame):
    """Muted uppercase label, big number, a 2px coloured line at the bottom (tone)."""

    def __init__(self, label: str, accent: bool = False, tone: str = "accent2"):
        super().__init__()
        self.setObjectName("accent" if accent else "card")
        self.setProperty("tone", tone)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.label = QLabel(label.upper())
        self.label.setObjectName("kpiLabel")
        self.value = QLabel("–")
        self.value.setObjectName("kpiValue")
        self.note = QLabel("")
        self.note.setObjectName("kpiLabel")
        layout.addWidget(self.label)
        layout.addWidget(self.value)
        layout.addWidget(self.note)

    def set(self, value: str, note: str = "") -> None:
        self.value.setText(value)
        self.note.setText(note)


# ======================================================================= login
class LoginDialog(QDialog):
    def __init__(self, client: PawConnectClient | None = None):
        super().__init__()
        self.client = client or PawConnectClient()
        self.user = None
        self.attempts = 0
        self.setWindowTitle(f"{APP_NAME} – Admin sign in")
        self.setMinimumWidth(380)
        layout = QVBoxLayout(self)
        title = QLabel("🐾 PawConnect Admin Console")
        title.setObjectName("title")
        layout.addWidget(title)
        where = "in-process (local mode)" if self.client.mode == "local" else self.client.base_url
        layout.addWidget(QLabel(f"Shelter administrators only. Connected to: {where}"))
        form = QFormLayout()
        self.identifier = QLineEdit()
        self.identifier.setPlaceholderText("admin@pawconnect.org")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("E-mail / mobile", self.identifier)
        form.addRow("Password", self.password)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Sign in")
        buttons.accepted.connect(self.try_login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def try_login(self) -> None:
        try:
            data = self.client.login(self.identifier.text(), self.password.text())
        except ApiError as error:           # wrong password (401), too many attempts (429), API down
            self.attempts += 1
            if self.attempts >= 5:
                QMessageBox.critical(self, APP_NAME, "Too many failed attempts.")
                self.reject()
                return
            warn(self, error)
            return
        if data["role"] != "Admin":
            self.client.logout()
            QMessageBox.warning(self, APP_NAME, "This console is for administrators.")
            return
        self.user = User.from_dict(data)
        self.accept()


# ======================================================================= tabs
class DashboardTab(QWidget):
    def __init__(self, client: PawConnectClient):
        super().__init__()
        self.client = client
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        self.cards = {
            "raised": KpiCard("Total funds raised", accent=True), "avg": KpiCard("Average donation", tone="accent"),
            "std": KpiCard("Std deviation", tone="accent2"), "recovery": KpiCard("Recovery rate", tone="success"),
            "response": KpiCard("Avg response time", tone="accent2"), "beds": KpiCard("Shelter beds in use", tone="accent3"),
            "open": KpiCard("Open cases", tone="accent3"), "available": KpiCard("Funds available", tone="success"),
        }
        for index, card in enumerate(self.cards.values()):
            grid.addWidget(card, index // 4, index % 4)
        layout.addLayout(grid)
        charts = QHBoxLayout()
        self.chart_slots = [QVBoxLayout(), QVBoxLayout()]
        for slot in self.chart_slots:
            charts.addLayout(slot)
        layout.addLayout(charts, stretch=1)
        self.canvases: list[FigureCanvasQTAgg] = []

    def refresh(self) -> None:
        summary = self.client.summary()
        overview = self.client.funds_overview()
        money, response, beds = summary["money"], summary["response_hours"], summary["beds"]
        self.cards["raised"].set(format_inr(money["total"]), f"{int(money['count'])} donations")
        self.cards["avg"].set(format_inr(money["mean"]), f"median {format_inr(money['median'])}")
        self.cards["std"].set(format_inr(money["std"]), f"CV {money['cv']:.0f}%")
        self.cards["recovery"].set(f"{summary['recovery_rate']:.1f}%", "recovered ÷ rescued")
        self.cards["response"].set(f"{response['mean']:.1f} h", f"{response['within_2h']:.0f}% within 2 h")
        self.cards["beds"].set(f"{beds['in_use']} / {beds['total']}")
        self.cards["open"].set(str(summary["open_cases"]), f"{summary['waiting_cases']} unassigned")
        self.cards["available"].set(format_inr(overview["available"].sum()), "general + feed")
        figures = [ns.plot_monthly_trend(summary["monthly_donations"], summary["monthly_expenditure"]),
                   ns.plot_fund_utilization(summary["utilization"])]
        for canvas in self.canvases:
            canvas.setParent(None)
            canvas.deleteLater()
        self.canvases = []
        for slot, figure in zip(self.chart_slots, figures):
            canvas = FigureCanvasQTAgg(figure)
            canvas.setStyleSheet(f"background: {COLORS['surface']}; border-radius: 12px;")   # under the transparent chart
            slot.addWidget(canvas)
            self.canvases.append(canvas)


class CasesTab(QWidget):
    COLUMNS = ["case_id", "reported_at", "animal_type", "injury_level", "status", "pincode",
               "address", "rescuer_id", "estimated_cost", "description"]

    def __init__(self, client: PawConnectClient):
        super().__init__()
        self.client = client
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(["All open", "All"] + CASE_STATUSES)
        self.filter.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search description, pincode or case id…")
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(QLabel("Show"))
        bar.addWidget(self.filter)
        bar.addWidget(self.search, stretch=1)
        layout.addLayout(bar)
        self.table = make_table()
        layout.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        self.rescuer = QComboBox()
        assign = button("Assign rescuer")
        assign.clicked.connect(self.assign)
        advance = button("Advance status ▶", primary=True)
        advance.clicked.connect(self.advance)
        import_button = button("Import offline cases (CSV)…")
        import_button.clicked.connect(self.import_cases)
        export = button("Export CSV…")
        export.clicked.connect(lambda: save_file(self, self.client, "rescue_cases", "csv"))
        actions.addWidget(QLabel("Rescuer"))
        actions.addWidget(self.rescuer)
        actions.addWidget(assign)
        actions.addWidget(advance)
        actions.addStretch()
        actions.addWidget(import_button)
        actions.addWidget(export)
        layout.addLayout(actions)

    def refresh(self) -> None:
        self.rescuer.clear()
        for uid, label in self.client.rescuers().items():
            self.rescuer.addItem(label, uid)
        df = self.client.cases()                # newest first
        choice = self.filter.currentText()
        if choice == "All open":
            df = df[df["status"] != "Recovered"]
        elif choice in CASE_STATUSES:
            df = df[df["status"] == choice]
        text = self.search.text().strip().lower()
        if text:
            df = df[df[["case_id", "description", "pincode", "address"]]
                    .apply(lambda col: col.str.lower().str.contains(text, regex=False)).any(axis=1)]
        fill_table(self.table, df[self.COLUMNS])
        colors = {"Critical": qcolor(COLORS["danger"], 0.15), "Moderate": qcolor(COLORS["accent3"], 0.10)}
        for r in range(self.table.rowCount()):
            color = colors.get(self.table.item(r, 3).text())
            if color:
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setBackground(color)

    def selected_case(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            info(self, "Select a case first.")
            return None
        return self.table.item(row, 0).text()

    def assign(self) -> None:
        case_id = self.selected_case()
        if case_id and self.rescuer.currentData():
            try:
                self.client.assign_case(case_id, self.rescuer.currentData())
                self.refresh()
            except ApiError as error:
                warn(self, error)

    def advance(self) -> None:
        case_id = self.selected_case()
        if not case_id:
            return
        try:
            case = self.client.case(case_id)
            if case["status"] == "Reported":
                if not self.rescuer.currentData():
                    info(self, "Choose a rescuer first.")
                    return
                self.client.assign_case(case_id, self.rescuer.currentData())
            else:
                self.client.advance_case(case_id)
            self.refresh()
        except ApiError as error:
            warn(self, error)

    def import_cases(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import offline cases", str(ROOT / "data"), "CSV files (*.csv)")
        if not path:
            return
        try:
            result = self.client.import_cases(Path(path).read_bytes(), Path(path).name)
        except (ApiError, OSError) as error:
            warn(self, error)
            return
        imported, skipped = result["imported"], result["skipped"]
        message = f"Imported {imported} cases."
        if skipped:
            message += "\n\nSkipped:\n" + "\n".join(skipped[:15])
        info(self, message)
        self.refresh()


class FundsTab(QWidget):
    def __init__(self, client: PawConnectClient):
        super().__init__()
        self.client = client
        layout = QVBoxLayout(self)
        cards = QHBoxLayout()
        self.cards = {name: KpiCard(name, accent=name == "General Shelter Fund", tone="accent2")
                      for name in ["General Shelter Fund", "Specific Medical Case", "Emergency Feed Fund"]}
        for card in self.cards.values():
            cards.addWidget(card)
        layout.addLayout(cards)

        body = QHBoxLayout()
        form_box = QFrame()
        form_box.setObjectName("card")
        form = QFormLayout(form_box)
        heading = QLabel("Allocate funds to a case")
        heading.setObjectName("title")
        form.addRow(heading)
        self.case = QComboBox()
        self.source = QComboBox()
        self.source.addItems(ALLOCATABLE_FUNDS)
        self.purpose = QComboBox()
        self.purpose.addItems(ALLOCATION_PURPOSES)
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0, 1_000_000)
        self.amount.setSingleStep(500)
        self.amount.setPrefix("₹ ")
        self.amount.setValue(2000)
        self.notes = QLineEdit()
        allocate = button("Allocate", primary=True)
        allocate.clicked.connect(self.allocate)
        form.addRow("Case", self.case)
        form.addRow("From fund", self.source)
        form.addRow("Purpose", self.purpose)
        form.addRow("Amount", self.amount)
        form.addRow("Note", self.notes)
        form.addRow(allocate)
        body.addWidget(form_box, stretch=2)

        right = QVBoxLayout()
        right.addWidget(QLabel("Recent donations"))
        self.donations = make_table()
        right.addWidget(self.donations, stretch=1)
        right.addWidget(QLabel("Allocations"))
        self.allocations = make_table()
        right.addWidget(self.allocations, stretch=1)
        body.addLayout(right, stretch=5)
        layout.addLayout(body, stretch=1)

    def refresh(self) -> None:
        overview = self.client.funds_overview()
        for name, card in self.cards.items():
            row = overview.loc[name]
            if row["allocatable"]:
                card.set(format_inr(row["available"]), f"available of {format_inr(row['raised'])}")
            else:
                card.set(format_inr(row["raised"]), "given straight to cases")
        table = self.client.case_funding()
        open_cases = table[~table["status"].isin(["Recovered", "Reported"])]
        self.case.clear()
        for r in open_cases.itertuples():
            self.case.addItem(f"{r.case_id} · {r.animal_type} · {r.injury_level} · gap {format_inr(r.gap)}", r.case_id)
        fill_table(self.donations, self.client.donations().iloc[::-1][["timestamp", "transaction_id", "donor_name",
                                                             "amount", "contribution_type", "case_id",
                                                             "method", "status"]].head(200))
        fill_table(self.allocations, self.client.allocations().iloc[::-1])

    def allocate(self) -> None:
        if not self.case.currentData():
            info(self, "No case in treatment to allocate to.")
            return
        try:
            allocation = self.client.allocate(self.case.currentData(), f"{self.amount.value():.2f}",
                                              self.purpose.currentText(), self.source.currentText(),
                                              self.notes.text())
            info(self, f"{allocation['allocation_id']}: {format_inr(allocation['amount'])} allocated.")
            self.notes.clear()
            self.refresh()
        except ApiError as error:
            warn(self, error)


class InventoryTab(QWidget):
    COLUMNS = ["item_id", "item", "category", "quantity", "unit", "reorder_level", "updated_at"]

    def __init__(self, client: PawConnectClient):
        super().__init__()
        self.client = client
        layout = QVBoxLayout(self)
        self.status = QLabel()
        layout.addWidget(self.status)
        self.table = make_table()
        layout.addWidget(self.table, stretch=1)
        bar = QHBoxLayout()
        add = button("Add item")
        add.clicked.connect(self.add_row)
        save = button("Save stock", primary=True)
        save.clicked.connect(self.save)
        bar.addWidget(add)
        bar.addStretch()
        bar.addWidget(save)
        layout.addLayout(bar)

    def refresh(self) -> None:
        df = self.client.inventory()
        fill_table(self.table, df, editable_columns={"item", "category", "quantity", "unit", "reorder_level"})
        low = pe.low_stock(df)
        for r in range(self.table.rowCount()):
            if self.table.item(r, 0).text() in set(low["item_id"]):
                for c in range(self.table.columnCount()):
                    self.table.item(r, c).setBackground(qcolor(COLORS["danger"], 0.15))
        self.status.setText("⚠️ Low stock: " + ", ".join(low["item"]) if not low.empty else "✅ All stock above reorder level.")

    def add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        for c, value in enumerate(["", "New item", "Medicine", "0", "units", "0", ""]):
            self.table.setItem(row, c, QTableWidgetItem(value))

    def save(self) -> None:
        try:
            count = self.client.save_inventory(table_to_frame(self.table, self.COLUMNS))
            info(self, f"Saved {count} items.")
            self.refresh()
        except ApiError as error:
            warn(self, error)


class AuditTab(QWidget):
    def __init__(self, client: PawConnectClient):
        super().__init__()
        self.client = client
        layout = QVBoxLayout(self)
        bar = QHBoxLayout()
        self.action = QComboBox()
        self.action.currentIndexChanged.connect(self.refresh_table)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search details…")
        self.search.textChanged.connect(self.refresh_table)
        bar.addWidget(QLabel("Action"))
        bar.addWidget(self.action)
        bar.addWidget(self.search, stretch=1)
        layout.addLayout(bar)
        self.table = make_table()
        layout.addWidget(self.table, stretch=1)
        buttons = QHBoxLayout()
        export_log = button("Export audit log (XML)…", primary=True)
        export_log.clicked.connect(self.export_log)
        export_donations = button("Export donations (XML)…")
        export_donations.clicked.connect(lambda: save_file(self, self.client, "donations", "xml"))
        backup = button("Full backup (CSV + XML)")
        backup.clicked.connect(self.backup)
        for widget in (export_log, export_donations, backup):
            buttons.addWidget(widget)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.log = pd.DataFrame()

    def refresh(self) -> None:
        self.log = self.client.audit_log()
        current = self.action.currentText()
        self.action.blockSignals(True)
        self.action.clear()
        self.action.addItems(["All"] + sorted(self.log["action"].unique()))
        self.action.setCurrentText(current or "All")
        self.action.blockSignals(False)
        self.refresh_table()

    def refresh_table(self) -> None:
        df = self.log
        if df.empty:
            fill_table(self.table, df)
            return
        if self.action.currentText() not in ("", "All"):
            df = df[df["action"] == self.action.currentText()]
        if self.search.text():
            df = df[df["details"].str.contains(self.search.text(), case=False, regex=False)]
        fill_table(self.table, df.head(1000))

    def export_log(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save audit log", "audit_logs.xml", "XML (*.xml)")
        if path:
            Path(path).write_bytes(self.client.audit_log_xml())
            info(self, f"Saved {path}")

    def backup(self) -> None:
        try:
            backup = self.client.backup()
        except ApiError as error:
            warn(self, error)
            return
        info(self, f"Backup created with {backup['files']} files in\n{backup['folder']}")


def save_file(parent, client: PawConnectClient, table: str, kind: str) -> None:
    path, _ = QFileDialog.getSaveFileName(parent, f"Export {table}", f"{table}.{kind}",
                                          "CSV (*.csv)" if kind == "csv" else "XML (*.xml)")
    if path:
        Path(path).write_bytes(client.export(table, kind))
        info(parent, f"Saved {path}")


# ======================================================================= main window
class MainWindow(QMainWindow):
    def __init__(self, client: PawConnectClient, admin: User | None = None):
        super().__init__()
        self.client = client
        self.admin = admin = admin or User.from_dict(client.me())
        self.setWindowTitle(f"{APP_NAME} – Shelter Admin Console")
        self.resize(1280, 820)
        self.tabs = QTabWidget()
        self.dashboard = DashboardTab(client)
        self.cases = CasesTab(client)
        self.funds = FundsTab(client)
        self.inventory = InventoryTab(client)
        self.audit = AuditTab(client)
        for widget, label in ((self.dashboard, "📊 Dashboard"), (self.cases, "🚑 Rescue cases"),
                              (self.funds, "💰 Donations && funds"), (self.inventory, "📦 Inventory"),
                              (self.audit, "🗂️ Audit log")):
            self.tabs.addTab(widget, label)
        self.tabs.currentChanged.connect(self.refresh_current)
        self.setCentralWidget(self.tabs)

        menu = self.menuBar().addMenu("&File")
        refresh = QAction("Refresh", self)
        refresh.setShortcut("Ctrl+R")
        refresh.triggered.connect(self.refresh_all)
        quit_action = QAction("Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        menu.addAction(refresh)
        menu.addSeparator()
        menu.addAction(quit_action)
        where = "in-process (local mode)" if client.mode == "local" else client.base_url
        self.statusBar().showMessage(f"Signed in as {admin.name} ({admin.email}) · connected to {where}")
        self.refresh_all()

    def refresh_current(self) -> None:
        try:
            self.tabs.currentWidget().refresh()
        except ApiError as error:
            warn(self, error)

    def refresh_all(self) -> None:
        try:
            for widget in (self.dashboard, self.cases, self.funds, self.inventory, self.audit):
                widget.refresh()
        except ApiError as error:
            warn(self, error)

    def closeEvent(self, event) -> None:
        self.client.logout()            # recorded as LOGOUT in the audit log
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    app.setFont(QFont(app.font().family(), 12))
    login = LoginDialog()
    if login.exec() != QDialog.DialogCode.Accepted or login.user is None:
        return 0
    window = MainWindow(login.client, login.user)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
