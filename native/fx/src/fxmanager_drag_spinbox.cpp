#include "fxmanager_drag_spinbox.h"

#include <QApplication>
#include <QColor>
#include <QEvent>
#include <QLineEdit>
#include <QMouseEvent>
#include <QPainter>
#include <QPaintEvent>
#include <QPalette>
#include <algorithm>
#include <cmath>

namespace {

class FxManagerValueLineEdit final : public QLineEdit
{
public:
    explicit FxManagerValueLineEdit(QWidget *parent)
        : QLineEdit(parent)
    {
        setFrame(false);
        QPalette p = palette();
        p.setColor(QPalette::Base, Qt::transparent);
        p.setColor(QPalette::Window, Qt::transparent);
        setPalette(p);
    }

    void setValueRatio(double ratio)
    {
        m_ratio = std::clamp(ratio, 0.0, 1.0);
        update();
    }

protected:
    void paintEvent(QPaintEvent *event) override
    {
        QPainter painter(this);
        const int filledWidth = qRound(width() * m_ratio);
        painter.fillRect(rect(), QColor(QStringLiteral("#1e1e1e")));
        painter.fillRect(QRect(0, 0, filledWidth, height()),
                         QColor(QStringLiteral("#557b9f")));
        painter.end();
        QLineEdit::paintEvent(event);
    }

private:
    double m_ratio = 0.0;
};

} // namespace

FxManagerDragSpinBox::FxManagerDragSpinBox(QWidget *parent)
    : QDoubleSpinBox(parent)
{
    setLineEdit(new FxManagerValueLineEdit(this));
    setButtonSymbols(QAbstractSpinBox::NoButtons);
    setAlignment(Qt::AlignCenter);
    lineEdit()->installEventFilter(this);
    lineEdit()->setCursor(Qt::SizeHorCursor);
    connect(this, QOverload<double>::of(&QDoubleSpinBox::valueChanged),
            this, &FxManagerDragSpinBox::updateValueBar);
    updateValueBar();
    setToolTip(tr("Drag horizontally to adjust; click to type. Shift: fine adjustment."));
}

void FxManagerDragSpinBox::refreshValueBar()
{
    updateValueBar();
}

void FxManagerDragSpinBox::updateValueBar()
{
    const double span = maximum() - minimum();
    const double ratio = span > 0.0 ? std::clamp((value() - minimum()) / span, 0.0, 1.0) : 0.0;
    if (auto *bar = dynamic_cast<FxManagerValueLineEdit *>(lineEdit())) {
        bar->setValueRatio(ratio);
    }
}
bool FxManagerDragSpinBox::eventFilter(QObject *watched, QEvent *event)
{
    if (watched != lineEdit()) return QDoubleSpinBox::eventFilter(watched, event);
    if (event->type() == QEvent::MouseButtonPress) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (mouse->button() == Qt::LeftButton) {
            interpretText();
            m_pressed = true;
            m_dragging = false;
            m_pressPosition = mouse->globalPos();
            m_pressValue = value();
        }
    } else if (event->type() == QEvent::MouseMove && m_pressed) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        const int dx = mouse->globalPos().x() - m_pressPosition.x();
        if (!m_dragging && std::abs(dx) >= QApplication::startDragDistance()) {
            m_dragging = true;
            lineEdit()->deselect();
        }
        if (m_dragging) {
            const double span = maximum() - minimum();
            const double pixels = std::max(1, lineEdit()->width());
            const double fine = mouse->modifiers().testFlag(Qt::ShiftModifier) ? 0.1 : 1.0;
            const double delta = span > 0.0 ? (span / pixels) * dx * fine : 0.0;
            setValue(std::clamp(m_pressValue + delta, minimum(), maximum()));
            return true;
        }
    } else if (event->type() == QEvent::MouseButtonRelease) {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (mouse->button() == Qt::LeftButton) {
            const bool wasDragging = m_dragging;
            m_pressed = false;
            m_dragging = false;
            if (wasDragging) return true;
        }
    } else if (event->type() == QEvent::UngrabMouse || event->type() == QEvent::Hide) {
        m_pressed = false;
        m_dragging = false;
    }
    return QDoubleSpinBox::eventFilter(watched, event);
}
