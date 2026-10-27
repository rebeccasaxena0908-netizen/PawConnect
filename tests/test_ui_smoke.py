"""Renders every dashboard of the web app and the desktop console without a screen.

The UIs talk to the API through PawConnectClient; tests/helpers.py sets
PAWCONNECT_MODE=local, so the API runs in-process on the temporary database.
"""
import unittest

from tests import helpers
from api.client import PawConnectClient

PASSWORDS = {"karan@example.com": "Citizen@123", "riya@example.com": "Adopter@123",
             "arjun.rescue@pawconnect.org": "Rescuer@123", "ananya@example.com": "Donor@123",
             "admin@pawconnect.org": "Admin@123"}


def signed_in_client(email: str) -> PawConnectClient:
    client = PawConnectClient(mode="local")
    client.login(email, PASSWORDS[email])
    return client


def _streamlit_available() -> bool:
    try:
        from streamlit.testing.v1 import AppTest  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_streamlit_available(), "Streamlit not installed")
class WebAppSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        helpers.fresh_demo_data()

    def _run(self, email=None):
        from streamlit.testing.v1 import AppTest
        app = AppTest.from_file(str(helpers.ROOT / "ui" / "web_app.py"), default_timeout=60)
        if email:
            client = signed_in_client(email)
            app.session_state["token"] = client.token
            app.session_state["user"] = client.user
        app.run()
        self.assertFalse(app.exception, [e.value for e in app.exception])
        self.assertFalse(app.error, [e.value for e in app.error])      # no API error shown either
        return app

    def test_login_page(self):
        app = self._run()
        self.assertTrue(any("second chance" in m.value for m in app.markdown))

    def test_login_form(self):
        app = self._run()
        app.text_input[0].input("admin@pawconnect.org")
        app.text_input[1].input("Admin@123")
        app.button[0].click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state["user"]["role"], "Admin")
        self.assertTrue(app.session_state["token"])                    # the JWT was kept …
        self.assertTrue(any("Shelter administration" in m.value for m in app.markdown))   # … and the dashboard shows

    def test_every_dashboard(self):
        for email in PASSWORDS:
            with self.subTest(email=email):
                self._run(email)


@unittest.skipUnless(__import__("importlib").util.find_spec("PyQt6"), "PyQt6 not installed")
class DesktopSmokeTests(unittest.TestCase):
    def test_main_window(self):
        helpers.fresh_demo_data()
        from PyQt6.QtWidgets import QApplication
        from ui import desktop_gui
        app = QApplication.instance() or QApplication([])
        window = desktop_gui.MainWindow(signed_in_client("admin@pawconnect.org"))
        self.assertGreater(window.cases.table.rowCount(), 0)
        self.assertGreater(window.funds.donations.rowCount(), 0)
        self.assertGreater(window.audit.table.rowCount(), 0)
        self.assertEqual(len(window.dashboard.canvases), 2)
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
