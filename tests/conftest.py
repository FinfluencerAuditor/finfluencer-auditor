import os
os.environ["AUDITOR_DB_PATH"]="/tmp/finfluencer-auditor-test.sqlite3"
from app import db
def pytest_sessionstart(session):
    if os.path.exists(os.environ["AUDITOR_DB_PATH"]): os.remove(os.environ["AUDITOR_DB_PATH"])
    db.init_db()
