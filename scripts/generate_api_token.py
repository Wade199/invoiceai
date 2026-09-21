"""Print a fresh random API_TOKEN (put it in .env, never in Git)."""

import secrets

if __name__ == "__main__":
    print(secrets.token_urlsafe(32))
