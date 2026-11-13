"""Synthetic presenter used by the capture tests.

Qt Quick renders through Qt's D3D11 RHI backend on Windows, which
creates a real DXGI swap chain that PresentMon can capture.  (A plain
QWidget uses a GDI backing store and produces no present events.)

Run it with pythonw.exe so PresentMon can target a unique process name
("pythonw.exe") without matching the "python.exe" test runner.
"""

import sys

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine


QML = """
import QtQuick
import QtQuick.Window

Window {
    width: 520
    height: 340
    visible: true
    title: "LagLens test presenter"
    color: "#0B0F19"

    Text {
        text: "LagLens presenter"
        color: "#2DD4BF"
        font.pixelSize: 26
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.margins: 24
    }

    Rectangle {
        id: spinner
        width: 120
        height: 120
        radius: 60
        color: "#F87171"
        anchors.centerIn: parent

        RotationAnimator on rotation {
            from: 0
            to: 360
            duration: 900
            loops: Animation.Infinite
        }
    }
}
"""


def main():

    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 8.0

    app = QGuiApplication(sys.argv)

    engine = QQmlApplicationEngine()
    engine.loadData(
        QML.encode("utf-8"),
        QUrl("qrc:/laglens_presenter.qml"),
    )

    if not engine.rootObjects():

        return 2

    QTimer.singleShot(
        int(seconds * 1000),
        app.quit,
    )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
