import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
import test_docker as fixture
from qt_test_binding import QPoint, QPointF, QTimer
from qt_test_binding import QTransform
from qt_test_binding import QWidget, QMenu

PATH=Path(__file__).resolve().parents[1]/'pykrita/quick_image_search/drop_router.py'
M=None
if PATH.exists():
    spec=importlib.util.spec_from_file_location('_quick_image_search_test.drop_router',PATH)
    M=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(M)

class DropRoutingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(M,'Automatic location-based drop routing is missing')
        self.widget=QWidget()
        self.widget.resize(800,600)
        self.widget.move(70,80)
    def tearDown(self):
        if hasattr(self,'widget'):self.widget.close()
    def view(self, transform=None):
        class Document:
            def width(self):return 200
            def height(self):return 100
        class Canvas:
            def wrapAroundMode(self):return False
        class View:
            def document(self):return Document()
            def canvas(self):return Canvas()
            def flakeToCanvasTransform(self):return transform or QTransform.fromTranslate(200,180)
            def flakeToImageTransform(self):return QTransform.fromScale(2,2)
        return View()
    def test_inside_document_is_layer_and_grey_margin_is_reference(self):
        self.assertEqual(M.drop_mode(self.view(),self.widget,self.widget.mapToGlobal(QPoint(250,200))),'layer')
        self.assertEqual(M.drop_mode(self.view(),self.widget,self.widget.mapToGlobal(QPoint(50,50))),'reference')
    def test_rotated_mirrored_zoomed_view_uses_inverse_transform(self):
        transform=QTransform().translate(400,300).rotate(37).scale(-1.7,1.7)
        view=self.view(transform)
        inside=transform.map(QPointF(20,15)).toPoint()
        outside=transform.map(QPointF(180,15)).toPoint()
        self.assertEqual(M.drop_mode(view,self.widget,self.widget.mapToGlobal(inside)),'layer')
        self.assertEqual(M.drop_mode(view,self.widget,self.widget.mapToGlobal(outside)),'reference')
    def test_outside_viewport_and_singular_transform_fail_safely(self):
        self.assertIsNone(M.drop_mode(self.view(),self.widget,self.widget.mapToGlobal(QPoint(-10,50))))
        transform=QTransform.fromScale(0,0)
        self.assertIsNone(M.drop_mode(self.view(transform),self.widget,self.widget.mapToGlobal(QPoint(100,100))))
    def test_polish_before_modal_loop_does_not_consume_reference_choice(self):
        router=M.DropRouter(lambda:None)
        menu=QMenu()
        menu.setObjectName('drop_popup')
        for name in ('Insert as New Layer','Insert as New File Layer','Open in New Document','Insert as Reference Image'):
            menu.addAction(name)
        fixture.APP.installEventFilter(router)
        try:
            router.arm('reference')
            menu.ensurePolished()
            fixture.APP.processEvents()
            QTimer.singleShot(500,menu.close)
            chosen=menu.exec(QPoint(0,0))
            self.assertIsNotNone(chosen,'Polish consumed the selection before the native menu entered its modal loop')
            self.assertEqual(chosen.text(),'Insert as Reference Image')
        finally:
            fixture.APP.removeEventFilter(router)
            menu.close()

    def test_automatic_menu_choice_returns_native_reference_action(self):
        router=M.DropRouter(lambda:None)
        menu=QMenu()
        menu.setObjectName('drop_popup')
        for name in ('Insert as New Layer','Insert as New File Layer','Open in New Document','Insert as Reference Image'):
            menu.addAction(name)
        fixture.APP.installEventFilter(router)
        try:
            router.arm('reference')
            QTimer.singleShot(1500,menu.close)
            chosen=menu.exec(QPoint(0,0))
            self.assertIsNotNone(chosen,'Native drop selection did not complete automatically')
            self.assertEqual(chosen.text(),'Insert as Reference Image')
        finally:
            fixture.APP.removeEventFilter(router)
            menu.close()

    def test_import_file_rejects_bad_mode_path_and_missing_current_document(self):
        router=M.DropRouter(lambda:None)
        with self.assertRaises(ValueError): router.import_file('missing.png','other')
        with self.assertRaises(ValueError): router.import_file('missing.png','layer')
        with self.assertRaisesRegex(ValueError,'document|target'):
            router.current_import_target()

    def test_current_import_target_rejects_ambiguous_visible_views(self):
        app=Mock(); window=Mock(); view=Mock()
        view.document.return_value=object()
        window.activeView.return_value=view
        native=QWidget(); native.setVisible(True); native.inherits=Mock(return_value=True)
        qwindow=Mock(); qwindow.findChildren.return_value=[native,native]
        window.qwindow.return_value=qwindow
        app.activeWindow.return_value=window
        router=M.DropRouter(lambda:app)
        with self.assertRaisesRegex(ValueError,'ambiguous|unique'):
            router.current_import_target()

    def test_failed_explicit_import_clears_transient_state(self):
        router=M.DropRouter(lambda:None)
        native=QWidget(); router._explicit_import=(native,'layer'); router.last_choice='stale'
        with self.assertRaises((ValueError,RuntimeError)):
            router.import_file('missing.png','layer',target=(None,None,None,native,None))
        self.assertIsNone(router._explicit_import)
        self.assertEqual(router.last_choice,'')

if __name__=='__main__':unittest.main(verbosity=2)
