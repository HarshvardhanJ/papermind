"""
Authentication for Chainlit UI.
"""

import chainlit as cl
from typing import Optional


def auth_callback(username: str, password: str) -> Optional[cl.User]:
    """Simple authentication callback.
    
    Customize this for production use (e.g., integrate with OAuth, LDAP, etc.)
    """
    # Simple default auth - in production, use proper authentication
    if username == "admin" and password == "admin":
        return cl.User(identifier="admin", metadata={"role": "admin"})
    return None


def require_auth():
    """Decorator to require authentication for certain functions."""
    pass