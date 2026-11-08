#pragma once

#include "fxmanager_guided_color_match.h"
#include "fxmanager_drag_spinbox.h"
#include <KisMainWindow.h>
#include <KisPart.h>
#include <KisViewManager.h>
#include <kis_group_layer.h>
#include <kis_image.h>
#include <kis_mask.h>
#include <kis_node.h>
#include <kis_paint_device.h>
#include <QtWidgets>
#include <functional>
#include <cmath>

// Requires the host's KisConfigWidget and configuration interfaces.
namespace fxmanager::guided {

constexpr int kCanvasReferenceMaxEdge = 1536;

inline KisNodeSP layerToExclude(KisNodeSP node)
{
    KisNodeSP current = node;
    while (current && dynamic_cast<KisMask*>(current.data())) {
        current = current->parent();
    }
    return current;
}

inline QSize canvasThumbSize(const QRect &bounds)
{
    QSize size = bounds.size();
    if (size.width() > kCanvasReferenceMaxEdge || size.height() > kCanvasReferenceMaxEdge) {
        size.scale(kCanvasReferenceMaxEdge, kCanvasReferenceMaxEdge, Qt::KeepAspectRatio);
    }
    return QSize(qMax(1, size.width()), qMax(1, size.height()));
}

inline QImage thumbnailDevice(KisPaintDeviceSP device, const QRect &bounds, const QSize &size)
{
    if (!device || bounds.isEmpty() || size.isEmpty()) return {};
    QImage image = device->createThumbnailUncached(size.width(), size.height(), bounds);
    if (image.isNull()) return {};
    return image.convertToFormat(QImage::Format_ARGB32);
}

// Composite visible layers without mutating visibility or calling waitForDone().
// Filter dialogs already own image strokes; waitForDone() here deadlocks the GUI
// ("Waiting for image operation to complete...").
inline void compositeWithoutNode(KisNodeSP node, KisNodeSP excluded,
                                 QPainter &painter, const QRect &bounds, const QSize &size)
{
    if (!node || !node->visible() || node == excluded) return;

    if (dynamic_cast<KisGroupLayer*>(node.data())) {
        for (KisNodeSP child = node->firstChild(); child; child = child->nextSibling()) {
            compositeWithoutNode(child, excluded, painter, bounds, size);
        }
        return;
    }

    KisPaintDeviceSP device = node->projection();
    if (!device) return;
    const QImage thumb = thumbnailDevice(device, bounds, size);
    if (thumb.isNull()) return;
    painter.setOpacity(node->opacity() / 255.0);
    painter.drawImage(0, 0, thumb);
    painter.setOpacity(1.0);
}

inline QImage readCanvasWithoutActiveLayer()
{
    KisMainWindow *mainWindow = KisPart::instance() ? KisPart::instance()->currentMainwindow() : nullptr;
    KisViewManager *view = mainWindow ? mainWindow->viewManager() : nullptr;
    if (!view) return {};
    KisImageSP image = view->image();
    if (!image) return {};

    const QRect bounds = image->bounds();
    if (bounds.isEmpty()) return {};
    const QSize size = canvasThumbSize(bounds);
    KisNodeSP excluded = layerToExclude(view->activeNode());
    KisNodeSP root = image->root();

    if (excluded && root) {
        QImage result(size, QImage::Format_ARGB32);
        result.fill(Qt::transparent);
        {
            QPainter painter(&result);
            painter.setCompositionMode(QPainter::CompositionMode_SourceOver);
            for (KisNodeSP child = root->firstChild(); child; child = child->nextSibling()) {
                compositeWithoutNode(child, excluded, painter, bounds, size);
            }
        }
        for (int y = 0; y < result.height(); ++y) {
            const QRgb *row = reinterpret_cast<const QRgb*>(result.constScanLine(y));
            for (int x = 0; x < result.width(); ++x) {
                if (qAlpha(row[x]) > 0) return result;
            }
        }
    }

    // Fallback: current projection thumbnail (still no waitForDone / visibility toggle).
    return thumbnailDevice(image->projection(), bounds, size);
}
class SamplePreview final : public QWidget
{
public:
    QImage image;
    bool regionSelect=false;
    QRectF region;
    std::function<void(QColor)> picked;
    std::function<void(QPointF)> pickedAt;
    std::function<void()> regionChanged;

    explicit SamplePreview(QWidget *parent=nullptr) : QWidget(parent)
    {
        setMinimumSize(130,80);
        setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
        setFixedHeight(140);
        setCursor(Qt::ArrowCursor);
        setToolTip(i18n("Use the mouse wheel to zoom the preview."));
    }
    void clearRegion()
    {
        if(region.isNull() && !m_regionDragging) return;
        m_regionDragging=false;
        region=QRectF();
        update();
    }
    QRect imageRect() const
    {
        if(image.isNull()) return {};
        const QSize available(qMax(1,width()-4),qMax(1,height()-4));
        QSize size=image.size().scaled(available,Qt::KeepAspectRatio);
        size=QSize(qMax(1,qRound(size.width()*m_zoom)),qMax(1,qRound(size.height()*m_zoom)));
        return QRect(QPoint((width()-size.width())/2,(height()-size.height())/2),size);
    }
    void setMarkers(const QVector<QPointF> &markers) { m_markers=markers; update(); }
    void resetFit() { m_zoom=1.0; update(); }
    double zoom() const { return m_zoom; }
    void paintEvent(QPaintEvent *) override
    {
        QPainter painter(this); painter.setRenderHint(QPainter::Antialiasing);
        painter.fillRect(rect(),palette().brush(QPalette::Base));
        painter.setPen(palette().color(QPalette::Mid)); painter.drawRect(rect().adjusted(0,0,-1,-1));
        if(image.isNull()) { painter.drawText(rect(),Qt::AlignCenter,i18n("Empty")); return; }
        const QRect area=imageRect(); painter.drawImage(area,image); painter.setClipRect(rect());
        if(regionSelect && region.width()>0.0 && region.height()>0.0) {
            const QRectF box(area.left()+region.x()*area.width(), area.top()+region.y()*area.height(),
                             region.width()*area.width(), region.height()*area.height());
            painter.save();
            QPainterPath shade; shade.addRect(rect()); shade.addRect(box);
            painter.setClipPath(shade);
            painter.fillRect(rect(), QColor(0,0,0,110));
            painter.restore();
            painter.setPen(QPen(QColor(90,170,255), 1.5));
            painter.setBrush(Qt::NoBrush);
            painter.drawRect(box);
        }
        for(int index=0;index<m_markers.size();++index) {
            const QPointF marker(area.left()+m_markers[index].x()*area.width(),area.top()+m_markers[index].y()*area.height());
            const QRectF circle(marker.x()-8.0,marker.y()-8.0,16.0,16.0);
            painter.setPen(QPen(Qt::white,1.5)); painter.setBrush(QColor(35,105,170,220)); painter.drawEllipse(circle);
            painter.setPen(Qt::white); painter.drawText(circle,Qt::AlignCenter,QString::number(index+1));
        }
    }
    QPointF normalizedAt(const QPoint &point) const
    {
        const QRect area=imageRect();
        return QPointF(std::clamp((point.x()-area.left())/double(qMax(1,area.width())),0.0,1.0),
                       std::clamp((point.y()-area.top())/double(qMax(1,area.height())),0.0,1.0));
    }
    void mousePressEvent(QMouseEvent *event) override
    {
        const QRect area=imageRect(); const QPoint point=event->pos();
        if(image.isNull() || !area.contains(point)) return;
        if(event->button()==Qt::RightButton && regionSelect) {
            const bool hadRegion=region.width()>=0.02 && region.height()>=0.02;
            m_regionDragging=false;
            region=QRectF();
            update();
            if(hadRegion && regionChanged) regionChanged();
            event->accept();
            return;
        }
        if(event->button()!=Qt::LeftButton) return;
        const bool sampleNow=event->modifiers() & Qt::ControlModifier;
        if(regionSelect && !sampleNow) {
            m_regionDragging=true;
            m_regionAnchor=normalizedAt(point);
            region=QRectF(m_regionAnchor, QSizeF(0,0));
            update();
            event->accept();
            return;
        }
        if(!sampleNow) return;
        const QPointF normalized=normalizedAt(point);
        if(pickedAt) pickedAt(normalized);
        const int x=std::clamp(qRound(normalized.x()*(image.width()-1)),0,image.width()-1);
        const int y=std::clamp(qRound(normalized.y()*(image.height()-1)),0,image.height()-1);
        const QColor color=image.pixelColor(x,y); if(color.alpha()>0 && picked) picked(color);
    }
    void mouseMoveEvent(QMouseEvent *event) override
    {
        if(!m_regionDragging) return;
        region=QRectF(m_regionAnchor, normalizedAt(event->pos())).normalized();
        update();
        event->accept();
    }
    void mouseReleaseEvent(QMouseEvent *event) override
    {
        if(!m_regionDragging || event->button()!=Qt::LeftButton) return;
        m_regionDragging=false;
        region=QRectF(m_regionAnchor, normalizedAt(event->pos())).normalized();
        if(region.width()<0.02 || region.height()<0.02) region=QRectF();
        update();
        if(regionChanged) regionChanged();
        event->accept();
    }
    void wheelEvent(QWheelEvent *event) override
    {
        if(image.isNull() || event->angleDelta().y()==0) { event->ignore(); return; }
        m_zoom=std::clamp(m_zoom*(event->angleDelta().y()>0 ? 1.2 : 1.0/1.2),0.25,8.0); update(); event->accept();
    }
private:
    QVector<QPointF> m_markers;
    double m_zoom=1.0;
    bool m_regionDragging=false;
    QPointF m_regionAnchor;
};

class GuidedWidget final : public KisConfigWidget
{
public:
    GuidedWidget(const QString &id,std::function<QImage()> sourceReader,QWidget *parent=nullptr)
        : KisConfigWidget(parent),m_id(id),m_sourceReader(std::move(sourceReader))
    {
        auto *root=new QVBoxLayout(this);
        root->setContentsMargins(8,6,8,6); root->setSpacing(4);
        auto *previews=new QHBoxLayout;
        m_sourcePreview=new SamplePreview(this); m_sourcePreview->setObjectName("guided_source_preview");
        m_targetPreview=new SamplePreview(this); m_targetPreview->setObjectName("guided_reference_preview");
        m_targetPreview->regionSelect=true;
        m_targetPreview->setToolTip(i18n("Drag to choose which reference colours count. The main tone and the accent colours inside the box are both used. Right-click clears the region. Ctrl+click samples one colour."));
        m_targetPreview->regionChanged=[this]{
            const QRectF region=m_targetPreview->region;
            if(region.width()>=0.02 && region.height()>=0.02) m_matchCleared=false;
            scheduleRebuild();
        };
        for(const auto &item : {qMakePair(i18n("Source"),m_sourcePreview),qMakePair(i18n("Reference"),m_targetPreview)}) {
            auto *column=new QVBoxLayout; column->addWidget(new QLabel(item.first,this)); column->addWidget(item.second); previews->addLayout(column);
        }
        root->addLayout(previews);
        auto *refLabel=new QLabel(i18n("Reference source"),this);
        refLabel->setObjectName(QStringLiteral("guided_reference_source_label"));
        root->addWidget(refLabel);
        auto *buttons=new QHBoxLayout;
        buttons->setSpacing(4);
        const auto button=[&](const QString &text,const QString &name,std::function<void()> action) {
            auto *b=new QPushButton(text,this); b->setObjectName(name);
            b->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
            b->setMinimumWidth(0); buttons->addWidget(b,1);
            connect(b,&QPushButton::clicked,this,std::move(action));
        };
        {
            auto *canvas=new QPushButton(i18n("Canvas"),this);
            canvas->setObjectName(QStringLiteral("guided_canvas_reference"));
            canvas->setToolTip(i18n("Use a thumbnail of the canvas without the active layer as the reference. Does not block on image strokes."));
            canvas->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
            canvas->setMinimumWidth(0);
            buttons->addWidget(canvas,1);
            connect(canvas,&QPushButton::clicked,this,[this]{
                const QImage image=readCanvasWithoutActiveLayer();
                if(image.isNull()) {
                    m_status->setText(i18n("Could not read the canvas without the active layer."));
                    return;
                }
                setReference(image);
            });
        }
        button(i18n("Clipboard"),"guided_paste_reference",[this]{setReference(QApplication::clipboard()->image());});
        button(i18n("File"),"guided_load_reference",[this]{
            const QString path=QFileDialog::getOpenFileName(this,i18n("Reference Image"),{},i18n("Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"));
            if(!path.isEmpty()) setReference(QImage(path));
        });
        auto *clean=new QPushButton(i18n("Clean"),this);
        clean->setObjectName(QStringLiteral("guided_clear_reference"));
        clean->setSizePolicy(QSizePolicy::Fixed,QSizePolicy::Fixed);
        clean->setToolTip(i18n("Clear the current reference image."));
        connect(clean,&QPushButton::clicked,this,[this]{clearReference();});
        buttons->addWidget(clean,0);
        root->addLayout(buttons);

        auto *sampling=new QHBoxLayout;
        sampling->setSpacing(4);
        m_recommendButton=new QPushButton(i18n("Match Color"),this); m_recommendButton->setObjectName("guided_recommend");
        m_recommendButton->setToolTip(i18n("Match colours from the reference onto the current image."));
        connect(m_recommendButton,&QPushButton::clicked,this,[this]{matchColor();}); sampling->addWidget(m_recommendButton);
        m_undoRecommendation=new QPushButton(i18n("Clean"),this); m_undoRecommendation->setObjectName("guided_undo_recommendation");
        m_undoRecommendation->setToolTip(i18n("Cancel colour matching on the current image. Drag a region on Reference to match again."));
        connect(m_undoRecommendation,&QPushButton::clicked,this,[this]{cleanMatch();}); sampling->addWidget(m_undoRecommendation);
        m_exportButton=new QPushButton(i18n("Export LUT .cube"),this); m_exportButton->setObjectName("guided_export_lut");
        connect(m_exportButton,&QPushButton::clicked,this,[this]{exportCube();}); sampling->addWidget(m_exportButton);
        m_pairsTable=new QTableWidget(4,3,this);
        m_pairsTable->setObjectName("guided_pairs");
        m_pairsTable->setHorizontalHeaderLabels({i18n("Role"),i18n("Source"),i18n("Reference")});
        m_pairsTable->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
        m_pairsTable->setSelectionBehavior(QAbstractItemView::SelectRows);
        m_pairsTable->setSelectionMode(QAbstractItemView::SingleSelection);
        m_pairsTable->verticalHeader()->setDefaultSectionSize(23);
        m_pairsTable->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        m_pairsTable->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        m_pairsTable->setFixedHeight(m_pairsTable->horizontalHeader()->sizeHint().height() + 4 * m_pairsTable->verticalHeader()->defaultSectionSize() + 2);
        const QStringList roles={i18n("Shadows"),i18n("Dark Midtones"),i18n("Midtones"),i18n("Highlights")};
        for(int row=0;row<4;++row) {
            for(int col=0;col<3;++col) m_pairsTable->setItem(row,col,new QTableWidgetItem);
            auto *role=m_pairsTable->item(row,0);
            role->setText(roles[row]);
            role->setFlags(role->flags() & ~Qt::ItemIsEditable);
        }
        m_pairsTable->horizontalHeader()->setSectionResizeMode(0,QHeaderView::ResizeToContents);
        m_pairsTable->horizontalHeader()->setSectionResizeMode(1,QHeaderView::Stretch);
        m_pairsTable->horizontalHeader()->setSectionResizeMode(2,QHeaderView::Stretch);
        m_pairsTable->selectRow(0);
        m_pairsTable->setToolTip(i18n("Right-click a row to clear it."));
        m_pairsTable->viewport()->setContextMenuPolicy(Qt::CustomContextMenu);
        connect(m_pairsTable->viewport(),&QWidget::customContextMenuRequested,this,[this](const QPoint &pos){
            const int row=m_pairsTable->indexAt(pos).row();
            if(row>=0) clearRow(row);
        });
        root->addWidget(m_pairsTable);
        root->addLayout(sampling);
        connect(m_pairsTable,&QTableWidget::itemChanged,this,[this](QTableWidgetItem *item){
            if(item->column()>0) updateCellVisual(item);
            scheduleRebuild();
        });
        m_sourcePreview->picked=[](QColor){};
        m_targetPreview->picked=[](QColor){};
        m_sourcePreview->pickedAt=[this](QPointF p){setSampleAt(1,p);};
        m_targetPreview->pickedAt=[this](QPointF p){setSampleAt(2,p);};
        auto *parameters=new QVBoxLayout; parameters->setSpacing(8); root->addLayout(parameters);
        const auto addGroup=[this,parameters](const QString &title,const QString &name){
            auto *box=new QGroupBox(title,this);
            box->setObjectName(name);
            auto *layout=new QVBoxLayout(box);
            layout->setContentsMargins(8,10,8,6);
            layout->setSpacing(3);
            parameters->addWidget(box);
            return layout;
        };
        auto *brightness=addGroup(i18n("Brightness"),QStringLiteral("guided_group_brightness"));
        add(brightness,"align_brightness",i18n("Align Brightness"),1,1,i18n("0 keeps the source brightness. 1 matches the reference brightness."));
        add(brightness,"smoothness",i18n("Smoothness"),0.35,1,i18n("Blurs the lightness profile so tonal bands stay smooth."));
        auto *mainColor=addGroup(i18n("Main Color"),QStringLiteral("guided_group_main"));
        add(mainColor,"match_strength",i18n("Match Strength"),1,1,i18n("0: original colour; 1: full main-colour match."));
        add(mainColor,"chroma",i18n("Chroma"),1,2,i18n("How far each lightness takes the Reference main colour. 1 matches it; above 1 pushes further."));
        auto *subColor=addGroup(i18n("Sub Color"),QStringLiteral("guided_group_sub"));
        add(subColor,"keep_local",i18n("Keep Source Sub Color"),1,1,i18n("0 paints the whole image with the matched colour. 1 keeps colours that leave the main tone and pushes them further out."));
        add(subColor,"match_local",i18n("Match Ref Sub Color"),0,1,i18n("Moves colours that leave the source main tone onto the reference sub colour, even when that sub colour is a different hue. This still works when Keep Source Sub Color is 0."));
        auto *resetDefaults=new QPushButton(i18n("Reset to Defaults"),this);
        resetDefaults->setObjectName(QStringLiteral("guided_reset_defaults"));
        resetDefaults->setToolTip(i18n("Restore these sliders to their default values."));
        connect(resetDefaults,&QPushButton::clicked,this,[this]{resetParameters();});
        parameters->addWidget(resetDefaults);
        m_rebuildTimer.setSingleShot(true); m_rebuildTimer.setInterval(100);
        connect(&m_rebuildTimer,&QTimer::timeout,this,[this]{flushRebuild();});
        root->addStretch(1);
        auto *info=new QFrame(this);
        info->setObjectName(QStringLiteral("guided_info"));
        info->setFrameShape(QFrame::StyledPanel);
        info->setFrameShadow(QFrame::Sunken);
        auto *infoLayout=new QVBoxLayout(info);
        infoLayout->setContentsMargins(8,6,8,6);
        infoLayout->setSpacing(2);
        auto *instruction=new QLabel(i18n("Drag on Reference to choose the colours that count. Accents inside the box stay separate. Right-click clears it. Ctrl+click samples a colour."),info);
        instruction->setObjectName(QStringLiteral("guided_instruction"));
        instruction->setWordWrap(true);
        infoLayout->addWidget(instruction);
        m_emptyHint=new QLabel(i18n("Reference is empty — use Canvas, Clipboard, or File above."),info);
        m_emptyHint->setObjectName(QStringLiteral("guided_empty_hint"));
        m_emptyHint->setWordWrap(true);
        m_emptyHint->setStyleSheet(QStringLiteral("color: #d6a64f;"));
        infoLayout->addWidget(m_emptyHint);
        m_tonalWarning=new QLabel(info);
        m_tonalWarning->setObjectName("guided_tonal_warning");
        m_tonalWarning->setWordWrap(true);
        m_tonalWarning->setTextInteractionFlags(Qt::TextSelectableByMouse);
        m_tonalWarning->setStyleSheet(QStringLiteral("color: #d6a64f;"));
        infoLayout->addWidget(m_tonalWarning);
        m_recommendationStatus=new QLabel(info);
        m_recommendationStatus->setObjectName("guided_recommendation_status");
        m_recommendationStatus->setWordWrap(true);
        m_recommendationStatus->setVisible(false);
        infoLayout->addWidget(m_recommendationStatus);
        m_status=new QLabel(info);
        m_status->setObjectName("guided_status");
        m_status->setWordWrap(true);
        infoLayout->addWidget(m_status);
        root->addWidget(info);
        updateStatus();
    }
    KisPropertiesConfigurationSP configuration() const override
    {
        auto *self=const_cast<GuidedWidget *>(this);
        self->flushRebuild();
        auto *config=new KisFilterConfiguration(m_id,1,KisGlobalResourcesInterface::instance());
        config->setProperty("guided_version",1);
        for(auto it=m_boxes.cbegin();it!=m_boxes.cend();++it)
            config->setProperty(it.key(),m_recommendationPending ? m_previousBoxValues.value(it.key(),it.value()->value()) : it.value()->value());
        std::array<Pair,4> savedPairs=pairsFromUi();
        if(m_recommendationPending) {
            for(int r=0;r<4;++r) for(int c=0;c<2;++c) {
                const QColor color(m_previousPairText[r][c]);
                if(color.isValid()) {
                    if(c==0) savedPairs[r].source=color; else savedPairs[r].target=color;
                    savedPairs[r].valid=savedPairs[r].source.isValid() && savedPairs[r].target.isValid();
                } else savedPairs[r].valid=false;
            }
        }
        config->setProperty("guided_pairs",encodePairs(savedPairs));
        for(int r=0;r<4;++r) for(int c=0;c<2;++c) {
            const QString text=m_recommendationPending ? m_previousPairText[r][c] : m_pairsTable->item(r,c+1)->text();
            config->setProperty(QStringLiteral("guided_sample_%1_%2").arg(r).arg(c),text);
            const bool hasPosition=m_recommendationPending ? m_previousHasPosition[r][c] : m_hasPosition[r][c];
            if(hasPosition) config->setProperty(QStringLiteral("guided_sample_position_%1_%2").arg(r).arg(c),positionString(m_recommendationPending ? m_previousPositions[r][c] : m_positions[r][c]));
        }
        // The display grid is rebuilt from the compact grade. Krita persists this
        // configuration as kritarc "Last Used"/bookmarks, and the raw grid was ~0.5MB.
        const LookTransfer &look=m_recommendationPending ? m_previousLook : m_look;
        const QByteArray lookBytes=encodeLook(look);
        config->setProperty("guided_look",lookBytes.isEmpty() ? QByteArray() : qCompress(lookBytes,9));
        const LightnessStats &sourceStats=m_recommendationPending ? m_previousSourceStats : m_sourceStats;
        const LightnessStats &referenceStats=m_recommendationPending ? m_previousReferenceStats : m_referenceStats;
        config->setProperty("guided_lightness",encodeLightness(sourceStats,referenceStats));
        config->setProperty("guided_lut",QByteArray());
        config->setProperty("guided_lut_valid",m_recommendationPending ? m_previousValid : m_valid);
        // Preview PNGs are session UI only. Krita writes this configuration into
        // kritarc "Last Used"/bookmarks; embedding full previews previously
        // ballooned kritarc to multi-megabyte and made the app feel sluggish.
        config->setProperty("guided_source_preview",QByteArray());
        config->setProperty("guided_reference_preview",QByteArray());
        return config;
    }
    void setConfiguration(const KisPropertiesConfigurationSP config) override
    {
        if(!config) return;
        m_rebuildTimer.stop(); m_rebuildPending=false;
        const QSignalBlocker self(this),table(m_pairsTable);
        for(auto it=m_boxes.begin();it!=m_boxes.end();++it) {
            const QSignalBlocker block(it.value());
            double value=m_defaults.value(it.key());
            if(config->hasProperty(it.key())) {
                const QVariant stored=config->getProperty(it.key());
                value=stored.userType()==QMetaType::Bool ? (stored.toBool()?1.0:0.0) : stored.toDouble();
            }
            it.value()->setValue(value); it.value()->refreshValueBar();
            m_sliders.value(it.key())->setValue(qRound(it.value()->value()*100));
        }
        const auto pairs=decodePairs(config->getProperty("guided_pairs").toByteArray());
        m_recommendationPending=false; m_hasRecommendation=false; m_hasPreviousPairs=false;
        for(int r=0;r<4;++r) for(int c=0;c<2;++c) {
            m_hasPosition[r][c]=false;
            const QString fallback=pairs[r].valid ? (c ? pairs[r].target : pairs[r].source).name() : QString();
            m_pairsTable->item(r,c+1)->setText(config->getString(QStringLiteral("guided_sample_%1_%2").arg(r).arg(c),fallback));
            QPointF position;
            if(parsePosition(config->getString(QStringLiteral("guided_sample_position_%1_%2").arg(r).arg(c)),position)) {
                m_positions[r][c]=position; m_hasPosition[r][c]=true;
            }
        }
        m_look=decodeLook(inflateStored(config->getProperty("guided_look").toByteArray()));
        decodeLightness(config->getProperty("guided_lightness").toByteArray(),m_sourceStats,m_referenceStats);
        if(m_look.valid) {
            m_lutData=encodeLut(buildLookLut(m_look));
        } else {
            const QByteArray stored=inflateStored(config->getProperty("guided_lut").toByteArray());
            m_lutData=stored; // documents saved before guided_look
        }
        m_valid=config->getBool("guided_lut_valid",false) && decodeLut(m_lutData).valid;
        m_sourceData=config->getProperty("guided_source_preview").toByteArray(); m_targetData=config->getProperty("guided_reference_preview").toByteArray();
        m_sourcePreview->image=QImage::fromData(m_sourceData,"PNG"); m_targetPreview->image=QImage::fromData(m_targetData,"PNG");
        m_sourcePreview->resetFit(); m_targetPreview->resetFit();
        if(m_sourceData.isEmpty()) setPreview(m_sourcePreview,m_sourceData,m_sourceReader());
        updateCellVisuals(); updatePreviewMarkers(); m_sourcePreview->update(); m_targetPreview->update(); updateStatus();
        // Let the canvas finish its current frame before walking the other layers.
        QTimer::singleShot(0, this, [this] { useCanvasReference(); });
    }
private:
    static QString positionString(const QPointF &position)
    {
        return QStringLiteral("%1,%2").arg(QString::number(position.x(),'g',9),QString::number(position.y(),'g',9));
    }
    static bool parsePosition(const QString &text,QPointF &position)
    {
        const QStringList parts=text.split(QLatin1Char(',')); if(parts.size()!=2) return false;
        bool xOk=false,yOk=false; const double x=parts[0].toDouble(&xOk),y=parts[1].toDouble(&yOk);
        if(!xOk || !yOk || !std::isfinite(x) || !std::isfinite(y)) return false;
        position=QPointF(std::clamp(x,0.0,1.0),std::clamp(y,0.0,1.0)); return true;
    }
    void add(QVBoxLayout *parameters,const QString &key,const QString &label,double value,double maximum,const QString &tip)
    {
        auto *row=new QHBoxLayout; row->setSpacing(8);
        auto *labelWidget=new QLabel(label,this); labelWidget->setMinimumWidth(168); labelWidget->setToolTip(tip); row->addWidget(labelWidget);
        auto *slider=new QSlider(Qt::Horizontal,this); slider->setObjectName(key+QStringLiteral("_slider"));
        slider->setRange(0,qRound(maximum*100)); slider->setSingleStep(1); slider->setPageStep(10); slider->setValue(qRound(value*100));
        slider->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed); slider->setToolTip(tip); row->addWidget(slider,1);
        auto *box=new FxManagerDragSpinBox(this); box->setObjectName(key);
        box->setRange(0,maximum); box->setDecimals(2); box->setSingleStep(0.01); box->setFixedWidth(74); box->setValue(value); box->refreshValueBar(); box->setToolTip(tip); row->addWidget(box);
        m_boxes[key]=box; m_sliders[key]=slider; m_defaults[key]=value; parameters->addLayout(row);
        connect(slider,&QSlider::valueChanged,box,[box](int v){box->setValue(v/100.0);});
        connect(box,&QDoubleSpinBox::valueChanged,this,[this,slider](double v){const QSignalBlocker blocker(slider);slider->setValue(qRound(v*100));scheduleRebuild();});
    }
    void setPreview(SamplePreview *preview,QByteArray &bytes,const QImage &image)
    {
        if(image.isNull()) return;
        preview->image=image.scaled(768,768,Qt::KeepAspectRatio,Qt::SmoothTransformation).convertToFormat(QImage::Format_ARGB32);
        clearMarkers(preview); preview->resetFit(); preview->clearRegion();
        bytes.clear(); QBuffer buffer(&bytes); buffer.open(QIODevice::WriteOnly); preview->image.save(&buffer,"PNG"); preview->update();
    }
    QColor recommendColor(const QImage &image,int role,bool preferChroma) const
    {
        if(image.isNull()) return {};
        const double low[4]={0.00,0.25,0.45,0.70};
        const double high[4]={0.25,0.45,0.70,1.01};
        const double centre=(low[role]+std::min(high[role],1.0))*0.5;
        double red=0,green=0,blue=0,weightTotal=0;
        double nearestDistance=1e9; QColor nearest;
        double bestChromaScore=-1.0; QColor vivid;
        for(int y=0;y<image.height();++y) for(int x=0;x<image.width();++x) {
            const QColor color=image.pixelColor(x,y); if(color.alpha()==0) continue;
            const Lab lab=rgbToOklab(color);
            const double distance=std::abs(lab.l-centre);
            if(distance<nearestDistance) { nearestDistance=distance; nearest=color; }
            if(lab.l<low[role] || lab.l>=high[role]) continue;
            const double chroma=std::hypot(lab.a,lab.b);
            // Reference grades: prefer saturated exemplars so black silhouettes
            // do not dilute a glowing red band into a muddy brown average.
            const double chromaWeight=preferChroma ? (0.04+chroma)*(0.04+chroma) : 1.0;
            const double weight=color.alphaF()*chromaWeight;
            red+=srgbToLinear(color.redF())*weight;
            green+=srgbToLinear(color.greenF())*weight;
            blue+=srgbToLinear(color.blueF())*weight;
            weightTotal+=weight;
            const double chromaScore=chroma*color.alphaF()*(1.0-std::min(distance,0.2)/0.2);
            if(preferChroma && chromaScore>bestChromaScore) {
                bestChromaScore=chromaScore; vivid=color;
            }
        }
        if(preferChroma && vivid.isValid() && weightTotal>0) {
            // Blend vivid exemplar with the chroma-weighted mean for stability.
            const QColor mean=QColor::fromRgbF(linearToSrgb(red/weightTotal),linearToSrgb(green/weightTotal),linearToSrgb(blue/weightTotal));
            const Lab meanLab=rgbToOklab(mean), vividLab=rgbToOklab(vivid);
            return oklabToRgb({meanLab.l*0.35+vividLab.l*0.65,
                               meanLab.a*0.35+vividLab.a*0.65,
                               meanLab.b*0.35+vividLab.b*0.65});
        }
        if(weightTotal<=0) return nearest;
        return QColor::fromRgbF(linearToSrgb(red/weightTotal),linearToSrgb(green/weightTotal),linearToSrgb(blue/weightTotal));
    }
    void refreshTonalReadout()
    {
        if(!m_sourcePreview || !m_targetPreview || m_sourcePreview->image.isNull() || m_targetPreview->image.isNull()) return;
        const double align=m_boxes["align_brightness"]->value();
        const LookTransfer look=LookTransfer::fromImages(
            m_sourcePreview->image, referenceForMatch(), align,
            0.0, m_boxes["chroma"]->value(), m_boxes["match_strength"]->value(),
            0.0, m_boxes["smoothness"]->value(),
            1.0, 1.0, m_boxes["keep_local"]->value(), m_boxes["match_local"]->value());
        const QSignalBlocker blocker(m_pairsTable);
        for(int role=0;role<4;++role) {
            const QColor source=recommendColor(m_sourcePreview->image,role,false);
            QColor target;
            if(look.valid && source.isValid()) target=oklabToRgb(look.map(rgbToOklab(source)));
            else target=recommendColor(referenceForMatch(),role,true);
            m_pairsTable->item(role,1)->setText(source.isValid() ? source.name() : QString());
            m_pairsTable->item(role,2)->setText(target.isValid() ? target.name() : QString());
            m_hasPosition[role][0]=false; m_hasPosition[role][1]=false;
        }
        updateCellVisuals(); updatePreviewMarkers();
    }
    void matchColor()
    {
        if(!m_sourcePreview || !m_targetPreview || m_sourcePreview->image.isNull() || m_targetPreview->image.isNull()) {
            m_recommendationStatus->setText(i18n("Add both Source and Reference before matching."));
            m_recommendationStatus->setVisible(true);
            return;
        }
        m_matchCleared=false;
        scheduleRebuild();
    }
    void cleanMatch()
    {
        m_matchCleared=true;
        m_rebuildTimer.stop();
        m_rebuildPending=false;
        m_valid=false;
        m_look={};
        m_sourceStats={};
        m_referenceStats={};
        m_lutData.clear();
        m_recommendationStatus->setText(i18n("Colour match cleared."));
        m_recommendationStatus->setVisible(true);
        updateStatus();
        emit sigConfigurationItemChanged();
    }
    QImage referenceForMatch() const
    {
        if(!m_targetPreview || m_targetPreview->image.isNull()) return {};
        const QImage &image=m_targetPreview->image;
        const QRectF region=m_targetPreview->region;
        if(region.width()<0.02 || region.height()<0.02) return image;
        const QRect crop(qRound(region.left()*image.width()), qRound(region.top()*image.height()),
                         qMax(1, qRound(region.width()*image.width())), qMax(1, qRound(region.height()*image.height())));
        return image.copy(crop.intersected(image.rect()));
    }
    void useCanvasReference()
    {
        const QImage image=readCanvasWithoutActiveLayer();
        if(image.isNull()) return;
        setPreview(m_targetPreview,m_targetData,image);
        m_matchCleared=false;
        scheduleRebuild();
    }
    void clearReference()
    {
        m_rebuildTimer.stop();
        m_rebuildPending=false;
        if(m_targetPreview) {
            m_targetPreview->image=QImage();
            m_targetPreview->clearRegion();
            m_targetPreview->update();
        }
        m_targetData.clear();
        m_matchCleared=true;
        m_valid=false;
        m_look={};
        m_sourceStats={};
        m_referenceStats={};
        m_lutData.clear();
        if(m_pairsTable) {
            const QSignalBlocker blocker(m_pairsTable);
            for(int row=0;row<4;++row) m_pairsTable->item(row,2)->setText(QString());
        }
        updateCellVisuals();
        updatePreviewMarkers();
        updateStatus();
        emit sigConfigurationItemChanged();
    }
    void setReference(const QImage &image)
    {
        if(image.isNull()) {m_status->setText(i18n("No readable reference image.")); updateStatus(); return;}
        setPreview(m_targetPreview,m_targetData,image);
        m_matchCleared=false;
        scheduleRebuild();
    }

    void setSampleAt(int column,const QPointF &normalized)
    {
        const int row=std::max(0,m_pairsTable->currentRow());
        const SamplePreview *preview=column==1 ? m_sourcePreview : m_targetPreview;
        const QColor color=sampleColorAt(preview,normalized);
        if(!color.isValid() || color.alpha()==0) return;
        m_positions[row][column-1]=normalized; m_hasPosition[row][column-1]=true;
        m_pairsTable->item(row,column)->setText(color.name()); updatePreviewMarkers();
    }
    QColor sampleColorAt(const SamplePreview *preview,const QPointF &normalized) const
    {
        if(!preview || preview->image.isNull()) return {};
        const int centerX=std::clamp(qRound(normalized.x()*(preview->image.width()-1)),0,preview->image.width()-1);
        const int centerY=std::clamp(qRound(normalized.y()*(preview->image.height()-1)),0,preview->image.height()-1);
        const int radius=2;
        if(radius==0) {
            const QColor color=preview->image.pixelColor(centerX,centerY); return color.alpha()>0 ? color : QColor();
        }
        double red=0,green=0,blue=0,alphaTotal=0,weightTotal=0;
        for(int y=centerY-radius;y<=centerY+radius;++y) for(int x=centerX-radius;x<=centerX+radius;++x) {
            if(x<0 || y<0 || x>=preview->image.width() || y>=preview->image.height()) continue;
            const QColor color=preview->image.pixelColor(x,y); const double weight=color.alphaF();
            if(weight<=0) continue;
            red+=color.redF()*weight; green+=color.greenF()*weight; blue+=color.blueF()*weight;
            alphaTotal+=color.alphaF()*weight; weightTotal+=weight;
        }
        if(weightTotal<=0) return {};
        return QColor::fromRgbF(red/weightTotal,green/weightTotal,blue/weightTotal,alphaTotal/weightTotal);
    }
    std::array<Pair,4> pairsFromUi() const
    {
        std::array<Pair,4> pairs{};
        for(int i=0;i<4;++i) {
            const QColor source(m_pairsTable->item(i,1)->text()),target(m_pairsTable->item(i,2)->text());
            if(source.isValid() && target.isValid()) pairs[i]={true,source,target};
        }
        return pairs;
    }
    void resetParameters()
    {
        for(auto it=m_boxes.begin();it!=m_boxes.end();++it) {
            const QSignalBlocker blockBox(it.value());
            it.value()->setValue(m_defaults.value(it.key()));
            it.value()->refreshValueBar();
            if(QSlider *slider=m_sliders.value(it.key())) {
                const QSignalBlocker blockSlider(slider);
                slider->setValue(qRound(it.value()->value()*100));
            }
        }
        scheduleRebuild();
    }
    void rebuild()
    {
        if(m_matchCleared) { updateStatus(); return; }
        refreshTonalReadout();
        const QImage sourceImage=m_sourcePreview ? m_sourcePreview->image : QImage();
        const QImage referenceImage=referenceForMatch();
        const double align=m_boxes["align_brightness"]->value();
        const LookTransfer look=LookTransfer::fromImages(
            sourceImage, referenceImage, align,
            0.0,
            m_boxes["chroma"]->value(),
            m_boxes["match_strength"]->value(),
            0.0,
            m_boxes["smoothness"]->value(),
            1.0,
            1.0,
            m_boxes["keep_local"]->value(),
            m_boxes["match_local"]->value());
        m_look=look;
        m_sourceStats=imageLightnessStats(sourceImage);
        m_referenceStats=imageLightnessStats(referenceImage);
        Lut lut=buildLookLut(look);
        if(!lut.valid) {
            lut=buildLut(pairsFromUi(),
                         0.0,
                         m_boxes["chroma"]->value(),
                         m_boxes["match_strength"]->value(),
                         0.0,
                         m_boxes["smoothness"]->value(),
                         1.0,
                         1.0,
                         align>0.0,
                         m_sourceStats,
                         m_referenceStats);
        }
        m_valid=lut.valid; m_lutData=encodeLut(lut); updateStatus(); emit sigConfigurationItemChanged();
    }
    void scheduleRebuild()
    {
        if(m_matchCleared || m_recommendationPending) { updateStatus(); return; }
        m_rebuildPending=true; m_rebuildTimer.start(); updateStatus();
    }
    void flushRebuild()
    {
        if(!m_rebuildPending) return;
        m_rebuildTimer.stop(); m_rebuildPending=false; rebuild();
    }
    static int tonalRole(double lightness)
    {
        if(lightness<0.30) return 0; if(lightness<0.50) return 1; if(lightness<0.72) return 2; return 3;
    }
    static QString tonalRoleName(int role)
    {
        return QStringList{i18n("Shadows"),i18n("Dark Midtones"),i18n("Midtones"),i18n("Highlights")}.value(role);
    }
    void updateCellVisual(QTableWidgetItem *item)
    {
        if(!item || item->column()==0) return;
        const QSignalBlocker blocker(m_pairsTable);
        const QColor color(item->text());
        if(!color.isValid()) { item->setIcon(QIcon()); item->setToolTip(item->text().isEmpty() ? QString() : i18n("Invalid HEX colour.")); return; }
        QPixmap pixmap(16,16); pixmap.fill(Qt::transparent); QPainter painter(&pixmap); painter.setRenderHint(QPainter::Antialiasing);
        painter.setPen(QPen(palette().color(QPalette::Mid),1)); painter.setBrush(color); painter.drawRoundedRect(QRectF(1,1,14,14),2,2); item->setIcon(QIcon(pixmap));
        item->setToolTip(i18n("HEX %1\nOKLab L: %2").arg(item->text()).arg(QLocale::c().toString(rgbToOklab(color).l,'f',4)));
    }
    void updateCellVisuals() { for(int r=0;r<4;++r) for(int c=1;c<3;++c) updateCellVisual(m_pairsTable->item(r,c)); }
    void updatePreviewMarkers()
    {
        QVector<QPointF> source,target;
        for(int row=0;row<4;++row) { if(m_hasPosition[row][0]) source.append(m_positions[row][0]); if(m_hasPosition[row][1]) target.append(m_positions[row][1]); }
        m_sourcePreview->setMarkers(source); m_targetPreview->setMarkers(target);
    }
    void clearMarkers(SamplePreview *preview)
    {
        const int column=preview==m_sourcePreview ? 0 : 1;
        for(int row=0;row<4;++row) m_hasPosition[row][column]=false;
        preview->setMarkers({});
    }
    void clearRow(int row)
    {
        if(row<0 || row>=m_pairsTable->rowCount()) return;
        const QSignalBlocker blocker(m_pairsTable);
        for(int column=1;column<3;++column) { m_pairsTable->item(row,column)->setText(QString()); m_hasPosition[row][column-1]=false; }
        updateCellVisuals(); updatePreviewMarkers(); scheduleRebuild();
    }
    void updateStatus()
    {
        if(!m_status || !m_exportButton) return;
        const bool referenceEmpty=!m_targetPreview || m_targetPreview->image.isNull();
        if(m_emptyHint) m_emptyHint->setVisible(referenceEmpty);
        if(m_recommendButton) {
            m_recommendButton->setEnabled(!referenceEmpty && m_sourcePreview && !m_sourcePreview->image.isNull());
        }
        if(m_undoRecommendation) m_undoRecommendation->setEnabled(!m_matchCleared && !referenceEmpty);
        const auto pairs=pairsFromUi(); int count=0; for(const auto &pair:pairs) count+=pair.valid;
        if(referenceEmpty) {
            m_status->setText(i18n("Load a Reference with Canvas, Clipboard, or File."));
        } else if(m_matchCleared) {
            m_status->setText(i18n("Colour match cleared. Drag a region to match again."));
        } else {
            m_status->setText(m_valid ? i18n("Ready — %1 pairs.").arg(count) :
                count<2 ? i18n("Pick at least two distinct pairs.") : i18n("Mapping unavailable — adjust distinct source colours."));
        }
        m_exportButton->setEnabled(!m_recommendationPending && m_valid && decodeLut(m_lutData).valid);
        QStringList warnings;
        for(int row=0;row<4;++row) {
            const QColor source(m_pairsTable->item(row,1)->text()),target(m_pairsTable->item(row,2)->text()); if(!source.isValid() || !target.isValid()) continue;
            const double sourceL=rgbToOklab(source).l,targetL=rgbToOklab(target).l; const int suggested=tonalRole((sourceL+targetL)*0.5);
            if(tonalRole(sourceL)!=tonalRole(targetL) || suggested!=row)
                warnings.append(i18n("Row %1 suggests %2, while the samples suggest %3 (source L %4, reference L %5).").arg(row+1).arg(tonalRoleName(row)).arg(tonalRoleName(suggested)).arg(QLocale::c().toString(sourceL,'f',3)).arg(QLocale::c().toString(targetL,'f',3)));
        }
        m_tonalWarning->setText(warnings.isEmpty() ? QString() : i18n("Tonal roles differ — review samples."));
        m_tonalWarning->setToolTip(warnings.join(QLatin1Char('\n'))); m_tonalWarning->setVisible(!warnings.isEmpty());
    }
    void exportCube()
    {
        const Lut lut=decodeLut(m_lutData); if(!m_valid || !lut.valid) { updateStatus(); return; }
        QString path=QFileDialog::getSaveFileName(this,i18n("Export 3D LUT"),{},i18n("Cube LUT (*.cube)")); if(path.isEmpty()) return;
        if(QFileInfo(path).suffix().isEmpty()) path+=QStringLiteral(".cube");
        QSaveFile file(path); if(!file.open(QIODevice::WriteOnly|QIODevice::Text)) { m_status->setText(i18n("Could not open the LUT export file.")); return; }
        auto writeLine=[&](const QString &line) { return file.write((line+QLatin1Char('\n')).toUtf8())>=0; };
        bool ok=writeLine(QStringLiteral("# Input color space: sRGB")) && writeLine(QStringLiteral("# Output color space: sRGB")) && writeLine(QStringLiteral("TITLE \"Guided Color Match\"")) && writeLine(QStringLiteral("LUT_3D_SIZE %1").arg(Lut::Size)) && writeLine(QStringLiteral("DOMAIN_MIN 0.0 0.0 0.0")) && writeLine(QStringLiteral("DOMAIN_MAX 1.0 1.0 1.0"));
        const QLocale locale=QLocale::c();
        for(int b=0;ok && b<Lut::Size;++b) for(int g=0;ok && g<Lut::Size;++g) for(int r=0;r<Lut::Size;++r) {
            const int base=Lut::index(r,g,b,0); ok=writeLine(QStringLiteral("%1 %2 %3").arg(locale.toString(double(lut.values[base]),'f',9),locale.toString(double(lut.values[base+1]),'f',9),locale.toString(double(lut.values[base+2]),'f',9)));
        }
        if(!ok || !file.commit()) { file.cancelWriting(); m_status->setText(i18n("Could not finish the LUT export.")); return; }
        m_status->setText(i18n("Exported a valid 33 x 33 x 33 LUT."));
    }
    QString m_id;
    std::function<QImage()> m_sourceReader;
    SamplePreview *m_sourcePreview=nullptr,*m_targetPreview=nullptr;
    QTableWidget *m_pairsTable=nullptr;
    QPushButton *m_exportButton=nullptr;
    QPushButton *m_undoRecommendation=nullptr,*m_recommendButton=nullptr;
    QLabel *m_status=nullptr,*m_tonalWarning=nullptr,*m_recommendationStatus=nullptr,*m_emptyHint=nullptr;
    QHash<QString,FxManagerDragSpinBox*> m_boxes;
    QHash<QString,QSlider*> m_sliders;
    QHash<QString,double> m_defaults;
    QByteArray m_lutData,m_sourceData,m_targetData;
    LookTransfer m_look,m_previousLook;
    LightnessStats m_sourceStats,m_referenceStats,m_previousSourceStats,m_previousReferenceStats;
    std::array<std::array<QPointF,2>,4> m_positions{};
    std::array<std::array<bool,2>,4> m_hasPosition{};
    std::array<Pair,4> m_recommended{};
    std::array<std::array<QString,2>,4> m_previousPairText{};
    std::array<std::array<QPointF,2>,4> m_previousPositions{};
    std::array<std::array<bool,2>,4> m_previousHasPosition{};
    QHash<QString,double> m_previousBoxValues;
    QTimer m_rebuildTimer;
    bool m_rebuildPending=false;
    bool m_matchCleared=false;
    bool m_valid=false,m_previousValid=false,m_hasRecommendation=false,m_hasPreviousPairs=false,m_recommendationPending=false;
};
}
