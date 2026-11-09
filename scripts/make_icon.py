"""Generate packaging/icon.ico (and icon.png) with Qt, no external assets: python scripts/make_icon.py"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen

app = QGuiApplication(sys.argv[:1])
out = Path(__file__).resolve().parent.parent / "packaging"
for size in (256,):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#0b0d10")); p.setPen(QPen(QColor("#38bdf8"), size * 0.05))
    p.drawEllipse(QRectF(size * .05, size * .05, size * .9, size * .9))
    p.setPen(QColor("#e6ebf0")); f = QFont("Segoe UI", int(size * .28)); f.setBold(True); p.setFont(f)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, "RE")
    p.end()
    img.save(str(out / "icon.png"))
    print("icon.ico written:", img.save(str(out / "icon.ico")))
