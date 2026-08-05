import secrets

def generate_session_token() -> str:
    """Generate a cryptographically secure, random URL-safe string."""
    return secrets.token_urlsafe(32)
