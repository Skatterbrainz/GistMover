"""Draw the app icon (256x256 PNG) with Qt, so no extra tools or image files are needed."""
import os, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF

app = QGuiApplication([])
S = 256
img = QImage(S, S, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setPen(Qt.NoPen)
p.setBrush(QColor("#24292f"))
p.drawRoundedRect(QRectF(8, 8, S - 16, S - 16), 44, 44)
# two "documents" with an arrow between them: gist -> repo
p.setBrush(QColor("#f6f8fa"))
p.drawRoundedRect(QRectF(34, 62, 72, 92), 8, 8)
p.setBrush(QColor("#2da44e"))
p.drawRoundedRect(QRectF(150, 102, 72, 92), 8, 8)
p.setPen(QPen(QColor("#24292f"), 6, Qt.SolidLine, Qt.RoundCap))
for y in (84, 102, 120):
    p.drawLine(48, y, 92, y)
p.setPen(QPen(QColor("#f6f8fa"), 6, Qt.SolidLine, Qt.RoundCap))
for y in (124, 142, 160):
    p.drawLine(164, y, 208, y)
p.setPen(Qt.NoPen)
p.setBrush(QColor("#f6f8fa"))
p.drawPolygon(QPolygonF([QPointF(112, 190), QPointF(112, 222), QPointF(140, 206)]))
p.setPen(QPen(QColor("#f6f8fa"), 10, Qt.SolidLine, Qt.RoundCap))
p.drawLine(60, 206, 114, 206)
p.end()
img.save(sys.argv[1])
