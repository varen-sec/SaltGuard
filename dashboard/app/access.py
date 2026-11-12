"""Local demo PIN gate for specialist/configuration spaces (not production IAM)."""
from __future__ import annotations
import hmac
import os
import secrets
import threading
import time

PIN = os.getenv('SALTGUARD_ADVANCED_PIN', '1111')
if len(PIN) != 4 or not PIN.isascii() or not PIN.isdigit():
    raise RuntimeError('SALTGUARD_ADVANCED_PIN phải gồm đúng bốn chữ số')
SESSION_SECONDS = 4 * 3600
sessions: dict[str,float] = {}
failed: dict[str,tuple[int,float]] = {}
lock = threading.RLock()

def authenticated(request):
    token=request.cookies.get('sg_advanced','')
    if not token: return False
    with lock:
        expiry=sessions.get(token,0)
        if expiry <= time.time():
            sessions.pop(token,None)
            return False
        return True

def verify(pin:str, ip:str):
    now=time.time()
    with lock:
        tries,until=failed.get(ip,(0,0))
        if until > now:
            return None, int(until-now)+1
        if not hmac.compare_digest(str(pin),PIN):
            tries+=1
            failed[ip]=(tries, now+60 if tries>=5 else 0)
            return None, 60 if tries>=5 else 0
        failed.pop(ip,None)
        token=secrets.token_urlsafe(32)
        sessions[token]=now+SESSION_SECONDS
        return token,0

def revoke(request):
    token=request.cookies.get('sg_advanced')
    with lock:
        if token:sessions.pop(token,None)
