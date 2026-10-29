#pragma once

#include <QDoubleSpinBox>
#include <QPoint>

class QEvent;
/// QDoubleSpinBox that also supports Blender-style horizontal dragging.
/// A click still enters the normal editable field; dragging starts only after
/// the pointer moves a few pixels, so direct typing is not stolen.
class FxManagerDragSpinBox final : public QDoubleSpinBox
{
    Q_OBJECT
public:
    explicit FxManagerDragSpinBox(QWidget *parent = nullptr);

    void refreshValueBar();
protected:
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    void updateValueBar();

    bool m_pressed = false;
    bool m_dragging = false;
    QPoint m_pressPosition;
    double m_pressValue = 0.0;
};
