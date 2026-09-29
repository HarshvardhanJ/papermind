"""Single-admin password authentication for a self-hosted PaperMind instance."""

import hmac
import os
from typing import Optional

import chainlit as cl


def auth_callback(username: str, password: str) -> Optional[cl.User]:
    """Authenticate against credentials supplied through the host environment."""
    expected_username = os.environ.get("PAPERMIND_ADMIN_USERNAME", "")
    expected_password = os.environ.get("PAPERMIND_ADMIN_PASSWORD", "")

    # Fail closed: an unset credential must never create a default account.
    if not expected_username or not expected_password:
        return None

    username_ok = hmac.compare_digest(username, expected_username)
    password_ok = hmac.compare_digest(password, expected_password)
    if username_ok and password_ok:
        return cl.User(identifier=expected_username, metadata={"role": "admin"})
    return None
