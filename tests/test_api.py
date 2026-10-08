from app.main import health
from app.schemas import AuditRequest
from app.schemas import AuditRequest
def test_health():
    assert health()['status']=='ok'
def test_submission_request_schema():
    request=AuditRequest(url='https://youtu.be/dQw4w9WgXcQ')
    assert request.url.endswith('dQw4w9WgXcQ')
