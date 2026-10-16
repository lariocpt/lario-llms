"""Shared KB access boundary for rag_api; raw physical/write routes require a host secret."""
import hmac
import os

PUBLIC_COLLECTIONS=frozenset({'kb-buddha','kb-crust','kb-extreme-pro','kb-flawless-react',
    'kb-lario-local-linux','kb-life-recovery','kb-muscledynamix','kb-react-corpus',
    'kb-life-vault','kb-muscledynamix-advisor'})


def trusted(authorization):
    expected=os.environ.get('KB_BACKEND_TOKEN','')
    return bool(expected) and hmac.compare_digest(
        (authorization or '').encode('utf-8'), ('Bearer '+expected).encode('utf-8'))


def authorize(path,body,authorization):
    if path in ('/health','/docs','/openapi.json'):return True
    if trusted(authorization):return True
    if path not in ('/retrieve','/query'):return False
    return (isinstance(body,dict) and isinstance(body.get('collection'),str)
            and body['collection'] in PUBLIC_COLLECTIONS)
