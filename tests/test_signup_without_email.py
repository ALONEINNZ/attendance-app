import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import app as app_module


class SignupWithoutEmailTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_main.db")
        self.original_db_file = app_module.DB_FILE
        app_module.DB_FILE = self.db_path
        app_module.init_db()

        app_module.app.config.update(TESTING=True)
        self.client = app_module.app.test_client()

    def tearDown(self):
        app_module.DB_FILE = self.original_db_file
        self.temp_dir.cleanup()

    def test_signup_creates_verified_account_without_email(self):
        with patch.object(app_module, "send_email", return_value=(False, "disabled")):
            response = self.client.post(
                "/signup",
                data={
                    "username": "student1",
                    "password": "password123",
                    "confirm_password": "password123",
                    "email": "student1@burnside.school.nz",
                    "code": "12345",
                },
            )

        self.assertIn(b"Account created", response.data)

        conn = sqlite3.connect(self.db_path)
        user = conn.execute(
            "SELECT username, is_verified FROM users WHERE username=?",
            ("student1",),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(user)
        self.assertEqual(user[1], 1)


if __name__ == "__main__":
    unittest.main()
