import os

# Use in-memory sqlite for tests, before app modules import settings
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["JWT_SECRET"] = "test-secret-at-least-32-bytes-long-for-hs256"
os.environ["ENABLE_SCHEDULER"] = "false"
