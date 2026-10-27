"""The colour themes: readable contrast, one source of truth, styles built from config."""
import tomllib
import unittest

from tests import helpers
import config


def luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    channel = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a: str, b: str) -> float:
    light, dark = sorted([luminance(a), luminance(b)], reverse=True)
    return (light + 0.05) / (dark + 0.05)


class ThemeTests(unittest.TestCase):
    def test_text_contrast_at_least_4_5(self):
        for name, colors in config.THEMES.items():
            for text in ("text", "muted", "accent", "accent2", "accent3", "danger", "success", "violet"):
                for background in ("bg", "surface", "raised"):
                    with self.subTest(theme=name, text=text, on=background):
                        self.assertGreaterEqual(contrast(colors[text], colors[background]), 4.5)
            self.assertGreaterEqual(contrast(colors["on_accent"], colors["accent_fill"]), 4.5)
            self.assertGreaterEqual(contrast(colors["on_accent"], colors["accent_fill_deep"]), 4.5)

    def test_dusk_rose_values(self):
        expected = {"bg": "#151216", "surface": "#1E1A20", "raised": "#272229", "border": "#362F39",
                    "text": "#F0E9EC", "muted": "#A89BA2", "accent": "#F28FAD", "accent2": "#8FB8F2",
                    "accent3": "#F2C98F", "danger": "#F5877F", "success": "#8FD9B6"}
        self.assertEqual({k: config.COLORS[k] for k in expected}, expected)
        self.assertEqual(config.CHART_PALETTE, ["#8FB8F2", "#F28FAD", "#F2C98F", "#8FD9B6", "#C4A7F2"])
        self.assertEqual(config.COLORS["on_accent"], config.COLORS["bg"])        # dark text on rose

    def test_streamlit_config_matches(self):
        theme = tomllib.loads((helpers.ROOT / ".streamlit" / "config.toml").read_text())["theme"]
        c = config.COLORS_DARK
        self.assertEqual(theme["base"], "dark")
        self.assertEqual(theme["primaryColor"], c["accent"])
        self.assertEqual(theme["backgroundColor"], c["bg"])
        self.assertEqual(theme["secondaryBackgroundColor"], c["surface"])
        self.assertEqual(theme["textColor"], c["text"])
        self.assertEqual(theme["chartCategoricalColors"], config.CHART_PALETTE)

    def test_desktop_style_sheet_uses_the_palette(self):
        from ui.desktop_gui import build_qss
        qss = build_qss()
        for key in ("bg", "surface", "raised", "border", "text", "muted", "accent"):
            self.assertIn(config.COLORS[key], qss)
        self.assertIn("QScrollBar", qss)
        self.assertIn("QComboBox QAbstractItemView", qss)
        self.assertIn("QPushButton#primary:disabled", qss)


if __name__ == "__main__":
    unittest.main()
