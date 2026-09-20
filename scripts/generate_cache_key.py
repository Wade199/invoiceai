"""Print a fresh key for CACHE_ENCRYPTION_KEY (put it in .env, never in Git)."""

from cryptography.fernet import Fernet

if __name__ == "__main__":
    print(Fernet.generate_key().decode())
