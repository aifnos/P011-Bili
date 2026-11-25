import unittest

from captcha_layout_qa import click_point, fixture_html, instrument_component, rect_inside


class CaptchaLayoutHostQaTests(unittest.TestCase):
    def test_synthetic_fixture_is_explicit_and_offline(self):
        for height in (350, 500, 600):
            html = fixture_html(height)
            self.assertIn("SYNTHETIC GEOMETRY ONLY", html)
            self.assertIn("NOT A CAPTCHA", html)
            self.assertIn("window.qaClicks=[]", html)
            for corner in ("qa-tl", "qa-tr", "qa-bl", "qa-br"):
                self.assertIn('id="' + corner + '"', html)
            for forbidden in ("http://", "https://", "geetest_validate", "proof.complete", "initGeetest"):
                self.assertNotIn(forbidden, html)
        for invalid in (100, 349, 601, "500", None):
            with self.assertRaises(ValueError):
                fixture_html(invalid)

    def test_instrumentation_does_not_begin_or_complete_login(self):
        original = "Item { WebEngineView {id:view} }"
        instrumented = instrument_component(original)
        self.assertIn("qaLoadSynthetic", instrumented)
        self.assertIn('view.loadHtml(html, "https://passport.bilibili.com/")', instrumented)
        self.assertNotIn("begin(", instrumented)
        self.assertNotIn("proof.", instrumented)
        self.assertEqual(original, "Item { WebEngineView {id:view} }")
        with self.assertRaises(ValueError):
            instrument_component("Item {}")

    def test_css_click_mapping_with_zoom_and_screen_offset(self):
        rect = {"left": 100, "right": 164, "top": 500, "bottom": 544}
        self.assertEqual(click_point(rect, 0.3, (0, 66)), (40, 223))
        self.assertEqual(click_point(rect, 0.5, (4, 66)), (70, 327))
        with self.assertRaises(ValueError):
            click_point(rect, 0, (0, 0))

    def test_visible_area_checks_all_edges(self):
        bounds = {"left": 0, "top": 66, "right": 800, "bottom": 268}
        self.assertTrue(rect_inside({"left": 704, "top": 66, "right": 800, "bottom": 114}, bounds))
        self.assertFalse(rect_inside({"left": 704, "top": 230, "right": 800, "bottom": 278}, bounds))
        self.assertFalse(rect_inside({"left": -10, "top": 66, "right": 86, "bottom": 114}, bounds))


if __name__ == "__main__":
    unittest.main()
