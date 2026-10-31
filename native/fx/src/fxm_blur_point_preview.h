#pragma once

#include <QImage>
#include <QSizePolicy>
#include <QWidget>
#include <QPainter>
#include <QMouseEvent>
#include <QDoubleSpinBox>
#include <QSignalBlocker>
#include <functional>
#include <algorithm>
#include <kis_paint_device.h>
#include <klocalizedstring.h>

// A bounded UI-only input thumbnail. Never stored in a filter preset or read by
// the pixel processing callbacks. Coordinates use the filter's reference frame.
class FxmBlurPointPreview final : public QWidget
{
public:
    explicit FxmBlurPointPreview(QWidget *parent=nullptr) : QWidget(parent)
    {
        setObjectName("blur_center_preview");
        setMinimumSize(180,120);
        setFixedHeight(160);
        setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
        setCursor(Qt::CrossCursor);
        setToolTip(i18n("Click the image to position the blur center."));
    }
    void setSource(KisPaintDeviceSP device,const QRect &frame)
    {
        m_sourceFrame=frame;
        QSize size=frame.size();
        if(size.width()>640 || size.height()>360)size.scale(QSize(640,360),Qt::KeepAspectRatio);
        m_image=device && !frame.isEmpty() && !size.isEmpty()
            ? device->createThumbnailUncached(size.width(),size.height(),frame) : QImage();
        update();
    }
    void setReferenceFrame(const QRect &frame) { m_referenceFrame=frame; update(); }
    void setCenter(QPointF point) { m_center=point; update(); }
    QPointF center() const { return m_center; }
    void bind(QDoubleSpinBox *x,QDoubleSpinBox *y,std::function<void()> changed)
    {
        m_x=x; m_y=y; m_changed=std::move(changed);
        connect(x,QOverload<double>::of(&QDoubleSpinBox::valueChanged),this,[this](double){setCenter(QPointF(m_x->value(),m_y->value()));});
        connect(y,QOverload<double>::of(&QDoubleSpinBox::valueChanged),this,[this](double){setCenter(QPointF(m_x->value(),m_y->value()));});
    }
    QRect imageRect() const
    {
        if(m_image.isNull()) return {};
        const QSize size=m_image.size().scaled(this->size()-QSize(4,4),Qt::KeepAspectRatio);
        return QRect(QPoint((width()-size.width())/2,(height()-size.height())/2),size);
    }
    std::function<void(QPointF)> picked;
protected:
    void paintEvent(QPaintEvent *) override
    {
        QPainter p(this); p.fillRect(rect(),palette().brush(QPalette::Base));
        p.setPen(palette().color(QPalette::Mid)); p.drawRect(rect().adjusted(0,0,-1,-1));
        if(m_image.isNull()) { p.drawText(rect(),Qt::AlignCenter,i18n("Empty")); return; }
        const QRect area=imageRect(); p.drawImage(area,m_image); p.setClipRect(area);
        if(m_sourceFrame.isEmpty() || m_referenceFrame.isEmpty())return;
        const double gx=m_referenceFrame.x()+m_center.x()*m_referenceFrame.width();
        const double gy=m_referenceFrame.y()+m_center.y()*m_referenceFrame.height();
        const QPointF marker(area.x()+(gx-m_sourceFrame.x())/m_sourceFrame.width()*area.width(),
                             area.y()+(gy-m_sourceFrame.y())/m_sourceFrame.height()*area.height());
        p.setRenderHint(QPainter::Antialiasing);
        for(const auto &pen:{QPen(Qt::black,3),QPen(Qt::white,1)}) {
            p.setPen(pen); p.setBrush(Qt::NoBrush); p.drawEllipse(marker,6,6);
            p.drawLine(marker+QPointF(-11,0),marker+QPointF(11,0));
            p.drawLine(marker+QPointF(0,-11),marker+QPointF(0,11));
        }
    }
    void mousePressEvent(QMouseEvent *event) override
    {
        const QRect area=imageRect();
        if(event->button()!=Qt::LeftButton || !area.contains(event->pos()) || m_referenceFrame.isEmpty())return;
        const double gx=m_sourceFrame.x()+double(event->pos().x()-area.x())/area.width()*m_sourceFrame.width();
        const double gy=m_sourceFrame.y()+double(event->pos().y()-area.y())/area.height()*m_sourceFrame.height();
        const QPointF point((gx-m_referenceFrame.x())/m_referenceFrame.width(),
                            (gy-m_referenceFrame.y())/m_referenceFrame.height());
        if(m_x && m_y) {
            { const QSignalBlocker block(parentWidget()); m_x->setValue(point.x()); m_y->setValue(point.y()); }
            setCenter(QPointF(m_x->value(),m_y->value()));
            if(m_changed)m_changed();
        }
        if(picked)picked(point);
        event->accept();
    }
private:
    QImage m_image;
    QRect m_sourceFrame,m_referenceFrame;
    QPointF m_center{.5,.5};
    QDoubleSpinBox *m_x=nullptr,*m_y=nullptr;
    std::function<void()> m_changed;
};
