#pragma once

#include "fxmanager_guided_color_match.h"
#include "fxmanager_drag_spinbox.h"
#include <QtWidgets>
#include <functional>
#include <cmath>

// Requires the host's KisConfigWidget and configuration interfaces.
namespace fxmanager::guided {
class SamplePreview final : public QWidget
{
public:
    QImage image;
    std::function<void(QColor)> picked;
    std::function<void(QPointF)> pickedAt;

    explicit SamplePreview(QWidget *parent=nullptr) : QWidget(parent)
    {
        setMinimumSize(130,80);
        setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
        setFixedHeight(140);
        setCursor(Qt::CrossCursor);
        setToolTip(i18n("Click to sample. Use the mouse wheel to zoom the preview."));
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
        for(int index=0;index<m_markers.size();++index) {
            const QPointF marker(area.left()+m_markers[index].x()*area.width(),area.top()+m_markers[index].y()*area.height());
            const QRectF circle(marker.x()-8.0,marker.y()-8.0,16.0,16.0);
            painter.setPen(QPen(Qt::white,1.5)); painter.setBrush(QColor(35,105,170,220)); painter.drawEllipse(circle);
            painter.setPen(Qt::white); painter.drawText(circle,Qt::AlignCenter,QString::number(index+1));
        }
    }
    void mousePressEvent(QMouseEvent *event) override
    {
        const QRect area=imageRect(); const QPoint point=event->pos();
        if(event->button()!=Qt::LeftButton || !area.contains(point) || image.isNull()) return;
        const QPointF normalized(std::clamp((point.x()-area.left())/double(qMax(1,area.width())),0.0,1.0),
                                 std::clamp((point.y()-area.top())/double(qMax(1,area.height())),0.0,1.0));
        if(pickedAt) pickedAt(normalized);
        const int x=std::clamp(qRound(normalized.x()*(image.width()-1)),0,image.width()-1);
        const int y=std::clamp(qRound(normalized.y()*(image.height()-1)),0,image.height()-1);
        const QColor color=image.pixelColor(x,y); if(color.alpha()>0 && picked) picked(color);
    }
    void wheelEvent(QWheelEvent *event) override
    {
        if(image.isNull() || event->angleDelta().y()==0) { event->ignore(); return; }
        m_zoom=std::clamp(m_zoom*(event->angleDelta().y()>0 ? 1.2 : 1.0/1.2),0.25,8.0); update(); event->accept();
    }
private:
    QVector<QPointF> m_markers;
    double m_zoom=1.0;
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
        for(const auto &item : {qMakePair(i18n("Source"),m_sourcePreview),qMakePair(i18n("Reference"),m_targetPreview)}) {
            auto *column=new QVBoxLayout; column->addWidget(new QLabel(item.first,this)); column->addWidget(item.second); previews->addLayout(column);
        }
        root->addLayout(previews);
        auto *buttons=new QHBoxLayout;
        buttons->setSpacing(4);
        const auto button=[&](const QString &text,const QString &name,std::function<void()> action) {
            auto *b=new QPushButton(text,this); b->setObjectName(name);
            b->setSizePolicy(QSizePolicy::Expanding,QSizePolicy::Fixed);
            b->setMinimumWidth(0); buttons->addWidget(b,1);
            connect(b,&QPushButton::clicked,this,std::move(action));
        };
        button(i18n("Refresh"),"guided_refresh_source",[this]{setPreview(m_sourcePreview,m_sourceData,m_sourceReader()); emit sigConfigurationItemChanged();});
        button(i18n("Paste"),"guided_paste_reference",[this]{setReference(QApplication::clipboard()->image());});
        button(i18n("Load"),"guided_load_reference",[this]{
            const QString path=QFileDialog::getOpenFileName(this,i18n("Reference Image"),{},i18n("Images (*.png *.jpg *.jpeg *.webp *.bmp *.tif *.tiff)"));
            if(!path.isEmpty()) setReference(QImage(path));
        });
        root->addLayout(buttons);

        auto *sampling=new QHBoxLayout;
        sampling->setSpacing(4);
        sampling->addWidget(new QLabel(i18n("Sampling"),this));
        m_samplingMode=new QComboBox(this); m_samplingMode->setObjectName("guided_sampling_mode");
        m_samplingMode->addItem(i18n("Point"),0);
        m_samplingMode->addItem(i18n("3 x 3 average"),1);
        m_samplingMode->addItem(i18n("5 x 5 average"),2);
        m_samplingMode->setToolTip(i18n("Average RGB using each pixel's alpha as its weight."));
        sampling->addWidget(m_samplingMode);
        auto *recommend=new QPushButton(i18n("Recommend"),this); recommend->setObjectName("guided_recommend");
        recommend->setToolTip(i18n("Analyse the embedded Source and Reference previews and fill four tonal colour pairs. Nothing is applied until you click Apply."));
        connect(recommend,&QPushButton::clicked,this,[this]{recommendTonalPairs();}); sampling->addWidget(recommend);
        m_applyRecommendation=new QPushButton(i18n("Apply"),this); m_applyRecommendation->setObjectName("guided_apply_recommendation");
        m_applyRecommendation->setEnabled(false); sampling->addWidget(m_applyRecommendation);
        connect(m_applyRecommendation,&QPushButton::clicked,this,[this]{applyRecommendations();});
        m_undoRecommendation=new QPushButton(i18n("Undo"),this); m_undoRecommendation->setObjectName("guided_undo_recommendation");
        m_undoRecommendation->setEnabled(false); sampling->addWidget(m_undoRecommendation);
        connect(m_undoRecommendation,&QPushButton::clicked,this,[this]{undoRecommendation();});
        root->addLayout(sampling);
        auto *instruction=new QLabel(i18n("Select a row, then click either preview to sample. Edit any HEX cell by hand."),this);
        instruction->setWordWrap(false); instruction->setSizePolicy(QSizePolicy::Preferred,QSizePolicy::Fixed); root->addWidget(instruction);
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
        m_pairsTable->selectRow(0); root->addWidget(m_pairsTable);
        connect(m_pairsTable,&QTableWidget::itemChanged,this,[this](QTableWidgetItem *item){
            if(item->column()>0) updateCellVisual(item);
            scheduleRebuild();
        });
        m_sourcePreview->picked=[](QColor){};
        m_targetPreview->picked=[](QColor){};
        m_sourcePreview->pickedAt=[this](QPointF p){setSampleAt(1,p);};
        m_targetPreview->pickedAt=[this](QPointF p){setSampleAt(2,p);};
        auto *rowButtons=new QHBoxLayout; rowButtons->setSpacing(4);
        auto *clear=new QPushButton(i18n("Clear Selected Row"),this); clear->setObjectName("guided_clear_selected");
        connect(clear,&QPushButton::clicked,this,[this]{clearSelectedRow();}); rowButtons->addWidget(clear);
        auto *reset=new QPushButton(i18n("Reset Samples"),this); reset->setObjectName("guided_reset");
        connect(reset,&QPushButton::clicked,this,[this]{clearAllSamples();}); rowButtons->addWidget(reset);
        m_exportButton=new QPushButton(i18n("Export LUT .cube"),this); m_exportButton->setObjectName("guided_export_lut");
        connect(m_exportButton,&QPushButton::clicked,this,[this]{exportCube();}); rowButtons->addWidget(m_exportButton);
        m_tonalWarning=new QLabel(this); m_tonalWarning->setObjectName("guided_tonal_warning"); m_tonalWarning->setWordWrap(false); m_tonalWarning->setTextInteractionFlags(Qt::TextSelectableByMouse); m_tonalWarning->setStyleSheet(QStringLiteral("color: #d6a64f;")); rowButtons->addWidget(m_tonalWarning,1);
        root->addLayout(rowButtons);
        auto *parameters=new QVBoxLayout; parameters->setSpacing(3); root->addLayout(parameters);
        add(parameters,"match_strength",i18n("Match Strength"),1,1,i18n("0: original; 1: full colour mapping."));
        add(parameters,"luminance",i18n("Luminance"),0,1,i18n("0: retain source lightness; 1: match sampled target lightness."));
        add(parameters,"chroma",i18n("Chroma"),1,2,i18n("Amount of sampled hue and chroma transfer."));
        add(parameters,"shadow_color",i18n("Shadow Color"),1,1,i18n("0: suppress colour transfer near black; 1: unrestricted transfer."));
        add(parameters,"highlight_warmth",i18n("Highlight Warmth"),1,2,i18n("Scales warm sample shifts in highlights. Does not invent a warm colour."));
        add(parameters,"neutral_protection",i18n("Neutral Protection"),0,1,i18n("Protects unsampled neutral colours; explicit sample matches take priority."));
        add(parameters,"smoothness",i18n("Smoothness"),0.35,1,i18n("How far each sample influences neighbouring colours."));
        m_recommendationStatus=new QLabel(this); m_recommendationStatus->setObjectName("guided_recommendation_status"); m_recommendationStatus->setWordWrap(false); m_recommendationStatus->setMaximumHeight(20); root->addWidget(m_recommendationStatus);
        m_status=new QLabel(this); m_status->setObjectName("guided_status"); m_status->setWordWrap(false); m_status->setMaximumHeight(20); root->addWidget(m_status);
        m_rebuildTimer.setSingleShot(true); m_rebuildTimer.setInterval(100);
        connect(&m_rebuildTimer,&QTimer::timeout,this,[this]{flushRebuild();});
        root->addStretch(1); updateStatus();
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
        config->setProperty("guided_lut",m_recommendationPending ? m_previousLutData : m_lutData);
        config->setProperty("guided_lut_valid",m_recommendationPending ? m_previousValid : m_valid);
        config->setProperty("guided_source_preview",m_sourceData); config->setProperty("guided_reference_preview",m_targetData);
        return config;
    }
    void setConfiguration(const KisPropertiesConfigurationSP config) override
    {
        if(!config) return;
        m_rebuildTimer.stop(); m_rebuildPending=false;
        const QSignalBlocker self(this),table(m_pairsTable);
        for(auto it=m_boxes.begin();it!=m_boxes.end();++it) {
            const QSignalBlocker block(it.value());
            it.value()->setValue(config->getDouble(it.key(),m_defaults.value(it.key()))); it.value()->refreshValueBar();
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
        m_lutData=config->getProperty("guided_lut").toByteArray();
        m_valid=config->getBool("guided_lut_valid",false) && decodeLut(m_lutData).valid;
        m_sourceData=config->getProperty("guided_source_preview").toByteArray(); m_targetData=config->getProperty("guided_reference_preview").toByteArray();
        m_sourcePreview->image=QImage::fromData(m_sourceData,"PNG"); m_targetPreview->image=QImage::fromData(m_targetData,"PNG");
        m_sourcePreview->resetFit(); m_targetPreview->resetFit();
        if(m_sourceData.isEmpty()) setPreview(m_sourcePreview,m_sourceData,m_sourceReader());
        updateCellVisuals(); updatePreviewMarkers(); m_sourcePreview->update(); m_targetPreview->update(); updateStatus();
        // Loading is read-only: never fit a replacement LUT here.
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
        auto *labelWidget=new QLabel(label,this); labelWidget->setMinimumWidth(130); labelWidget->setToolTip(tip); row->addWidget(labelWidget);
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
        clearMarkers(preview); preview->resetFit();
        bytes.clear(); QBuffer buffer(&bytes); buffer.open(QIODevice::WriteOnly); preview->image.save(&buffer,"PNG"); preview->update();
    }
    QColor recommendColor(const QImage &image,int role) const
    {
        if(image.isNull()) return {};
        const double low[4]={0.00,0.25,0.45,0.70};
        const double high[4]={0.25,0.45,0.70,1.01};
        const double centre=(low[role]+std::min(high[role],1.0))*0.5;
        double red=0,green=0,blue=0,weightTotal=0;
        double nearestDistance=1e9; QColor nearest;
        for(int y=0;y<image.height();++y) for(int x=0;x<image.width();++x) {
            const QColor color=image.pixelColor(x,y); if(color.alpha()==0) continue;
            const double lightness=rgbToOklab(color).l;
            const double distance=std::abs(lightness-centre);
            if(distance<nearestDistance) { nearestDistance=distance; nearest=color; }
            if(lightness<low[role] || lightness>=high[role]) continue;
            const double weight=color.alphaF();
            red+=srgbToLinear(color.redF())*weight;
            green+=srgbToLinear(color.greenF())*weight;
            blue+=srgbToLinear(color.blueF())*weight;
            weightTotal+=weight;
        }
        if(weightTotal<=0) return nearest;
        return QColor::fromRgbF(linearToSrgb(red/weightTotal),linearToSrgb(green/weightTotal),linearToSrgb(blue/weightTotal));
    }
    void recommendTonalPairs()
    {
        if(m_sourcePreview->image.isNull() || m_targetPreview->image.isNull()) {
            m_recommendationStatus->setText(i18n("Add both Source and Reference before recommending."));
            return;
        }
        for(int role=0;role<4;++role) {
            m_recommended[role].source=recommendColor(m_sourcePreview->image,role);
            m_recommended[role].target=recommendColor(m_targetPreview->image,role);
            m_recommended[role].valid=m_recommended[role].source.isValid() && m_recommended[role].target.isValid();
        }
        m_hasRecommendation=true;
        QStringList summary;
        for(int role=0;role<4;++role) if(m_recommended[role].valid)
            summary.append(QStringLiteral("%1 %2→%3").arg(tonalRoleName(role),m_recommended[role].source.name(),m_recommended[role].target.name()));
        const QString detail=summary.join(QStringLiteral("  ·  "));
        saveCurrentPairs();
        const QSignalBlocker blocker(m_pairsTable);
        for(int row=0;row<4;++row) {
            m_pairsTable->item(row,1)->setText(m_recommended[row].valid ? m_recommended[row].source.name() : QString());
            m_pairsTable->item(row,2)->setText(m_recommended[row].valid ? m_recommended[row].target.name() : QString());
            m_hasPosition[row][0]=false; m_hasPosition[row][1]=false;
        }
        m_recommendationPending=true;
        m_recommendationStatus->setText(i18n("Recommendation filled — review, then Apply."));
        m_recommendationStatus->setToolTip(detail);
        m_applyRecommendation->setEnabled(true);
        m_undoRecommendation->setEnabled(true);
        updateCellVisuals(); updatePreviewMarkers(); updateStatus();
    }
    void saveCurrentPairs()
    {
        for(int row=0;row<4;++row) for(int column=0;column<2;++column) {
            m_previousPairText[row][column]=m_pairsTable->item(row,column+1)->text();
            m_previousPositions[row][column]=m_positions[row][column];
            m_previousHasPosition[row][column]=m_hasPosition[row][column];
        }
        m_previousBoxValues.clear();
        for(auto it=m_boxes.cbegin();it!=m_boxes.cend();++it) m_previousBoxValues.insert(it.key(),it.value()->value());
        m_previousLutData=m_lutData; m_previousValid=m_valid;
        m_hasPreviousPairs=true;
    }
    void applyRecommendations()
    {
        if(!m_hasRecommendation || !m_recommendationPending) return;
        m_recommendationPending=false; m_applyRecommendation->setEnabled(false);
        m_recommendationStatus->setText(i18n("Recommended pairs applied."));
        rebuild();
    }
    void undoRecommendation()
    {
        if(!m_hasPreviousPairs) return;
        const QSignalBlocker blocker(m_pairsTable);
        for(int row=0;row<4;++row) for(int column=0;column<2;++column) {
            m_pairsTable->item(row,column+1)->setText(m_previousPairText[row][column]);
            m_positions[row][column]=m_previousPositions[row][column]; m_hasPosition[row][column]=m_previousHasPosition[row][column];
        }
        const bool wasPending=m_recommendationPending;
        m_recommendationPending=false; m_hasRecommendation=false; m_hasPreviousPairs=false; m_undoRecommendation->setEnabled(false);
        m_recommendationStatus->setText(i18n("Recommendation undone."));
        m_applyRecommendation->setEnabled(false);
        updateCellVisuals(); updatePreviewMarkers();
        if(wasPending) updateStatus(); else scheduleRebuild();
    }
    void setReference(const QImage &image)
    {
        if(image.isNull()) {m_status->setText(i18n("No readable reference image.")); return;}
        setPreview(m_targetPreview,m_targetData,image); emit sigConfigurationItemChanged();
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
        const int radius=m_samplingMode ? m_samplingMode->currentData().toInt() : 0;
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
    void rebuild()
    {
        const auto lut=buildLut(pairsFromUi(),m_boxes["luminance"]->value(),m_boxes["chroma"]->value(),m_boxes["match_strength"]->value(),m_boxes["neutral_protection"]->value(),m_boxes["smoothness"]->value(),m_boxes["shadow_color"]->value(),m_boxes["highlight_warmth"]->value());
        m_valid=lut.valid; m_lutData=encodeLut(lut); updateStatus(); emit sigConfigurationItemChanged();
    }
    void scheduleRebuild()
    {
        if(m_recommendationPending) { updateStatus(); return; }
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
    void clearSelectedRow()
    {
        const int row=std::max(0,m_pairsTable->currentRow()); const QSignalBlocker blocker(m_pairsTable);
        for(int column=1;column<3;++column) { m_pairsTable->item(row,column)->setText(QString()); m_hasPosition[row][column-1]=false; }
        updateCellVisuals(); updatePreviewMarkers(); scheduleRebuild();
    }
    void clearAllSamples()
    {
        const QSignalBlocker blocker(m_pairsTable);
        for(int row=0;row<4;++row) for(int column=1;column<3;++column) { m_pairsTable->item(row,column)->setText(QString()); m_hasPosition[row][column-1]=false; }
        m_pairsTable->selectRow(0); updateCellVisuals(); updatePreviewMarkers(); scheduleRebuild();
    }
    void updateStatus()
    {
        if(!m_status || !m_exportButton) return;
        const auto pairs=pairsFromUi(); int count=0; for(const auto &pair:pairs) count+=pair.valid;
        m_status->setText(m_recommendationPending ? i18n("Pairs changed — click Apply to rebuild.") :
            m_valid ? i18n("Ready — %1 pairs.").arg(count) :
            count<2 ? i18n("Pick at least two distinct pairs.") : i18n("Mapping unavailable — adjust distinct source colours."));
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
    QComboBox *m_samplingMode=nullptr;
    QPushButton *m_exportButton=nullptr;
    QPushButton *m_applyRecommendation=nullptr,*m_undoRecommendation=nullptr;
    QLabel *m_status=nullptr,*m_tonalWarning=nullptr,*m_recommendationStatus=nullptr;
    QHash<QString,FxManagerDragSpinBox*> m_boxes;
    QHash<QString,QSlider*> m_sliders;
    QHash<QString,double> m_defaults;
    QByteArray m_lutData,m_sourceData,m_targetData;
    std::array<std::array<QPointF,2>,4> m_positions{};
    std::array<std::array<bool,2>,4> m_hasPosition{};
    std::array<Pair,4> m_recommended{};
    std::array<std::array<QString,2>,4> m_previousPairText{};
    std::array<std::array<QPointF,2>,4> m_previousPositions{};
    std::array<std::array<bool,2>,4> m_previousHasPosition{};
    QHash<QString,double> m_previousBoxValues;
    QByteArray m_previousLutData;
    QTimer m_rebuildTimer;
    bool m_rebuildPending=false;
    bool m_valid=false,m_previousValid=false,m_hasRecommendation=false,m_hasPreviousPairs=false,m_recommendationPending=false;
};
}
