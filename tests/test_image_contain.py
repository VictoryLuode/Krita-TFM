import pytest
from qt_test_binding import Qt, QRect, QRectF
from qt_test_binding import QImage, QPixmap, QPainter, QColor, QIcon
from qt_test_binding import QStyleOptionViewItem
from test_search_history_ui import panel, finish
import test_docker as fixture

M = fixture.MODULE
COLORS = ('#ff0000', '#00ff00', '#ffff00', '#ff00ff', '#0000ff')


def bordered_image(width, height):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(COLORS[4]))
    painter = QPainter(image)
    painter.fillRect(0, 0, width, 12, QColor(COLORS[2]))
    painter.fillRect(0, height - 12, width, 12, QColor(COLORS[3]))
    painter.fillRect(0, 0, 12, height, QColor(COLORS[0]))
    painter.fillRect(width - 12, 0, 12, height, QColor(COLORS[1]))
    painter.end()
    return image


@pytest.mark.parametrize('width,height', [(600, 120), (120, 600), (64, 32)])
@pytest.mark.parametrize('tile', [80, 144, 320])
def test_gallery_draws_all_four_edges_at_original_aspect_ratio(tmp_path, width, height, tile):
    p = panel(tmp_path)
    try:
        p.grid.set_tile_size(tile)
        p.append_results([dict(source='pinterest', id='ratio', thumbnail='https://example.com/ratio')], cached_images={})
        p.grid.item(0).setIcon(QIcon(QPixmap.fromImage(bordered_image(width, height))))
        target = QImage(tile, tile, QImage.Format.Format_RGB32)
        target.fill(QColor('#333333'))
        option = QStyleOptionViewItem()
        option.rect = QRect(0, 0, tile, tile)
        option.widget = p.grid
        painter = QPainter(target)
        p.grid.itemDelegate().paint(painter, option, p.grid.model().index(0, 0))
        painter.end()
        points = {color: [] for color in COLORS}
        for y in range(tile):
            for x in range(tile):
                color = target.pixelColor(x, y).name()
                if color in points:
                    points[color].append((x, y))
        assert all(points.values()), 'An image edge was cropped away'
        all_points = [point for group in points.values() for point in group]
        drawn_width = max(x for x, y in all_points) - min(x for x, y in all_points) + 1
        drawn_height = max(y for x, y in all_points) - min(y for x, y in all_points) + 1
        if width < tile - 12 and height < tile - 12:
            assert drawn_width <= width and drawn_height <= height
        # Raster resampling may blend the two outermost rows/columns; test the minor axis in pixels.
        if width >= height:
            assert abs(drawn_height - drawn_width * height / width) <= 2
        else:
            assert abs(drawn_width - drawn_height * width / height) <= 2
        assert min(drawn_width, drawn_height) < tile / 2, 'Letterboxing was replaced by a stretched square'
    finally:
        finish(p)


@pytest.mark.parametrize('width,height', [(600, 120), (120, 600)])
def test_preview_fit_preserves_ratio_and_contains_entire_source(tmp_path, width, height):
    p = panel(tmp_path)
    path = tmp_path / 'ratio.png'
    assert bordered_image(width, height).save(str(path))
    popup = M.ImagePreview(str(path), p)
    try:
        for window_width, window_height in ((500, 300), (180, 500), (96, 128)):
            popup.resize(window_width, window_height)
            popup.fit_image()
            rect = popup.image_rect()
            assert QRectF(popup.rect()).contains(rect)
            assert abs(rect.width() / rect.height() - width / height) < .00001
    finally:
        popup.close()
        finish(p)


def test_small_images_are_not_automatically_enlarged_to_fill_preview(tmp_path):
    p = panel(tmp_path)
    path = tmp_path / 'small.png'
    assert bordered_image(64, 32).save(str(path))
    popup = M.ImagePreview(str(path), p)
    try:
        popup.resize(640, 480)
        popup.fit_image()
        assert popup.image_rect().width() == 64 and popup.image_rect().height() == 32
        popup.zoom_at(popup.image_rect().center(), 1)
        assert popup.image_rect().width() > 64, 'Explicit manual zoom should still work'
    finally:
        popup.close()
        finish(p)
