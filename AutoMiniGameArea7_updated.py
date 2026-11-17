"""
Auto Minigame v6  (ไร้แถบหัวหน้าต่าง + ปุ่มปิดอยู่ในตั้งค่า + เปลี่ยนธีมได้หลายแบบ)
  1) เชื่อมเหล็ก       : ลากตามเส้นดำ (เร็ว + ลื่น)
  2) ขันน็อตหน้าแปลน  : คลิกน็อตที่มีวงแหวนสีเหลือง
  3) กดรัว             : กดปุ่ม (ค่าเริ่มต้น E) รัว ๆ

ติดตั้ง:  python -m pip install mss opencv-python numpy keyboard pywebview
          (pywebview ใช้ทำหน้าต่างไร้กรอบ ถ้าไม่ติดตั้งจะเปิดด้วย Edge/Chrome แทน ซึ่งจะมีแถบหัวหน้าต่างของเบราว์เซอร์)
รัน:      เปิด PowerShell แบบ Run as Administrator แล้ว  python auto_minigame_v6.py
ทดสอบกับรูป (ไม่ขยับเมาส์):  python auto_minigame_v6.py --test image.png
"""

# =====================================================================
#  >>> ระบบกรอกคีย์ (เพิ่มใหม่) <<<
#  ระบบคีย์แสดงใน UI หลักและเริ่ม worker หลังยืนยันสิทธิ์แล้ว
# =====================================================================
SUPABASE_URL = "https://cgsuxxyezqhxayllhzfs.supabase.co"
SUPABASE_KEY = "sb_publishable_YvFpfdUYUF1b7L2VbFyZ5Q_RKLN-Mr3"   # Publishable key: ใส่ในสคริปต์ได้ (ผู้ใช้เรียกได้แค่ redeem_key / check_key ใน supabase_license.sql)
DISCORD_WEBHOOK_URL = ""  # ตั้งค่าใหม่หลังสร้าง webhook ใหม่ หากต้องการแจ้งเตือน
DISCORD_SERVER_ID = "1572061109714948166"
DISCORD_WIDGET_API = f"https://discord.com/api/guilds/{DISCORD_SERVER_ID}/widget.json"
DISCORD_INVITE_URL = "https://discord.gg/mr8MmUURw9"
LICENSE_APP_SECRET = "กรอกคีย์เพื่อเริ่มใช้งาน"                  # ใช้เข้ารหัสไฟล์จำคีย์ในเครื่อง
LICENSE_TITLE = "Auto Minigame"        # ชื่อที่โชว์บนหน้าต่างกรอกคีย์
BADGE_CORNER = "topright"              # มุมป้ายเวลาคงเหลือ: topright / topleft / bottomright / bottomleft
REVOKE_IF_REMOVED = True               # True = ถ้าคีย์ถูกยกเลิก/ลบออกจาก Supabase คีย์นั้นจะใช้ไม่ได้ทันที (ตอนมีเน็ต)
ALLOW_OFFLINE = True                   # True = เปิดซ้ำตอนเน็ตหลุดได้ (ยังเช็คเวลาย้อนหลังจากไฟล์ในเครื่อง)
CLOCK_TOLERANCE = 300                  # ยอมให้เวลาเครื่องคลาดเคลื่อนจากเวลาจริงได้กี่วินาที (5 นาที)
RECHECK_INTERVAL = 60                  # ระหว่างใช้งาน เช็คคีย์กับ Supabase ซ้ำทุกกี่วินาที (คีย์ถูกยกเลิก/ถูกรีเซ็ต/ไปผูกเครื่องอื่น = ปิดโปรแกรม)
OFFLINE_GRACE = 600                    # ถ้ายืนยันกับเซิร์ฟเวอร์ไม่ได้ติดต่อกันเกินกี่วินาที -> ไม่ให้ใช้ต่อ (กันตัดเน็ตเพื่อเลี่ยงการยกเลิกคีย์)

import os
import sys
import re
import json
import time
import uuid
import hmac
import base64
import socket
import math
import hashlib
import platform
import threading
import subprocess
import urllib.error
import urllib.request
import datetime as _dt
from email.utils import parsedate_to_datetime

_LIC = {"end_mono": 0.0, "expiry": 0.0, "trusted0": 0.0, "mono0": 0.0, "badge": None}
_LICENSE_UI = {"state": "checking", "error": "", "code": "", "offline": False}
_LICENSE_LOCK = threading.RLock()
_LICENSE_START_LOCK = threading.Lock()
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AutoMinigame/1.0"
_DUR_RE = re.compile(r"^(\d+)(min|hr|d)$", re.IGNORECASE)
_UNIT_SEC = {"min": 60, "hr": 3600, "d": 86400}
_NOTIFY_CODES = ("invalid", "expired", "hwid", "clock", "revoked")


class LicenseError(Exception):
    """ข้อผิดพลาดของระบบคีย์ (msg เป็นข้อความภาษาไทยที่แสดงให้ผู้ใช้เห็น)"""
    def __init__(self, msg, code="error"):
        super().__init__(msg)
        self.msg = msg
        self.code = code


# ---------------------------------------------------------------------
#  คีย์ / HWID / ไฟล์จำสถานะ (เข้ารหัส + ซ่อนในโฟลเดอร์ผู้ใช้)
# ---------------------------------------------------------------------
def parse_key(text):
    """แยกคีย์ 'PREFIX-RANDOM_24hr' -> (คีย์มาตรฐาน, จำนวนวินาที) หรือ None ถ้ารูปแบบผิด"""
    text = (text or "").strip()
    if "_" not in text:
        return None
    left, dur = text.rsplit("_", 1)
    m = _DUR_RE.match(dur)
    if not m or int(m.group(1)) <= 0:
        return None
    if not re.match(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)+$", left):
        return None
    n, unit = int(m.group(1)), m.group(2).lower()
    return left.upper() + "_" + f"{n}{unit}", n * _UNIT_SEC[unit]


def _mask_key(norm):
    """ปิดบังคีย์บางส่วนก่อนส่งเข้า Discord: AREA7KEY-K3****Q_24hr"""
    p = parse_key(norm)
    if not p:
        return (norm or "")[:3] + "***"
    left, dur = p[0].rsplit("_", 1)
    pre, _, rnd = left.rpartition("-")
    rnd = rnd[:2] + "*" * (len(rnd) - 3) + rnd[-1] if len(rnd) > 3 else "*" * len(rnd)
    return f"{pre}-{rnd}_{dur}"


def key_ref(norm):
    """รหัสอ้างอิงของคีย์ (แฮช 12 ตัว) — ส่งเข้า Discord แทนคีย์เต็ม; generate_keys.py ใช้สูตรเดียวกันจับคู่ประวัติ"""
    return hashlib.sha256(("area7|" + (norm or "")).encode("utf-8")).hexdigest()[:12]


def _dur_text(secs):
    if secs % 86400 == 0:
        return f"{secs // 86400} วัน"
    if secs % 3600 == 0:
        return f"{secs // 3600} ชั่วโมง"
    return f"{secs // 60} นาที"


def _hwid():
    raw = f"{uuid.getnode():012x}|{platform.node()}|{platform.system()}|{platform.machine()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _hwid_short():
    return _hwid()[:12].upper()


def _lic_dir():
    base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base or os.path.expanduser("~"), ".sysmeta7")


def _hide(path, on=True):
    """ซ่อน/แสดงไฟล์บน Windows (attribute Hidden)"""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(path, 0x02 if on else 0x80)
        except Exception:
            pass


def _lic_path():
    return os.path.join(_lic_dir(), ".cache.dat")


def _secret():
    return hashlib.sha256(LICENSE_APP_SECRET.encode("utf-8")).digest()


def _keystream(nonce, n):
    out, i = b"", 0
    while len(out) < n:
        out += hashlib.sha256(_secret() + nonce + i.to_bytes(4, "big")).digest()
        i += 1
    return out[:n]


def _encrypt(obj):
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    nonce = os.urandom(16)
    ct = bytes(a ^ b for a, b in zip(raw, _keystream(nonce, len(raw))))
    mac = hmac.new(_secret(), nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(nonce + mac + ct)


def _decrypt(blob):
    d = base64.b64decode(blob)
    nonce, mac, ct = d[:16], d[16:48], d[48:]
    if not hmac.compare_digest(mac, hmac.new(_secret(), nonce + ct, hashlib.sha256).digest()):
        raise ValueError("bad mac")
    return json.loads(bytes(a ^ b for a, b in zip(ct, _keystream(nonce, len(ct)))).decode("utf-8"))


def _state_load():
    """อ่านสถานะ: {'keys': {คีย์: {'start','hwid'}}, 'cur': คีย์ปัจจุบัน, 'last_seen': เวลาล่าสุด}"""
    try:
        with open(_lic_path(), "rb") as f:
            st = _decrypt(f.read())
        if isinstance(st, dict) and isinstance(st.get("keys"), dict):
            return st
    except Exception:
        pass
    return {"keys": {}, "cur": None, "last_seen": 0}


def _state_save(st):
    try:
        os.makedirs(_lic_dir(), exist_ok=True)
        _hide(_lic_dir())
        path = _lic_path()
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(_encrypt(st))
        _hide(path, False)
        os.replace(tmp, path)
        _hide(path)
    except Exception:
        pass


# ---------------------------------------------------------------------
#  เครือข่าย: ดึงรายการคีย์ + เวลาจริงจากอินเทอร์เน็ต
# ---------------------------------------------------------------------
def _http(url, timeout=8, method="GET", data=None, headers=None):
    h = {"User-Agent": _UA, "Cache-Control": "no-cache"}
    h.update(headers or {})
    return urllib.request.urlopen(urllib.request.Request(url, data=data, method=method, headers=h), timeout=timeout)


def _resp_time(headers):
    """เวลาจริงจาก HTTP Date (+Age ถ้าเป็นผลจากแคช) -> epoch วินาที"""
    t = parsedate_to_datetime(headers.get("Date")).timestamp()
    age = headers.get("Age")
    return t + (int(age) if age and age.strip().isdigit() else 0)


def _fallback_time():
    for url in ("https://www.google.com", "https://www.cloudflare.com"):
        try:
            with _http(url, timeout=5, method="HEAD") as r:
                return _resp_time(r.headers)
        except Exception:
            continue
    return None


def _sb_rpc(fn, payload):
    """เรียกฟังก์ชันบน Supabase -> (ผลลัพธ์ dict, เวลาจริงของเซิร์ฟเวอร์ หรือ None)
    เน็ตมีปัญหา -> LicenseError(code='net') / ตั้งค่าผิด -> LicenseError(code='config')"""
    if not str(SUPABASE_URL).startswith("http") or not SUPABASE_KEY:
        raise LicenseError("ยังไม่ได้ตั้งค่า SUPABASE_URL / SUPABASE_KEY ในสคริปต์", "config")
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    if SUPABASE_KEY.startswith("eyJ"):                  # คีย์แบบ JWT เดิมต้องส่ง Authorization ด้วย (sb_... ไม่ต้อง)
        headers["Authorization"] = "Bearer " + SUPABASE_KEY
    try:
        with _http(SUPABASE_URL.rstrip("/") + "/rest/v1/rpc/" + fn, timeout=8, method="POST",
                   data=json.dumps(payload).encode("utf-8"), headers=headers) as r:
            res = json.loads(r.read(200_000).decode("utf-8", "replace"))
            try:
                hdr_time = _resp_time(r.headers)
            except Exception:
                hdr_time = None
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise LicenseError("ไม่พบฟังก์ชันตรวจคีย์บน Supabase (ยังไม่ได้รัน supabase_license.sql)", "config")
        if e.code in (400, 401, 403):
            raise LicenseError(f"Supabase ปฏิเสธคำขอ (HTTP {e.code}) กรุณาตรวจสอบ SUPABASE_KEY และการติดตั้งฟังก์ชัน", "config")
        raise LicenseError(f"เซิร์ฟเวอร์ตอบกลับผิดปกติ (HTTP {e.code}) กรุณาลองใหม่ภายหลัง", "net")
    except (urllib.error.URLError, OSError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise LicenseError("เซิร์ฟเวอร์ตอบช้าเกินไป (หมดเวลาเชื่อมต่อ) กรุณาลองใหม่อีกครั้ง", "net")
        raise LicenseError("เชื่อมต่ออินเทอร์เน็ตไม่ได้ กรุณาตรวจสอบเน็ตแล้วลองใหม่", "net")
    except ValueError:
        raise LicenseError("เซิร์ฟเวอร์ตอบกลับข้อมูลไม่ถูกต้อง กรุณาลองใหม่ภายหลัง", "net")
    if not isinstance(res, dict):
        raise LicenseError("เซิร์ฟเวอร์ตอบกลับข้อมูลไม่ถูกต้อง กรุณาลองใหม่ภายหลัง", "net")
    st_ = res.get("server_time")                        # เวลาจริงจากเซิร์ฟเวอร์ (แม่นกว่า HTTP Date)
    net = float(st_) if isinstance(st_, (int, float)) else (hdr_time if hdr_time is not None else _fallback_time())
    return res, net


def sb_redeem(norm):
    """กรอกคีย์: เปิดใช้ครั้งแรก / เปิดซ้ำเครื่องเดิม / ผูกเครื่องใหม่หลังแอดมินรีเซ็ต HWID (เซิร์ฟเวอร์เป็นคนบันทึกเวลาเริ่ม)"""
    return _sb_rpc("redeem_key", {"p_key": norm, "p_hwid": _hwid(), "p_machine": (platform.node() or "")[:80],
                                  "p_client_time": time.time(), "p_tolerance": CLOCK_TOLERANCE})


def sb_check(norm):
    """ตรวจคีย์ที่ใช้อยู่ (อ่านอย่างเดียว ไม่แก้ข้อมูล)"""
    return _sb_rpc("check_key", {"p_key": norm, "p_hwid": _hwid()})


# ข้อความตามโค้ดผลลัพธ์จากเซิร์ฟเวอร์
_SB_MSG = {
    "invalid": "ไม่พบคีย์นี้ในระบบ กรุณาตรวจสอบตัวอักษรอีกครั้ง",
    "revoked": "คีย์นี้ถูกยกเลิกแล้ว กรุณาใช้คีย์ใหม่",
    "hwid": "คีย์นี้ถูกใช้ไปแล้วหรือผูกกับอุปกรณ์อื่น",
    "unbound": "คีย์นี้ถูกรีเซ็ตเครื่องแล้ว กรุณากรอกคีย์อีกครั้งเพื่อผูกกับเครื่องนี้",
    "unused": "ไม่พบการเปิดใช้คีย์นี้ในระบบ กรุณากรอกคีย์อีกครั้ง",
    "expired": "คีย์นี้หมดอายุแล้ว",
    "clock": "เวลาในเครื่องไม่ตรงกับเวลาจริง (คลาดเกิน 5 นาที) กรุณาตั้งเวลาเครื่องให้ถูกต้องแล้วเปิดใหม่",
}


# ---------------------------------------------------------------------
#  แจ้งเตือน Discord Webhook (ส่งใน thread แยก ล้มเหลวแล้วเงียบ ไม่ทำให้โปรแกรมพัง)
# ---------------------------------------------------------------------
_hook_count = [0]
_hook_threads = []
_HOOK_KINDS = {
    "activated": ("✅ เปิดใช้คีย์ครั้งแรก", 0x34D399),
    "invalid": ("❌ ใส่คีย์ไม่ถูกต้อง", 0xF87171),
    "expired": ("⏰ คีย์หมดอายุ", 0xFB923C),
    "hwid": ("🚫 คีย์ผูกกับเครื่องอื่น", 0xF87171),
    "clock": ("⚠️ เวลาเครื่องผิดปกติ", 0xF87171),
    "revoked": ("🛑 คีย์ถูกยกเลิก", 0xF87171),
}


def _hook_allowed(force):
    """จำกัดความถี่กันสแปม: เว้น 60 วินาที และไม่เกิน 3 ครั้งต่อการเปิดโปรแกรม (ยกเว้น force)"""
    if force:
        return True
    if _hook_count[0] >= 3:
        return False
    path = os.path.join(_lic_dir(), ".rl")
    now = time.time()
    try:
        with open(path, "r") as f:
            if now - float(f.read().strip() or 0) < 60:
                return False
    except Exception:
        pass
    try:
        os.makedirs(_lic_dir(), exist_ok=True)
        with open(path, "w") as f:
            f.write(str(now))
    except Exception:
        pass
    _hook_count[0] += 1
    return True


def _public_ip():
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip"):
        try:
            with _http(url, timeout=4) as r:
                ip = r.read(64).decode("ascii", "ignore").strip()
            if re.match(r"^[0-9a-fA-F:.]{3,45}$", ip):
                return ip
        except Exception:
            continue
    return "ไม่ทราบ"


def discord_notify(kind, key_norm=None, extra=None, force=False):
    """ส่ง embed เข้า Discord (ไม่บล็อก UI) คืนค่า thread หรือ None"""
    url = DISCORD_WEBHOOK_URL or ""
    if not url.startswith("http") or "XXXXXXXX" in url or not _hook_allowed(force):
        return None
    title, color = _HOOK_KINDS.get(kind, ("ℹ️ แจ้งเตือน", 0x8A92A8))

    def job():
        try:
            now = time.time()
            fields = [
                {"name": "คีย์", "value": f"`{_mask_key(key_norm)}`" if key_norm else "-", "inline": True},
                {"name": "รหัสอ้างอิง", "value": f"`{key_ref(key_norm)}`" if key_norm else "-", "inline": True},
                {"name": "HWID (ย่อ)", "value": f"`{_hwid_short()}`", "inline": True},
                {"name": "ชื่อเครื่อง", "value": f"`{platform.node() or '-'}`", "inline": True},
                {"name": "IP", "value": f"`{_public_ip()}`", "inline": True},
                {"name": "เวลา", "value": f"<t:{int(now)}:F>", "inline": True},
            ]
            for k, v in (extra or {}).items():
                fields.append({"name": str(k), "value": str(v), "inline": True})
            payload = {"username": LICENSE_TITLE + " License",
                       "embeds": [{"title": title, "color": color, "fields": fields,
                                   "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                                   "footer": {"text": LICENSE_TITLE}}]}
            _http(url, timeout=8, method="POST", data=json.dumps(payload).encode("utf-8"),
                  headers={"Content-Type": "application/json"}).close()
        except Exception:
            pass

    t = threading.Thread(target=job, daemon=True)
    t.start()
    _hook_threads.append(t)
    return t


def _fail(msg, code, key=None):
    """สร้าง LicenseError พร้อมแจ้ง Discord (ถ้าเป็นเหตุที่ควรแจ้ง)"""
    if code in _NOTIFY_CODES:
        discord_notify(code, key, extra={"สาเหตุ": msg[:200]})
    return LicenseError(msg, code)


# ---------------------------------------------------------------------
#  ตรวจเวลา / เปิดใช้คีย์ / ตรวจคีย์ที่จำไว้
# ---------------------------------------------------------------------
def _verify_time(st, net, key=None):
    """คืน 'เวลาที่เชื่อถือได้' (เวลาจริงจากเน็ต ถ้าไม่มีใช้เวลาเครื่อง) และตรวจว่าเวลาเครื่องไม่ผิดปกติ"""
    local = time.time()
    if net is not None:
        if abs(local - net) > CLOCK_TOLERANCE:
            raise _fail("เวลาในเครื่องไม่ตรงกับเวลาจริง (คลาดเกิน 5 นาที) กรุณาตั้งเวลาเครื่องให้ถูกต้องแล้วเปิดใหม่", "clock", key)
        now = net
    else:
        now = local
    if now < float(st.get("last_seen") or 0) - CLOCK_TOLERANCE:
        raise _fail("ตรวจพบเวลาเครื่องย้อนหลังกว่าครั้งล่าสุดที่เปิดโปรแกรม กรุณาตั้งเวลาให้ถูกต้อง", "clock", key)
    return now


def _grant(norm, expiry, now, offline=False):
    """บันทึกเวลาหมดอายุไว้ใช้นับถอยหลัง (ใช้ monotonic กันการแก้นาฬิการะหว่างใช้งาน)"""
    _LIC.update(key=norm, expiry=expiry, end_mono=time.monotonic() + (expiry - now),
                trusted0=now, mono0=time.monotonic())
    return {"key": norm, "expiry": expiry, "remaining": expiry - now, "offline": offline}


def activate(key_text):
    """เปิดใช้คีย์ที่ผู้ใช้กรอก (เรียกใน thread แยก)"""
    p = parse_key(key_text)
    if not p:
        raise LicenseError("รูปแบบคีย์ไม่ถูกต้อง ตัวอย่าง: AREA7KEY-K3F9Q2_24hr", "format")
    norm, secs = p
    res, net = sb_redeem(norm)
    if not res.get("ok"):
        code = res.get("code")
        raise _fail(_SB_MSG.get(code, "ตรวจสอบคีย์ไม่สำเร็จ กรุณาลองใหม่"), code if code in _SB_MSG else "error", norm)
    st = _state_load()
    now = _verify_time(st, net, norm)
    start = float(res["used_at"])                      # เวลาเริ่มใช้ตามเซิร์ฟเวอร์
    expiry = start + secs
    if now >= expiry:
        raise _fail("คีย์นี้หมดอายุแล้ว", "expired", norm)
    st["keys"][norm] = {"start": start, "hwid": _hwid()}
    st["cur"] = norm
    st["last_seen"] = max(float(st.get("last_seen") or 0), now)
    st["last_verified"] = now
    _state_save(st)
    if res.get("first"):    # ส่ง log ทุกครั้งที่เปิดใช้ครั้งแรก เพื่อให้คุณตรวจว่าซ้ำหรือไม่
        discord_notify("activated", norm, force=True, extra={
            "ระยะเวลา": _dur_text(secs),
            "หมดอายุ": f"<t:{int(expiry)}:F>"})
    return _grant(norm, expiry, now)


def check_saved():
    """ตรวจคีย์ที่จำไว้ในเครื่อง คืน info ถ้าผ่าน / None ถ้าไม่มีคีย์ที่จำไว้ / LicenseError ถ้าใช้ไม่ได้"""
    st = _state_load()
    norm = st.get("cur")
    ent = st["keys"].get(norm) if norm else None
    p = parse_key(norm) if norm else None
    if not ent or not p:
        return None
    if ent.get("hwid") != _hwid():
        raise _fail("คีย์นี้ถูกใช้ไปแล้วหรือผูกกับอุปกรณ์อื่น", "hwid", norm)
    offline, res = False, None
    try:
        res, net = sb_check(norm)
    except LicenseError as e:
        if e.code != "net" or not ALLOW_OFFLINE:
            raise
        if time.time() - float(st.get("last_verified") or 0) > OFFLINE_GRACE:
            raise LicenseError("ต้องเชื่อมต่ออินเทอร์เน็ตเพื่อยืนยันสถานะคีย์ก่อนใช้งาน (ออฟไลน์ได้ไม่เกิน "
                               f"{max(1, OFFLINE_GRACE // 60)} นาทีหลังตรวจสอบล่าสุด)", "net")
        net, offline = None, True
    now = _verify_time(st, net, norm)
    if res is not None:
        code = res.get("code")
        if code in ("revoked", "invalid"):
            if REVOKE_IF_REMOVED:
                st["cur"] = None
                _state_save(st)
                raise _fail(_SB_MSG["revoked"], "revoked", norm)
        elif code in ("hwid", "unbound", "unused"):
            st["cur"] = None
            _state_save(st)
            raise _fail(_SB_MSG[code], code, norm)
        elif code == "expired":
            st["cur"] = None
            _state_save(st)
            raise _fail("คีย์ที่บันทึกไว้หมดอายุแล้ว กรุณาใส่คีย์ใหม่", "expired", norm)
        elif res.get("ok") and res.get("used_at"):
            ent["start"] = float(res["used_at"])        # เวลาเริ่มใช้ตามเซิร์ฟเวอร์เป็นหลัก
            st["keys"][norm] = ent
        else:
            raise LicenseError(_SB_MSG.get(code, "ตรวจสอบคีย์ไม่สำเร็จ กรุณาลองใหม่"), "error")
    expiry = ent["start"] + p[1]
    if now >= expiry:
        st["cur"] = None
        _state_save(st)
        raise _fail("คีย์ที่บันทึกไว้หมดอายุแล้ว กรุณาใส่คีย์ใหม่", "expired", norm)
    st["last_seen"] = max(float(st.get("last_seen") or 0), now)
    if not offline:
        st["last_verified"] = now
    _state_save(st)
    return _grant(norm, expiry, now, offline)


def _trusted_now():
    return _LIC["trusted0"] + (time.monotonic() - _LIC["mono0"])


def _split(sec):
    sec = max(0, int(sec))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    return d, h, m, s


# ---------------------------------------------------------------------
#  หน้าต่างกรอกคีย์ (tkinter — โทนมืด จัดกึ่งกลางจอ มุมโค้ง)
# ---------------------------------------------------------------------
def _rrect(c, x1, y1, x2, y2, r, **kw):
    """วาดสี่เหลี่ยมมุมโค้งบน Canvas"""
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def _ui_setup(root):
    """คืน (สเกลจอ, ชื่อฟอนต์ที่ใช้ได้ทั้งไทย/อังกฤษ)"""
    import tkinter.font as tkfont
    scale = max(1.0, root.winfo_fpixels("1i") / 96.0)
    fams = set(tkfont.families(root))
    fam = next((f for f in ("Leelawadee UI", "Segoe UI", "Tahoma", "Arial") if f in fams), "TkDefaultFont")
    return scale, fam


def _mix(a, b, t):
    """ผสมสี hex สองสี (t=0 -> a, t=1 -> b)"""
    pa = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    pb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * max(0.0, min(1.0, t))) for x, y in zip(pa, pb))

# ชุดสีของแต่ละธีม (ตรงกับธีมในหน้าตั้งค่า): (พื้นหลัง, a1, a2, a3, soft)
_THEME_PAL = {
    "violet":  ("#06070b", "#7c5cff", "#22d3ee", "#5b8cff", "#c9bfff"),
    "ocean":   ("#050b14", "#0ea5e9", "#2dd4bf", "#3b82f6", "#bae6fd"),
    "emerald": ("#040d0a", "#10b981", "#a3e635", "#22c55e", "#bbf7d0"),
    "sunset":  ("#0d0706", "#f97316", "#f43f5e", "#fb923c", "#fed7aa"),
    "rose":    ("#0d060a", "#ec4899", "#a855f7", "#f472b6", "#fbcfe8"),
    "crimson": ("#0b0505", "#ef4444", "#f59e0b", "#dc2626", "#fecaca"),
    "gold":    ("#0b0904", "#eab308", "#f97316", "#facc15", "#fef08a"),
    "cyber":   ("#08040f", "#ff2bd6", "#00f0ff", "#7c3aed", "#f5d0fe"),
    "mint":    ("#050b0d", "#14b8a6", "#67e8f9", "#06b6d4", "#99f6e4"),
    "aurora":  ("#050a10", "#8b5cf6", "#34d399", "#38bdf8", "#ddd6fe"),
    "slate":   ("#08090b", "#94a3b8", "#e2e8f0", "#64748b", "#e2e8f0"),
    "amoled":  ("#000000", "#6366f1", "#22d3ee", "#818cf8", "#c7d2fe"),
}


def _saved_theme():
    """อ่านธีมที่ผู้ใช้เลือกไว้จาก settings.json (ไม่มี/อ่านไม่ได้ = violet)"""
    try:
        with open(BOOT_FILE, "r", encoding="utf-8") as f:
            d = json.load(f).get("data_dir", "")
        with open(os.path.join(d, SETTINGS_NAME), "r", encoding="utf-8") as f:
            t = json.load(f).get("theme", "violet")
        return t if t in _THEME_PAL else "violet"
    except Exception:
        return "violet"


def _lum(h):
    return 0.299 * int(h[1:3], 16) + 0.587 * int(h[3:5], 16) + 0.114 * int(h[5:7], 16)
class _KeyWindow:
    TXT, MUT, DIM = "#eef0f7", "#8a92a8", "#4b5268"
    OK, BAD, BUSY = "#34d399", "#f87171", "#9fb4ff"
    TRANSP = "#010203"
    PLACEHOLDER = "AREA7KEY-XXXXXXXX_24hr"
    _btn_locked = False

    def _theme(self):
        bg, a1, a2, a3, soft = _THEME_PAL[_saved_theme()]
        self.BG = _mix(bg, "#ffffff", 0.045)
        self.EDGE = _mix(self.BG, soft, 0.20)
        self.FIELD = _mix(self.BG, "#ffffff", 0.05)
        self.ACC, self.ACC2, self.SOFT = a1, a2, soft
        self.G1, self.G2 = a1, a3
        self.G1H, self.G2H = _mix(a1, "#ffffff", 0.2), _mix(a3, "#ffffff", 0.2)
        self.G1D = self.G2D = _mix(self.BG, "#ffffff", 0.12)
        self.PBG, self.PBGH = _mix(self.FIELD, soft, 0.12), _mix(self.FIELD, soft, 0.26)
        self.MUT = _mix("#8a92a8", soft, 0.25)
        self.BTNTX = "#0b0d15" if _lum(_mix(a1, a3, 0.5)) > 165 else "#ffffff"

    def __init__(self):
        import tkinter as tk
        import queue
        self.tk, self.q = tk, queue.Queue()
        self.ok, self.busy, self.closed, self.dots, self.base, self.gen = False, False, False, 0, "", 0
        self.info, self.ph_on, self.total = None, True, 1
        self._sp, self._shining, self.stars = 0, False, []
        self._theme()
        r = self.root = tk.Tk()
        r.title(LICENSE_TITLE)
        r.overrideredirect(True)
        try:
            r.attributes("-topmost", True)
            r.attributes("-alpha", 0.0)
        except Exception:
            pass
        S, self.fam = _ui_setup(r)
        import tkinter.font as tkfont
        fams = set(tkfont.families(r))
        self.mono = next((f for f in ("Cascadia Mono", "Consolas", "Courier New") if f in fams), self.fam)
        self.S = S
        u = self.u
        self.W, self.H = u(460), u(540)
        r.geometry(f"{self.W}x{self.H}+{(r.winfo_screenwidth() - self.W) // 2}+{max(0, (r.winfo_screenheight() - self.H) // 2 - u(20))}")
        r.configure(bg=self.TRANSP)
        try:
            r.attributes("-transparentcolor", self.TRANSP)
        except Exception:
            pass
        c = self.c = tk.Canvas(r, width=self.W, height=self.H, bg=self.TRANSP, highlightthickness=0, bd=0)
        c.pack()
        self._build()
        self._bind()
        self._show_form(False)
        self._show_panel(False)
        self.set_status("กำลังตรวจสอบสิทธิ์การใช้งาน", "busy", animate=True)
        threading.Thread(target=self._worker, args=("saved", None), daemon=True).start()
        r.after(80, self._poll)
        r.after(60, lambda: (r.lift(), r.focus_force()))
        r.after(300, self._shine)
        r.after(120, self._twinkle)
        self._fade(0)

    # ---- ตัวช่วย ----
    def u(self, v):
        return int(v * self.S)

    def font(self, px, bold=False, mono=False):
        fam = self.mono if mono else self.fam
        return (fam, -self.u(px), "bold") if bold else (fam, -self.u(px))

    def _fade(self, i):
        if self.closed:
            return
        try:
            self.root.attributes("-alpha", min(1.0, i / 8.0))
        except Exception:
            return
        if i < 8:
            self.root.after(16, lambda: self._fade(i + 1))

    def _shake(self, i=0):
        if self.closed:
            return
        seq = (12, -10, 8, -6, 4, -2, 0)
        if i == 0:
            self._sx, self._sy = self.root.winfo_x(), self.root.winfo_y()
        if i < len(seq):
            self.root.geometry(f"+{self._sx + self.u(seq[i])}+{self._sy}")
            self.root.after(28, lambda: self._shake(i + 1))
        else:
            self.root.geometry(f"+{self._sx}+{self._sy}")

    def _grad_pill(self, x1, y1, x2, y2, c1, c2, tags):
        c, ids = self.c, []
        r, w = (y2 - y1) // 2, x2 - x1
        for i in range(w + 1):
            d = min(i, w - i)
            dy = 0 if d >= r else r - int(math.sqrt(max(0, r * r - (r - d) ** 2)))
            ids.append(c.create_line(x1 + i, y1 + dy, x1 + i, y2 - dy + 1,
                                     fill=_mix(c1, c2, i / max(1, w)), tags=tags))
        return ids

    def _paint_btn(self, c1, c2, shine=None):
        """ทาสีปุ่มไล่เฉด (shine = ตำแหน่งแถบแสงวิ่งผ่านปุ่ม)"""
        self._bc = (c1, c2)
        n = len(self.btn_ids)
        for i, it in enumerate(self.btn_ids):
            col = _mix(c1, c2, i / max(1, n - 1))
            if shine is not None:
                k = 1 - abs(i - shine) / (n * 0.12)
                if k > 0:
                    col = _mix(col, "#ffffff", 0.32 * k)
            self.c.itemconfigure(it, fill=col)

    def _shine(self):
        """แถบแสงวิ่งผ่านปุ่มเปิดใช้งานเป็นระยะ"""
        if self.closed:
            return
        n = len(self.btn_ids)
        self._sp = (self._sp + max(3, n // 40)) % int(n * 2.2)
        if (not self.busy and not self._btn_locked
                and self.c.itemcget(self.btn_tx, "state") != "hidden"):
            act = self._sp < n * 1.2
            if act or self._shining:
                self._paint_btn(*self._bc, shine=self._sp if act else None)
            self._shining = act
        self.root.after(40, self._shine)

    def _twinkle(self):
        """ดาวเล็ก ๆ พื้นหลังระยิบ"""
        if self.closed:
            return
        t = time.time()
        for it, ph, sp in self.stars:
            a = 0.15 + 0.85 * (0.5 + 0.5 * math.sin(t * sp + ph))
            self.c.itemconfigure(it, fill=_mix(self.BG, self.SOFT, a * 0.8))
        self.root.after(120, self._twinkle)

    def _build(self):
        import random
        c, u, W, H = self.c, self.u, self.W, self.H
        # กรอบสองชั้น + เส้นแสงไล่สีด้านบน
        _rrect(c, u(2), u(2), W - u(2), H - u(2), u(28), fill=self.BG,
               outline=_mix(self.BG, self.ACC, 0.55), width=2)
        _rrect(c, u(9), u(9), W - u(9), H - u(9), u(22), fill="", outline=self.EDGE, width=1)
        n = 60
        for i in range(n):
            t = i / (n - 1)
            x1 = u(70) + (W - u(140)) * i // n
            x2 = u(70) + (W - u(140)) * (i + 1) // n + 1
            c.create_line(x1, u(2.5), x2, u(2.5), width=max(2, u(2)),
                          fill=_mix(self.BG, _mix(self.ACC, self.ACC2, t), math.sin(math.pi * t)))
        # ดาวระยิบพื้นหลัง
        rnd = random.Random(7)
        for _ in range(26):
            x, y = rnd.randint(u(22), W - u(22)), rnd.randint(u(24), H - u(70))
            if u(55) < x < W - u(55) and u(150) < y < u(450):
                continue
            rr = rnd.choice((1, 1, 1.5, 2))
            it = c.create_oval(x - rr, y - rr, x + rr, y + rr, outline="", fill=self.BG)
            self.stars.append((it, rnd.uniform(0, 6.28), rnd.uniform(0.8, 2.4)))
        # แสงเรืองด้านหลังโลโก้
        cx, cy = W // 2, u(96)
        for i in range(14, 0, -1):
            rr = u(36) + int(i * u(3.0))
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline="",
                          fill=_mix(self.BG, self.ACC, 0.22 * (1 - i / 14.0) ** 2))
        # ปุ่มปิด
        self.x_id = c.create_text(W - u(32), u(32), text="✕", fill=self.MUT, font=self.font(15), tags=("close",))
        # โลโก้สายฟ้า (วงแหวนซ้อน)
        rr = u(47)
        c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=_mix(self.BG, self.SOFT, 0.35), dash=(2, 6))
        rr = u(40)
        c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=self.ACC2, width=1)
        rr = u(34)
        c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, fill=self.ACC, outline="")
        s = u(1.5)
        bolt = [(13, 2), (4, 14), (10, 14), (9, 22), (18, 10), (12, 10)]
        c.create_polygon([v for x, y in bolt for v in (cx + (x - 12) * s, cy + (y - 12) * s)], fill="#ffffff", outline="")
        c.create_text(W // 2, u(154), text="P R E M I U M   A C C E S S", fill=self.SOFT, font=self.font(10, True))
        c.create_text(W // 2, u(174), text=LICENSE_TITLE, fill=self.TXT, font=self.font(25, True))
        # เส้นประดับ
        dy, d = u(196), u(5)
        c.create_line(u(110), dy, W // 2 - u(14), dy, fill=_mix(self.BG, self.SOFT, 0.45))
        c.create_line(W // 2 + u(14), dy, W - u(110), dy, fill=_mix(self.BG, self.SOFT, 0.45))
        c.create_polygon(W // 2, dy - d, W // 2 + d, dy, W // 2, dy + d, W // 2 - d, dy, fill=self.ACC2, outline="")
        c.create_text(W // 2, u(215), text="กรอกคีย์เพื่อเปิดใช้งานโปรแกรม", fill=self.MUT, font=self.font(13), tags=("formonly",))

        # ช่องกรอกคีย์ (มีแสงเรืองตอนโฟกัส)
        bx1, by1, bx2, by2 = u(40), u(238), W - u(40), u(294)
        self.glow = _rrect(c, bx1 - u(3), by1 - u(3), bx2 + u(3), by2 + u(3), u(23), fill="",
                           outline=self.BG, width=u(3), tags=("box",))
        self.box = _rrect(c, bx1, by1, bx2, by2, u(20), fill=self.FIELD, outline=self.EDGE, width=2, tags=("box",))
        kx, ky = u(66), (by1 + by2) // 2
        c.create_oval(kx - u(9), ky - u(5), kx + u(1), ky + u(5), outline=self.MUT, width=2, tags=("box",))
        c.create_line(kx + u(1), ky, kx + u(13), ky, fill=self.MUT, width=2, tags=("box",))
        c.create_line(kx + u(9), ky, kx + u(9), ky + u(5), fill=self.MUT, width=2, tags=("box",))
        c.create_line(kx + u(13), ky, kx + u(13), ky + u(5), fill=self.MUT, width=2, tags=("box",))
        px1, px2 = bx2 - u(78), bx2 - u(10)
        self.paste_bg = _rrect(c, px1, by1 + u(12), px2, by2 - u(12), u(16), fill=self.PBG, outline="", tags=("box", "paste"))
        self.paste_tx = c.create_text((px1 + px2) // 2, ky, text="วาง", fill=self.SOFT, font=self.font(13, True), tags=("box", "paste"))
        self.var = self.tk.StringVar(value=self.PLACEHOLDER)
        self.entry = self.tk.Entry(self.root, textvariable=self.var, bd=0, relief="flat", justify="left",
                                   bg=self.FIELD, fg=self.DIM, insertbackground=self.TXT,
                                   disabledbackground=self.FIELD, disabledforeground=self.MUT,
                                   font=self.font(15, mono=True), highlightthickness=0)
        ex1, ex2 = kx + u(24), px1 - u(8)
        self.entry_win = c.create_window((ex1 + ex2) // 2, ky, window=self.entry, width=ex2 - ex1, height=u(32))

        # ปุ่มเปิดใช้งาน (ไล่สีตามธีม + แสงวิ่ง)
        self.btn_ids = self._grad_pill(u(40), u(314), W - u(40), u(370), self.G1, self.G2, ("btn",))
        self._bc = (self.G1, self.G2)
        self.btn_tx = c.create_text(W // 2, u(342), text="เปิดใช้งาน", fill=self.BTNTX, font=self.font(17, True), tags=("btn",))

        # แผงเวลาคงเหลือ (โชว์หลังคีย์ผ่าน)
        c.create_oval(W // 2 - u(15), u(222) - u(15), W // 2 + u(15), u(222) + u(15), fill=_mix(self.BG, self.OK, 0.22), outline="", tags=("panel",))
        c.create_text(W // 2, u(222), text="✓", fill=self.OK, font=self.font(17, True), tags=("panel",))
        c.create_text(W // 2, u(258), text="เวลาคงเหลือ", fill=self.MUT, font=self.font(13), tags=("panel",))
        self.tiles = []
        tw, th, gap = u(84), u(76), u(10)
        x0 = (W - (4 * tw + 3 * gap)) // 2
        for i, lab in enumerate(("วัน", "ชั่วโมง", "นาที", "วินาที")):
            x = x0 + i * (tw + gap)
            _rrect(c, x, u(280), x + tw, u(280) + th, u(16), fill=self.FIELD, outline=self.EDGE, width=1, tags=("panel",))
            num = c.create_text(x + tw // 2, u(280) + u(30), text="00", fill=self.TXT, font=self.font(28, True), tags=("panel",))
            c.create_text(x + tw // 2, u(280) + u(61), text=lab, fill=self.MUT, font=self.font(12), tags=("panel",))
            self.tiles.append(num)
        self.bar_x1, self.bar_x2, self.bar_y = u(46), W - u(46), u(384)
        c.create_line(self.bar_x1, self.bar_y, self.bar_x2, self.bar_y, width=u(6), capstyle="round", fill=self.FIELD, tags=("panel",))
        self.bar = c.create_line(self.bar_x1, self.bar_y, self.bar_x2, self.bar_y, width=u(6), capstyle="round", fill=self.ACC2, tags=("panel",))
        self.exp_id = c.create_text(W // 2, u(410), text="", fill=self.MUT, font=self.font(13), tags=("panel",))

        # ข้อความสถานะ + ท้ายหน้าต่าง
        self.status = c.create_text(W // 2, u(392), text="", fill=self.MUT, font=self.font(14),
                                    width=W - u(70), justify="center", anchor="n")
        c.create_line(u(60), H - u(54), W - u(60), H - u(54), fill=self.EDGE)
        self.hw_id = c.create_text(W // 2, H - u(30), text=f"รหัสเครื่อง  {_hwid_short()}   ·   แตะเพื่อคัดลอก",
                                   fill=self.DIM, font=self.font(11), tags=("hw",))

    def _bind(self):
        c, r, e = self.c, self.root, self.entry
        c.tag_bind("close", "<Button-1>", lambda ev: self.close())
        c.tag_bind("close", "<Enter>", lambda ev: c.itemconfigure(self.x_id, fill=self.BAD))
        c.tag_bind("close", "<Leave>", lambda ev: c.itemconfigure(self.x_id, fill=self.MUT))
        c.tag_bind("btn", "<Button-1>", lambda ev: self.on_activate())
        c.tag_bind("btn", "<Enter>", lambda ev: self._btn_hover(True))
        c.tag_bind("btn", "<Leave>", lambda ev: self._btn_hover(False))
        c.tag_bind("paste", "<Button-1>", lambda ev: self._paste())
        c.tag_bind("paste", "<Enter>", lambda ev: c.itemconfigure(self.paste_bg, fill=self.PBGH))
        c.tag_bind("paste", "<Leave>", lambda ev: c.itemconfigure(self.paste_bg, fill=self.PBG))
        c.tag_bind("hw", "<Button-1>", lambda ev: self._copy_hw())
        for tag in ("close", "btn", "paste", "hw"):
            c.tag_bind(tag, "<Enter>", lambda ev: c.configure(cursor="hand2"), add="+")
            c.tag_bind(tag, "<Leave>", lambda ev: c.configure(cursor=""), add="+")
        c.bind("<ButtonPress-1>", self._drag_start)
        c.bind("<B1-Motion>", self._drag_move)
        r.bind("<Escape>", lambda ev: self.close())
        r.bind("<Return>", lambda ev: self.on_activate())
        e.bind("<FocusIn>", self._ph_hide)
        e.bind("<FocusOut>", self._ph_show)
        e.bind("<Button-3>", lambda ev: self._paste())

    def _btn_hover(self, on):
        if not self.busy and not self._btn_locked:
            self._paint_btn(self.G1H if on else self.G1, self.G2H if on else self.G2)

    def _paste(self):
        if self.busy or self._btn_locked:
            return
        try:
            t = self.root.clipboard_get().strip()
        except Exception:
            return
        if t:
            self._ph_hide()
            self.var.set(t.splitlines()[0].strip())
            self.entry.icursor("end")
            self.entry.focus_set()

    def _copy_hw(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(_hwid_short())
        except Exception:
            return
        self.c.itemconfigure(self.hw_id, text="คัดลอกรหัสเครื่องแล้ว ✓", fill=self.OK)
        self.root.after(1400, lambda: (not self.closed) and self.c.itemconfigure(
            self.hw_id, text=f"รหัสเครื่อง  {_hwid_short()}   ·   แตะเพื่อคัดลอก", fill=self.DIM))

    # ---- ลากหน้าต่าง ----
    def _drag_start(self, ev):
        tags = self.c.gettags("current")
        self._drag = None if ("btn" in tags or "close" in tags or "paste" in tags or "hw" in tags) else (
            ev.x_root - self.root.winfo_x(), ev.y_root - self.root.winfo_y())

    def _drag_move(self, ev):
        d = getattr(self, "_drag", None)
        if d:
            self.root.geometry(f"+{ev.x_root - d[0]}+{ev.y_root - d[1]}")

    # ---- placeholder ----
    def _ph_hide(self, ev=None):
        if self.ph_on:
            self.ph_on = False
            self.var.set("")
            self.entry.configure(fg=self.TXT)
        self.c.itemconfigure(self.box, outline=self.ACC)
        self.c.itemconfigure(self.glow, outline=_mix(self.BG, self.ACC, 0.4))

    def _ph_show(self, ev=None):
        if not self.var.get().strip():
            self.ph_on = True
            self.var.set(self.PLACEHOLDER)
            self.entry.configure(fg=self.DIM)
        self.c.itemconfigure(self.box, outline=self.EDGE)
        self.c.itemconfigure(self.glow, outline=self.BG)

    def _get_key(self):
        return "" if self.ph_on else self.var.get().strip()

    # ---- แสดง/ซ่อนส่วนต่าง ๆ ----
    def _show_form(self, on):
        st = "normal" if on else "hidden"
        self.c.itemconfigure("box", state=st)
        self.c.itemconfigure("btn", state=st)
        self.c.itemconfigure(self.entry_win, state=st)
        self.c.coords(self.status, self.W // 2, self.u(388))
        if on:
            self.root.after(50, self.entry.focus_force)

    def _show_panel(self, on):
        self.c.itemconfigure("panel", state="normal" if on else "hidden")
        self.c.itemconfigure("formonly", state="hidden" if on else "normal")
        if on:
            self.c.coords(self.status, self.W // 2, self.u(438))

    def set_status(self, text, kind="muted", animate=False):
        col = {"ok": self.OK, "err": self.BAD, "busy": self.BUSY}.get(kind, self.MUT)
        self.base = text
        self.c.itemconfigure(self.status, text=text, fill=col)
        if animate:
            self.busy = True
            self.gen += 1
            self._anim(self.gen)

    def _anim(self, gen):
        if not self.busy or self.closed or gen != self.gen:
            return
        self.dots = (self.dots + 1) % 4
        self.c.itemconfigure(self.status, text=self.base + "." * self.dots)
        self.root.after(350, lambda: self._anim(gen))

    def _set_busy(self, on, text=""):
        self.busy = False
        self._btn_locked = on
        if on:
            self.entry.configure(state="disabled")
            self._paint_btn(self.G1D, self.G2D)
            self.c.itemconfigure(self.btn_tx, text="กำลังตรวจสอบ", fill=self.MUT)
            self.set_status(text, "busy", animate=True)
        else:
            self.entry.configure(state="normal")
            self._paint_btn(self.G1, self.G2)
            self.c.itemconfigure(self.btn_tx, text="เปิดใช้งาน", fill=self.BTNTX)

    # ---- การทำงาน ----
    def on_activate(self):
        if self.busy or self.closed or self.c.itemcget(self.entry_win, "state") == "hidden":
            return
        key = self._get_key()
        if not key:
            self.set_status("กรุณากรอกคีย์ก่อน", "err")
            self._shake()
            return
        self._set_busy(True, "กำลังตรวจสอบคีย์")
        threading.Thread(target=self._worker, args=("key", key), daemon=True).start()

    def _worker(self, mode, key):
        try:
            self.q.put(("ok", check_saved() if mode == "saved" else activate(key)))
        except LicenseError as e:
            self.q.put(("err", e.msg))
        except Exception as e:
            self.q.put(("err", f"เกิดข้อผิดพลาดที่ไม่คาดคิด: {e}"))

    def _poll(self):
        if self.closed:
            return
        try:
            kind, val = self.q.get_nowait()
        except Exception:
            self.root.after(80, self._poll)
            return
        self.busy = False
        if kind == "ok" and val:
            self._success(val)
        elif kind == "ok":
            self._set_busy(False)
            self._show_form(True)
            self.set_status("กรุณากรอกคีย์ที่ได้รับเพื่อเปิดใช้งาน", "muted")
            self.root.after(80, self._poll)
        else:
            self._set_busy(False)
            self._show_form(True)
            self.set_status("✗ " + val, "err")
            self._shake()
            self.root.after(80, self._poll)

    def _success(self, info):
        self.info = info
        p = parse_key(info.get("key") or "")
        self.total = max(1, p[1] if p else int(info.get("remaining") or 1))
        self.entry.configure(state="normal")
        self._show_form(False)
        self._show_panel(True)
        self.c.itemconfigure(self.exp_id, text="หมดอายุ  " + time.strftime("%d/%m/%Y  %H:%M:%S", time.localtime(info["expiry"])))
        msg = "เปิดใช้งานสำเร็จ กำลังเปิดโปรแกรม"
        if info.get("offline"):
            msg = "ผ่าน (โหมดออฟไลน์ — เชื่อมเน็ตไม่ได้) กำลังเปิดโปรแกรม"
        self.set_status(msg, "ok")
        self._tick()
        self.root.after(3000, self._finish)

    def _tick(self):
        if self.closed:
            return
        left = _LIC["end_mono"] - time.monotonic()
        for item, v in zip(self.tiles, _split(left)):
            self.c.itemconfigure(item, text=f"{v:02d}")
        ratio = max(0.0, min(1.0, left / self.total))
        x2 = self.bar_x1 + int((self.bar_x2 - self.bar_x1) * ratio)
        self.c.coords(self.bar, self.bar_x1, self.bar_y, max(x2, self.bar_x1 + 1), self.bar_y)
        self.root.after(250, self._tick)

    def _finish(self):
        self.ok = True
        self.close(False)

    def close(self, quit_=True):
        if self.closed:
            return
        self.closed = True
        if quit_:
            self.ok = False
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()


# ---------------------------------------------------------------------
#  ป้ายเวลาคงเหลือลอยมุมจอ (always-on-top) — รันเป็นโปรเซสเล็กแยก ไม่ยุ่งกับ UI เดิม
# ---------------------------------------------------------------------
def _pid_alive(pid):
    try:
        if os.name == "nt":
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x00100000, False, int(pid))       # SYNCHRONIZE
            if not h:
                return False
            r = k.WaitForSingleObject(h, 0)
            k.CloseHandle(h)
            return r == 0x102                                    # WAIT_TIMEOUT = ยังทำงานอยู่
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _badge_main():
    """รันด้วย:  python สคริปต์.py --key-badge <วินาทีที่เหลือ> <เวลาหมดอายุ epoch> <pid แม่>"""
    import tkinter as tk
    remaining, expiry, ppid = float(sys.argv[2]), float(sys.argv[3]), int(sys.argv[4])
    end = time.monotonic() + remaining
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    r = tk.Tk()
    r.overrideredirect(True)
    TR, BG, EDGE = "#010203", "#0d0f17", "#262b3f"
    try:
        r.attributes("-topmost", True)
        r.attributes("-transparentcolor", TR)
        r.attributes("-alpha", 0.92)
    except Exception:
        pass
    S, fam = _ui_setup(r)
    u = lambda v: int(v * S)
    W, H, M = u(330), u(66), u(14)
    sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
    x = M if "left" in BADGE_CORNER else sw - W - M
    y = M if "top" in BADGE_CORNER else sh - H - M - u(40)
    r.geometry(f"{W}x{H}+{x}+{y}")
    r.configure(bg=TR)
    c = tk.Canvas(r, width=W, height=H, bg=TR, highlightthickness=0, bd=0)
    c.pack()
    _rrect(c, u(1), u(1), W - u(1), H - u(1), u(18), fill=BG, outline=EDGE, width=1)
    c.create_oval(u(16), u(16), u(24), u(24), fill="#34d399", outline="")
    c.create_text(u(32), u(20), text=f"เวลาคงเหลือ · หมดอายุ {time.strftime('%d/%m %H:%M', time.localtime(expiry))}",
                  fill="#8a92a8", font=(fam, -u(11)), anchor="w")
    big = c.create_text(W // 2, u(43), text="", fill="#e6e9f2", font=(fam, -u(19), "bold"))
    drag = {}
    c.bind("<ButtonPress-1>", lambda e: drag.update(x=e.x_root - r.winfo_x(), y=e.y_root - r.winfo_y()))
    c.bind("<B1-Motion>", lambda e: r.geometry(f"+{e.x_root - drag['x']}+{e.y_root - drag['y']}"))

    def tick():
        left = end - time.monotonic()
        if left <= 0 or not _pid_alive(ppid):
            r.destroy()
            return
        d, h, m, s = _split(left)
        parts = ([f"{d}วัน"] if d else []) + ([f"{h:02d}ชม."] if (d or h) else []) + [f"{m:02d}น.", f"{s:02d}วิ"]
        c.itemconfigure(big, text=" ".join(parts), fill="#e08a8a" if left < 300 else ("#e8b48a" if left < 3600 else "#e6e9f2"))
        if int(left) % 3 == 0:
            try:
                r.attributes("-topmost", True)
            except Exception:
                pass
        r.after(500, tick)

    tick()
    r.mainloop()


def _start_badge():
    try:
        args = ["--key-badge", str(int(_LIC["end_mono"] - time.monotonic())), str(_LIC["expiry"]), str(os.getpid())]
        cmd = [sys.executable] + args if getattr(sys, "frozen", False) else [sys.executable, os.path.abspath(__file__)] + args
        _LIC["badge"] = subprocess.Popen(cmd, creationflags=0x08000000 if os.name == "nt" else 0,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        _LIC["badge"] = None      # เปิดป้ายไม่ได้ก็ไม่เป็นไร โปรแกรมยังทำงานและยังหมดเวลาตามปกติ


# ---------------------------------------------------------------------
#  ตัวเฝ้าเวลาหมดอายุ: แจ้งเตือน แล้วปิดโปรแกรมอัตโนมัติ
# ---------------------------------------------------------------------
def _graceful_exit():
    """พยายามเรียก Core.shutdown() ของโปรแกรมเดิม (บันทึกตั้งค่า) ถ้าไม่ได้ภายใน 5 วิ ก็ปิดตรง ๆ"""
    def run():
        try:
            import gc
            core_cls = globals().get("Core")
            if core_cls:
                for o in gc.get_objects():
                    if isinstance(o, core_cls):
                        o.shutdown()
                        break
        except Exception:
            pass
    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(5)
    os._exit(0)


def _stop_with(msg, kind=None, extra=None, clear_cur=False):
    """แจ้งผู้ใช้ (กล่องข้อความ) แล้วปิดโปรแกรมอัตโนมัติ — ใช้ทั้งตอนหมดเวลาและตอนคีย์ถูกยกเลิก"""
    try:
        key = _LIC.get("key") or _state_load().get("cur")
        if kind:
            discord_notify(kind, key, force=True, extra=extra)
        for t in list(_hook_threads):
            t.join(3)
        if clear_cur:
            st = _state_load()
            st["cur"] = None
            _state_save(st)
    except Exception:
        pass
    try:
        if _LIC["badge"]:
            _LIC["badge"].terminate()
    except Exception:
        pass

    def box():
        try:
            import ctypes
            # MB_ICONINFORMATION | MB_SETFOREGROUND | MB_TOPMOST
            ctypes.windll.user32.MessageBoxW(0, msg + "\nโปรแกรมจะปิดลงอัตโนมัติ", LICENSE_TITLE, 0x40 | 0x10000 | 0x40000)
        except Exception:
            print(msg + " โปรแกรมจะปิดลงอัตโนมัติ")
    t = threading.Thread(target=box, daemon=True)
    t.start()
    t.join(8)               # รอให้กด OK ได้สูงสุด 8 วินาที แล้วปิดเอง
    _graceful_exit()


def _on_expired():
    _stop_with("เวลาใช้งานของคีย์หมดแล้ว", "expired", {"สถานะ": "หมดเวลาขณะใช้งาน โปรแกรมปิดอัตโนมัติ"})


def _recheck_online():
    """ตรวจคีย์กับ Supabase ขณะใช้งาน (เรียกในเธรดเฝ้า) — ถูกยกเลิก/ถูกรีเซ็ต/ไปผูกเครื่องอื่น = ปิดโปรแกรม"""
    key = _LIC.get("key")
    if not key:
        return True
    try:
        res, net = sb_check(key)
    except LicenseError:
        return False                            # เช็คไม่ได้ (เน็ตหลุด/เซิร์ฟเวอร์มีปัญหา) — ปล่อยให้ตัวนับช่วงออฟไลน์ตัดสิน
    code = res.get("code")
    if code in ("revoked", "invalid") and REVOKE_IF_REMOVED:
        _stop_with("คีย์นี้ถูกยกเลิกแล้ว ไม่สามารถใช้งานต่อได้", "revoked",
                   {"สถานะ": "ถูกยกเลิกขณะกำลังใช้งาน"}, clear_cur=True)
    elif code in ("hwid", "unbound", "unused"):
        _stop_with("คีย์นี้ถูกรีเซ็ตเครื่องหรือถูกใช้บนอุปกรณ์อื่นแล้ว ไม่สามารถใช้งานต่อได้\nกรุณาเปิดโปรแกรมใหม่แล้วกรอกคีย์อีกครั้ง",
                   "hwid" if code == "hwid" else None, {"สถานะ": "ผูกกับเครื่องอื่นขณะกำลังใช้งาน"}, clear_cur=True)
    return True


def _watcher():
    mono = time.monotonic
    last_save = last_chk = last_ok = mono()
    while mono() < _LIC["end_mono"]:
        time.sleep(1)
        now = mono()
        if now - last_save >= 30:                    # อัปเดต "เวลาล่าสุดที่เปิดโปรแกรม" ไว้เทียบเวลาย้อนหลัง
            last_save = now
            st = _state_load()
            st["last_seen"] = max(float(st.get("last_seen") or 0), _trusted_now())
            _state_save(st)
        if REVOKE_IF_REMOVED and now - last_chk >= RECHECK_INTERVAL:
            last_chk = now
            if _recheck_online():
                last_ok = mono()
                st = _state_load()
                st["last_verified"] = _trusted_now()
                _state_save(st)
            elif mono() - last_ok > OFFLINE_GRACE:   # ขาดการยืนยันกับเซิร์ฟเวอร์นานเกินกำหนด
                _stop_with("ไม่สามารถยืนยันคีย์กับเซิร์ฟเวอร์ได้นานเกินกำหนด\nกรุณาเชื่อมต่ออินเทอร์เน็ตแล้วเปิดโปรแกรมใหม่")
    _on_expired()


def _license_ui_snapshot():
    with _LICENSE_LOCK:
        result = dict(_LICENSE_UI)
        if result.get("state") == "active":
            result["remaining"] = max(0, int(_LIC.get("end_mono", 0) - time.monotonic()))
            result["expiry"] = float(_LIC.get("expiry", 0))
        return result


def _license_require_key(message="", code=""):
    with _LICENSE_LOCK:
        _LICENSE_UI.update(state="required", error=message or "", code=code or "", offline=False)


def _license_activate_ready(info, core):
    with _LICENSE_START_LOCK:
        if _license_ui_snapshot().get("state") == "active":
            return
        core.start(workers=True)
        if not getattr(core, "_license_watcher_started", False):
            core._license_watcher_started = True
            threading.Thread(target=_watcher, daemon=True).start()
        with _LICENSE_LOCK:
            _LICENSE_UI.update(state="active", error="", code="", offline=bool(info.get("offline")))


def _license_bootstrap(core):
    """ตรวจคีย์ที่จำไว้เบื้องหลัง; ถ้าไม่มี/ใช้ไม่ได้ ให้หน้า UI ขอคีย์ใหม่"""
    def check():
        try:
            info = check_saved()
            if info:
                _license_activate_ready(info, core)
            else:
                _license_require_key()
        except LicenseError as exc:
            _license_require_key(exc.msg, exc.code)
        except Exception:
            _license_require_key("ตรวจสอบสิทธิ์ไม่สำเร็จ กรุณาลองใหม่", "error")
    threading.Thread(target=check, daemon=True).start()


def license_gate():
    """หน้าต่างคีย์แบบเดิม (คงไว้เพื่อความเข้ากันได้; main ใช้หน้าคีย์ใน UI หลักแล้ว)"""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        win = _KeyWindow()
    except ImportError:
        print("ไม่พบ tkinter (ติดตั้ง Python จาก python.org แล้วเลือก tcl/tk) — เปิดหน้าต่างกรอกคีย์ไม่ได้")
        sys.exit(1)
    win.run()
    if not win.ok:
        sys.exit(0)
    threading.Thread(target=_watcher, daemon=True).start()


# โหมดป้ายลอย (ถูกเรียกจาก _start_badge) — ต้องอยู่ก่อน import ตัวหนัก ๆ ด้านล่าง จะได้เปิดเร็ว
if __name__ == "__main__" and len(sys.argv) >= 5 and sys.argv[1] == "--key-badge":
    _badge_main()
    sys.exit(0)
# =====================================================================
#  >>> จบบล็อกระบบกรอกคีย์ — โค้ดเดิมของคุณเริ่มตั้งแต่บรรทัดถัดไป <<<
# =====================================================================

import os
import sys
import json
import time
import math
import bisect
import ctypes
import secrets
import base64
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import cv2
import numpy as np

APP_NAME = "AutoMinigame"
SETTINGS_NAME = "settings.json"
LOGO_FILE = "logo.png"            # โลโก้ที่ผู้ใช้เลือกในตั้งค่า (เก็บในโฟลเดอร์เก็บข้อมูล)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# โลโก้เริ่มต้น: ถ้าวางไฟล์เหล่านี้ไว้ข้างไฟล์โปรแกรม จะถูกโหลดมาใช้เองทันทีที่เปิดโปรแกรม
LOGO_BESIDE = ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp")
# โลโก้ที่ฝังมากับโปรแกรม (PNG พื้นโปร่งใส เป็น base64) — เว้นว่างไว้ = ใช้โลโก้สายฟ้าเดิม
DEFAULT_LOGO_B64 = """
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
2Hnyz/8AuxlRnmRbZAUAAAAASUVORK5CYII=
"""
BG_FILE = "bg.jpg"                # รูปพื้นหลังที่ผู้ใช้เลือก (เก็บในโฟลเดอร์เก็บข้อมูล)
LEGACY_SETTINGS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "minigame_settings_v4.json")
# ไฟล์เล็ก ๆ ที่จำว่า "ผู้ใช้เลือกเก็บข้อมูลไว้ที่ไหน" (อยู่ที่ตายตัวเสมอ)
BOOT_FILE = os.path.join(os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config"),
                         APP_NAME, "location.json")
CROP = (0.25, 0.15, 0.75, 0.85)   # พื้นที่กลางจอที่ใช้สแกน (สัดส่วนหน้าจอ x1,y1,x2,y2)
DARK_MAX = 80                     # ค่า RGB สูงสุดที่ถือว่าเป็นสีดำของเส้นเชื่อม
WINDOW_TITLE = "Auto Minigame"

DEFAULTS = {
    "hotkey": "f8",          # ปุ่มเปิด/ปิดบอทมินิเกม
    "mode": "auto",          # auto / weld / bolt
    "weld_speed": 1400,      # [เชื่อม] ความเร็วลาก px/วินาที (ที่จอสูง 1080)
    "retry": True,           # [เชื่อม] ลองใหม่อัตโนมัติ
    "bolt_pre_ms": 10,       # [น็อต] หน่วงก่อนคลิก
    "bolt_post_ms": 60,      # [น็อต] หน่วงหลังคลิก
    "spam_key": "e",         # [กดรัว] ปุ่มที่จะกดรัว
    "spam_hotkey": "f7",     # [กดรัว] ปุ่มลัดเปิด/ปิด (หรือกดค้าง)
    "spam_ms": 25,           # [กดรัว] ระยะห่างระหว่างการกด (ms)
    "spam_hold": False,      # [กดรัว] True = กดปุ่มลัดค้างไว้ถึงจะรัว
    "topmost": True,
    "theme": "violet",       # ธีมสี (ดู THEMES ใน UI)
    "fx_on": True,           # เปิดเอฟเฟกต์พื้นหลัง (หิมะ ฝน ดาว ฯลฯ)
    "fx_kind": "auto",       # auto = ตามธีม หรือเลือกเอง
    "fx_amount": 60,         # ความหนาแน่นของเอฟเฟกต์ (%)
    "fx_pause": True,        # หยุดเอฟเฟกต์ตอนบอททำงาน (ลดภาระ CPU)
    "bg_on": False,          # ใช้รูปเป็นพื้นหลัง
    "bg_dim": 55,            # ความมืดทับรูป (%)
    "bg_blur": 0,            # ความเบลอของรูป (px)
    "bg_ver": 0,             # เลขเวอร์ชันรูป (ไว้ล้างแคช)
    "logo_ver": 0,           # เลขเวอร์ชันโลโก้ (ไว้ล้างแคช)
    "debug": False,
}
BOOLS = {"retry", "spam_hold", "topmost", "debug", "fx_on", "fx_pause", "bg_on"}
RANGES = {"weld_speed": (300, 4000), "bolt_pre_ms": (0, 100),
          "bolt_post_ms": (0, 400), "spam_ms": (1, 300),
          "fx_amount": (10, 100), "bg_dim": (0, 95), "bg_blur": (0, 24), "bg_ver": (0, 10 ** 9), "logo_ver": (0, 10 ** 9)}
MODES = ("auto", "weld", "bolt")
FX_IDS = ("auto", "snow", "rain", "stars", "bubbles", "fireflies", "embers", "petals",
          "sparkles", "matrix", "aurora")
THEME_IDS = ("violet", "ocean", "emerald", "sunset", "rose", "crimson", "gold",
             "cyber", "mint", "aurora", "slate", "amoled")


# =====================================================================
#  ตรวจจับภาพ
# =====================================================================
def find_red_dots(img_bgr):
    """มินิเกมเชื่อมเหล็ก: หาจุดแดง 4 จุด"""
    sub = img_bgr.astype(np.int16)
    b, g, r = sub[..., 0], sub[..., 1], sub[..., 2]
    mask = ((r > 170) & (r - g > 100) & (r - b > 100)).astype(np.uint8)
    n, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    cands = []
    for i in range(1, n):
        area = stats[i, cv2.CC_STAT_AREA]
        bw, bh = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
        if 60 < area < 1200 and 0.7 < bw / max(bh, 1) < 1.4:
            cands.append((area, cents[i][0], cents[i][1]))
    if len(cands) < 4:
        return []
    cands.sort(reverse=True)
    cands = cands[:4]
    areas = [c[0] for c in cands]
    if max(areas) / max(min(areas), 1) > 2.2:
        return []
    return [(c[1], c[2]) for c in cands]


def find_bolt_rings(img_bgr, scale=1.0):
    """มินิเกมขันน็อต: หาวงแหวนสีเหลืองทองบนแผ่นเทา คืนค่า list ของ (x, y)"""
    s = img_bgr.astype(np.int16)
    b, g, r = s[..., 0], s[..., 1], s[..., 2]
    mask = ((r > 190) & (g > 150) & (r - b > 50) & (r - b < 150) &
            (r - g < 55) & (r - g > 5)).astype(np.uint8)
    n, _, st, cents = cv2.connectedComponentsWithStats(mask)
    rings = []
    for i in range(1, n):
        area = st[i, cv2.CC_STAT_AREA]
        bw, bh = st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]
        if not (14 * scale <= bw <= 55 * scale and 14 * scale <= bh <= 55 * scale):
            continue
        if not (0.75 < bw / bh < 1.33):
            continue
        if area / float(bw * bh) > 0.65:      # วงแหวนต้องกลวง
            continue
        if area < 60 * scale * scale:
            continue
        x0, y0 = st[i, cv2.CC_STAT_LEFT], st[i, cv2.CC_STAT_TOP]
        m = int(10 * scale)
        ya, yb = max(y0 - m, 0), min(y0 + bh + m, img_bgr.shape[0])
        xa, xb = max(x0 - m, 0), min(x0 + bw + m, img_bgr.shape[1])
        patch = s[ya:yb, xa:xb]
        sat = patch.max(axis=2) - patch.min(axis=2)
        ring_px = mask[ya:yb, xa:xb] == 1
        gray_frac = float((sat[~ring_px] < 40).mean()) if (~ring_px).any() else 0.0
        if gray_frac < 0.75:                  # ต้องอยู่บนแผ่นหน้าแปลนสีเทา
            continue
        rings.append((float(cents[i][0]), float(cents[i][1])))
    return rings


def simplify_path(pts, scale=1.0):
    """ลดจุดให้เหลือเฉพาะมุมหัก -> เส้นตรงสะอาด ลากได้ลื่น"""
    if len(pts) < 3:
        return list(pts)
    arr = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)
    ap = cv2.approxPolyDP(arr, 2.5 * scale, False).reshape(-1, 2)
    out = [(float(x), float(y)) for x, y in ap]
    out[0] = (float(pts[0][0]), float(pts[0][1]))
    out[-1] = (float(pts[-1][0]), float(pts[-1][1]))
    return out


def build_paths(img_bgr, dots, scale=1.0):
    """คืน [path_ซ้าย, path_ขวา] (polyline จากบนลงล่าง)"""
    dots = sorted(dots, key=lambda p: p[1])
    tops = sorted(dots[:2], key=lambda p: p[0])
    bots = sorted(dots[2:], key=lambda p: p[0])
    mid_x = float(np.mean([p[0] for p in dots]))

    b, g, r = img_bgr[..., 0], img_bgr[..., 1], img_bgr[..., 2]
    dark = (b < DARK_MAX) & (g < DARK_MAX) & (r < DARK_MAX)

    pad = 25
    xl = int(min(p[0] for p in dots)) - pad
    xr = int(max(p[0] for p in dots)) + pad
    ranges = [(max(xl, 0), int(mid_x)), (int(mid_x), xr)]

    paths = []
    for (top, bot), (xa, xb) in zip(zip(tops, bots), ranges):
        pts = [top]
        prev_x = top[0]
        for y in range(int(top[1] + 11 * scale), int(bot[1] - 10 * scale)):
            xs = np.where(dark[y, xa:xb])[0]
            if not len(xs):
                continue
            groups = np.split(xs, np.where(np.diff(xs) > 3)[0] + 1)
            best = min(groups, key=lambda gp: abs(xa + gp.mean() - prev_x))
            x = xa + float(best.mean())
            if abs(x - prev_x) > 25 * scale:
                continue
            pts.append((x, float(y)))
            prev_x = x
        pts.append(bot)
        paths.append(simplify_path(pts, scale))
    return paths


def save_debug(img, paths=None, rings=None, name="debug.png"):
    out = np.ascontiguousarray(img).copy()
    for path in (paths or []):
        for a, b in zip(path, path[1:]):
            cv2.line(out, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), (0, 255, 0), 2)
        for p in path:
            cv2.circle(out, (int(p[0]), int(p[1])), 4, (255, 0, 255), -1)
    for x, y in (rings or []):
        cv2.circle(out, (int(x), int(y)), 22, (0, 255, 0), 2)
    cv2.imwrite(name, out)


# =====================================================================
#  ควบคุมเมาส์ (SendInput absolute) + หน้าต่าง
# =====================================================================
if os.name == "nt":
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class INPUT(ctypes.Structure):
        class _I(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT)]
        _anonymous_ = ("i",)
        _fields_ = [("type", wintypes.DWORD), ("i", _I)]

    _user32 = ctypes.windll.user32
    _MOVE, _LDOWN, _LUP, _ABS, _VDESK = 0x0001, 0x0002, 0x0004, 0x8000, 0x4000

    def _send(flags, nx=0, ny=0):
        inp = INPUT(type=0, mi=MOUSEINPUT(nx, ny, 0, flags, 0, 0))
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def mouse_move(x, y):
        vx, vy = _user32.GetSystemMetrics(76), _user32.GetSystemMetrics(77)
        vw, vh = _user32.GetSystemMetrics(78), _user32.GetSystemMetrics(79)
        nx = int(round((x - vx) * 65535 / max(vw - 1, 1)))
        ny = int(round((y - vy) * 65535 / max(vh - 1, 1)))
        _send(_MOVE | _ABS | _VDESK, nx, ny)

    def mouse_down():
        _send(_LDOWN)

    def mouse_up():
        _send(_LUP)

    def set_window_topmost(on):
        """ปักหมุดหน้าต่าง UI ให้อยู่บนสุด (คืน True ถ้าเจอหน้าต่าง)"""
        found = []
        proto = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def cb(hwnd, _):
            if _user32.IsWindowVisible(hwnd):
                n = _user32.GetWindowTextLengthW(hwnd)
                if n:
                    buf = ctypes.create_unicode_buffer(n + 1)
                    _user32.GetWindowTextW(hwnd, buf, n + 1)
                    if buf.value.startswith(WINDOW_TITLE):
                        found.append(hwnd)
            return True

        _user32.EnumWindows(proto(cb), 0)
        if not found:
            return False
        _user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                         ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        _user32.SetWindowPos(found[0], ctypes.c_void_p(-1 if on else -2), 0, 0, 0, 0,
                             0x0001 | 0x0002 | 0x0010)   # NOSIZE|NOMOVE|NOACTIVATE
        return True
else:
    def mouse_move(x, y): pass
    def mouse_down(): pass
    def mouse_up(): pass
    def set_window_topmost(on): return False


# =====================================================================
#  ที่จัดเก็บข้อมูล (ไดรฟ์/โฟลเดอร์)
# =====================================================================
def list_drives():
    """รายการไดรฟ์ให้เลือก พร้อมพื้นที่ว่าง และโฟลเดอร์ที่แนะนำให้เก็บ"""
    out = []
    if os.name == "nt":
        kinds = {2: "ไดรฟ์ถอดได้ (USB)", 3: "ฮาร์ดดิสก์", 4: "ไดรฟ์เครือข่าย"}
        sysdrv = (os.environ.get("SystemDrive") or "C:").upper()
        try:
            mask = ctypes.windll.kernel32.GetLogicalDrives()
        except Exception:
            mask = 0
        for i in range(26):
            if not (mask >> i) & 1:
                continue
            root = f"{chr(65 + i)}:\\"
            try:
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
                if dtype not in kinds:
                    continue
                total, _used, free = shutil.disk_usage(root)
            except Exception:
                continue
            is_sys = root[:2].upper() == sysdrv
            if is_sys:
                base = os.environ.get("LOCALAPPDATA") or os.path.join(root, "Users")
                suggest = os.path.join(base, APP_NAME)
            else:
                suggest = os.path.join(root, APP_NAME)
            out.append({"name": f"ไดรฟ์ {root[:2]}", "kind": kinds[dtype] + (" · ระบบ" if is_sys else ""),
                        "free": free, "total": total, "suggest": suggest, "system": is_sys})
    else:  # ไว้ทดสอบบนระบบอื่น
        for name, p in (("Home", os.path.expanduser("~")), ("Root", "/")):
            try:
                total, _used, free = shutil.disk_usage(p)
            except Exception:
                continue
            out.append({"name": name, "kind": "ดิสก์", "free": free, "total": total,
                        "suggest": os.path.join(p, APP_NAME), "system": name == "Home"})
    return out


def browse_folder(initial=""):
    """เปิดหน้าต่างเลือกโฟลเดอร์ (ทำในโปรเซสแยก กันชนกับ UI) คืนค่า path หรือ ''"""
    import subprocess
    code = ("import tkinter as tk\n"
            "from tkinter import filedialog\n"
            "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
            "p = filedialog.askdirectory(title='เลือกโฟลเดอร์เก็บข้อมูล', initialdir=%r)\n"
            "print(p or '')\n") % (initial if os.path.isdir(initial or "") else "",)
    try:
        flags = 0x08000000 if os.name == "nt" else 0      # CREATE_NO_WINDOW
        res = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=600,
                             env=dict(os.environ, PYTHONIOENCODING="utf-8"), creationflags=flags)
        p = res.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""
    if not p:
        return ""
    p = os.path.normpath(p)
    if os.path.basename(p).lower() != APP_NAME.lower():
        p = os.path.join(p, APP_NAME)     # สร้างโฟลเดอร์ย่อย ไม่เอาไฟล์ไปปนกับของอื่น
    return p


# =====================================================================
#  บอทมินิเกม
# =====================================================================
class Bot(threading.Thread):
    def __init__(self, core):
        super().__init__(daemon=True)
        self.app = core
        self.running = True
        self.scale = 1.0
        self.last_click = None
        self.last_click_t = 0.0
        self.bolt_count = 0

    def log(self, msg, kind="info"):
        self.app.log(msg, kind)

    # ---------- เชื่อมเหล็ก (เคลื่อนที่ตามเวลาจริง ลื่นและเร็ว) ----------
    def drag(self, path, speed):
        seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(path, path[1:])]
        cum = [0.0]
        for L in seg:
            cum.append(cum[-1] + L)
        total = cum[-1]
        if total <= 0:
            return True

        def point_at(d):
            i = min(bisect.bisect_right(cum, d) - 1, len(seg) - 1)
            t = (d - cum[i]) / seg[i] if seg[i] > 0 else 1.0
            return (path[i][0] + (path[i + 1][0] - path[i][0]) * t,
                    path[i][1] + (path[i + 1][1] - path[i][1]) * t)

        mouse_move(*path[0])
        time.sleep(0.05)
        mouse_down()
        time.sleep(0.04)
        try:
            t0 = time.perf_counter()
            while True:
                if not (self.running and self.app.enabled):
                    return False
                d = (time.perf_counter() - t0) * speed
                if d >= total:
                    break
                mouse_move(*point_at(d))
                time.sleep(0.001)
            mouse_move(*path[-1])
            time.sleep(0.06)
            return True
        finally:
            mouse_up()

    def play_weld(self, sct, region, img, dots):
        cfg = self.app.cfg
        speed = cfg["weld_speed"] * self.scale
        attempts = 3 if cfg["retry"] else 1
        for attempt in range(1, attempts + 1):
            paths = build_paths(img, dots, self.scale)
            if cfg["debug"]:
                save_debug(img, paths=paths, name=self.app.debug_path("debug_weld.png"))
            self.log(f"[เชื่อม] เริ่มลาก (รอบ {attempt}, {speed / self.scale:.0f} px/s)")
            for p in paths:
                shifted = [(x + region["left"], y + region["top"]) for x, y in p]
                if not self.drag(shifted, speed):
                    self.log("[เชื่อม] หยุดกลางคัน", "warn")
                    return
                time.sleep(0.10)
            if not cfg["retry"]:
                self.app.stats["weld"] += 1
                self.log("[เชื่อม] ลากครบแล้ว", "ok")
                return
            time.sleep(0.9)
            img = np.ascontiguousarray(np.array(sct.grab(region))[:, :, :3])
            dots = find_red_dots(img)
            if len(dots) != 4:
                self.app.stats["weld"] += 1
                self.log("[เชื่อม] สำเร็จ ✓", "ok")
                return
            self.log("[เชื่อม] ยังไม่ผ่าน -> ลองใหม่ให้ช้าลง", "warn")
            speed *= 0.65
        self.log("[เชื่อม] ลองครบแล้วยังไม่ผ่าน (ลดความเร็วลาก)", "err")

    # ---------- ขันน็อต ----------
    def click_bolts(self, rings, region, img):
        cfg = self.app.cfg
        pre = cfg["bolt_pre_ms"] / 1000.0
        post = cfg["bolt_post_ms"] / 1000.0
        if cfg["debug"]:
            save_debug(img, rings=rings, name=self.app.debug_path("debug_bolt.png"))
        for x, y in rings:
            now = time.time()
            if (self.last_click is not None and now - self.last_click_t < 0.35 and
                    math.hypot(x - self.last_click[0], y - self.last_click[1]) < 12 * self.scale):
                continue
            mouse_move(region["left"] + x, region["top"] + y)
            time.sleep(pre)
            mouse_down()
            time.sleep(0.02)
            mouse_up()
            self.bolt_count += 1
            self.app.stats["bolts"] += 1
            self.last_click = (x, y)
            self.last_click_t = time.time()
            self.log(f"[น็อต] คลิกตัวที่ {self.bolt_count}")
            time.sleep(post)

    # ---------- ลูปหลัก ----------
    def run(self):
        import mss
        with mss.mss() as sct:
            mon = sct.monitors[1]
            W, H = mon["width"], mon["height"]
            region = {
                "left": mon["left"] + int(CROP[0] * W),
                "top": mon["top"] + int(CROP[1] * H),
                "width": int((CROP[2] - CROP[0]) * W),
                "height": int((CROP[3] - CROP[1]) * H),
            }
            self.scale = H / 1080.0
            while self.running:
                if not self.app.enabled:
                    time.sleep(0.05)
                    continue
                try:
                    img = np.ascontiguousarray(np.array(sct.grab(region))[:, :, :3])
                    mode = self.app.cfg["mode"]
                    if mode in ("auto", "bolt"):
                        rings = find_bolt_rings(img, self.scale)
                        if rings:
                            self.click_bolts(rings, region, img)
                            continue
                    if mode in ("auto", "weld"):
                        dots = find_red_dots(img)
                        if len(dots) == 4:
                            self.play_weld(sct, region, img, dots)
                            time.sleep(1.0)
                            continue
                    if time.time() - self.last_click_t > 3:
                        self.bolt_count = 0
                except Exception as e:
                    self.log(f"error: {e}", "err")
                    time.sleep(1)
                time.sleep(0.01)



# =====================================================================
#  ปุ่มลัด: อ้างอิง "ตำแหน่งปุ่มจริง" (scan code) ไม่ขึ้นกับภาษาแป้นพิมพ์ ไทย/อังกฤษใช้ได้เหมือนกัน
# =====================================================================
KEY_SC = {"esc": 1, "-": 12, "=": 13, "backspace": 14, "tab": 15, "[": 26, "]": 27, "enter": 28,
          "ctrl": 29, ";": 39, "'": 40, "`": 41, "shift": 42, "\\": 43, ",": 51, ".": 52, "/": 53,
          "alt": 56, "space": 57, "capslock": 58, "numlock": 69, "scrolllock": 70,
          "home": 71, "up": 72, "pageup": 73, "left": 75, "right": 77, "end": 79, "down": 80,
          "pagedown": 81, "insert": 82, "delete": 83, "win": 91,
          "num*": 55, "num-": 74, "num+": 78, "num.": 83}
for _i, _c in enumerate("qwertyuiop"):
    KEY_SC[_c] = 16 + _i
for _i, _c in enumerate("asdfghjkl"):
    KEY_SC[_c] = 30 + _i
for _i, _c in enumerate("zxcvbnm"):
    KEY_SC[_c] = 44 + _i
for _i in range(1, 11):
    KEY_SC[str(_i % 10)] = 1 + _i
for _i in range(1, 11):
    KEY_SC[f"f{_i}"] = 58 + _i
KEY_SC["f11"], KEY_SC["f12"] = 87, 88
for _i, _sc in enumerate((82, 79, 80, 81, 75, 76, 77, 71, 72, 73)):
    KEY_SC[f"num{_i}"] = _sc
KEY_ALIAS = {"windows": "win", "control": "ctrl", "return": "enter", "escape": "esc", "del": "delete",
             "page up": "pageup", "page down": "pagedown", "caps lock": "capslock", "spacebar": "space",
             "left ctrl": "ctrl", "right ctrl": "ctrl", "left alt": "alt", "right alt": "alt",
             "alt gr": "alt", "left shift": "shift", "right shift": "shift",
             "left windows": "win", "right windows": "win"}
MOD_ORDER = ("ctrl", "alt", "shift", "win")
MOUSE_VK = {"mouse3": 0x04, "mouse4": 0x05, "mouse5": 0x06}     # กลาง / ข้าง 1 (ถอยหลัง) / ข้าง 2 (เดินหน้า)
MOUSE_LABEL = {"mouse3": "เมาส์กลาง", "mouse4": "เมาส์ข้าง 1", "mouse5": "เมาส์ข้าง 2"}
MOD_VK = {"ctrl": (0x11,), "alt": (0x12,), "shift": (0x10,), "win": (0x5B, 0x5C)}
SC_NAME = {}
for _n, _sc in KEY_SC.items():
    if not _n.startswith("num") or _n == "numlock":
        SC_NAME.setdefault(_sc, _n)
SC_NAME.update({54: "shift", 92: "win"})
SC_NAME_PAD = {v: k for k, v in KEY_SC.items() if k.startswith("num") and k != "numlock"}


def sc_to_name(sc, keypad=False):
    if keypad and sc in SC_NAME_PAD and sc not in (28,):
        return SC_NAME_PAD[sc]
    return SC_NAME.get(sc)


def hk_codes(text):
    """'ctrl+f8' -> [29, 66]   'f8' -> 66   (ใช้ scan code ส่งให้ไลบรารี keyboard)"""
    parts = [p.strip().lower() for p in str(text).split("+") if p.strip()]
    if not parts and str(text).strip() == "+":
        parts = ["+"]
    codes = []
    for p in parts:
        p = KEY_ALIAS.get(p, p)
        if p not in KEY_SC:
            raise ValueError(f"ไม่รู้จักปุ่ม '{p}'")
        codes.append(KEY_SC[p])
    if not codes:
        raise ValueError("ว่างเปล่า")
    return codes[0] if len(codes) == 1 else codes


def hk_mouse_parts(text):
    """คืน (รายชื่อ modifier, ชื่อปุ่มเมาส์) ถ้าไม่มีปุ่มเมาส์คืน ([], None)"""
    parts = [KEY_ALIAS.get(p.strip().lower(), p.strip().lower()) for p in str(text).split("+") if p.strip()]
    mouse = [p for p in parts if p in MOUSE_VK]
    if not mouse:
        return [], None
    others = [p for p in parts if p not in MOUSE_VK]
    if len(mouse) > 1 or any(p not in MOD_ORDER for p in others):
        raise ValueError("ปุ่มเมาส์ใช้ร่วมได้เฉพาะ Ctrl/Alt/Shift/Win")
    return others, mouse[0]


def hk_label(text):
    return " + ".join(MOUSE_LABEL.get(p.strip(), p.strip().upper()) for p in str(text).split("+"))


def mouse_click(tok):
    """คลิกปุ่มเมาส์ (กลาง/ข้าง) ด้วย Win32"""
    u = ctypes.windll.user32
    down, up, data = {"mouse3": (0x0020, 0x0040, 0), "mouse4": (0x0080, 0x0100, 1),
                      "mouse5": (0x0080, 0x0100, 2)}[tok]
    u.mouse_event(down, 0, 0, data, 0)
    time.sleep(0.008)
    u.mouse_event(up, 0, 0, data, 0)


def hk_normalize(text):
    parts = [KEY_ALIAS.get(p.strip().lower(), p.strip().lower()) for p in str(text).split("+") if p.strip()]
    mods, mouse = hk_mouse_parts("+".join(parts))
    if mouse:
        return "+".join([m for m in MOD_ORDER if m in mods] + [mouse])
    hk_codes("+".join(parts))
    mods = [m for m in MOD_ORDER if m in parts]
    rest = [p for p in parts if p not in MOD_ORDER]
    return "+".join(mods + rest)


# =====================================================================
#  กดรัว
# =====================================================================
class Spammer(threading.Thread):
    def __init__(self, core):
        super().__init__(daemon=True)
        self.app = core
        self.running = True

    def run(self):
        import keyboard
        while self.running:
            cfg = self.app.cfg
            if cfg["spam_hold"]:
                try:
                    active = self.app.hk_down(cfg["spam_hotkey"])
                except Exception:
                    active = False
            else:
                active = self.app.spam_on
            if active:
                try:
                    if cfg["spam_key"] in MOUSE_VK:
                        mouse_click(cfg["spam_key"])
                    else:
                        key = hk_codes(cfg["spam_key"])
                        if isinstance(key, list):
                            key = key[-1]
                        keyboard.press(key)
                        time.sleep(0.008)
                        keyboard.release(key)
                    self.app.stats["spam"] += 1
                except Exception:
                    pass
                time.sleep(max(cfg["spam_ms"], 1) / 1000.0)
            else:
                time.sleep(0.01)


# =====================================================================
#  แกนกลาง (สถานะ + ตั้งค่า + ปุ่มลัด)
# =====================================================================
class Core:
    def __init__(self):
        self.cfg = dict(DEFAULTS)
        self.data_dir = ""            # โฟลเดอร์เก็บข้อมูลที่ผู้ใช้เลือก
        self.needs_setup = True       # True = เปิดครั้งแรก ต้องให้เลือกที่เก็บก่อน
        self.setup_error = ""
        self._load_location()
        if self.needs_setup:
            self._load_settings_file(LEGACY_SETTINGS)    # ย้ายค่าเก่าจาก v4 มาให้ (ถ้ามี)
        self.enabled = False
        self.spam_on = False
        self.capturing = None
        self._tog = {}
        self.mouse_binds = {}
        self.stats = {"weld": 0, "bolts": 0, "spam": 0}
        self.logs = []
        self.log_id = 0
        self.lock = threading.Lock()
        self.handles = {}
        self.bot = None
        self.spammer = None
        self.last_poll = 0.0
        self.bye_time = 0.0
        self.quit_flag = False
        self._save_timer = None
        self._start_lock = threading.Lock()
        self._services_started = False
        self._workers_started = False
        self._license_watcher_started = False
        self.log("พร้อมใช้งาน")

    # ---------- เริ่ม/หยุดเธรดต่าง ๆ ----------
    def start(self, workers=True):
        with self._start_lock:
            if workers and not self._workers_started:
                self.bot = Bot(self)
                self.bot.start()
                self.spammer = Spammer(self)
                self.spammer.start()
                self.bind("hotkey")
                self.bind("spam_hotkey")
                threading.Thread(target=self._mouse_loop, daemon=True).start()
                self._workers_started = True
            if not self._services_started:
                threading.Thread(target=self._watchdog, daemon=True).start()
                threading.Thread(target=self._topmost_loop, daemon=True).start()
                self._services_started = True

    def shutdown(self):
        self.enabled = False
        self.spam_on = False
        if self.bot:
            self.bot.running = False
        if self.spammer:
            self.spammer.running = False
        try:
            mouse_up()
        except Exception:
            pass
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        self.save()
        os._exit(0)

    def _watchdog(self):
        while True:
            time.sleep(0.5)
            now = time.time()
            if self.quit_flag:
                time.sleep(0.4)
                self.shutdown()
            # ปิดหน้าต่างแล้วไม่มีใครกลับมาเชื่อมต่อภายใน 4 วินาที -> ปิดโปรแกรม
            if self.bye_time and now - self.bye_time > 4 and self.last_poll < self.bye_time:
                self.shutdown()
            # กรณีหน้าต่างหายไปเฉย ๆ เกิน 5 นาที
            if self.last_poll and now - self.last_poll > 300:
                self.shutdown()

    def _topmost_loop(self):
        # หน้าต่างเพิ่งเปิดอาจยังไม่พร้อม ลองซ้ำช่วงแรก
        for _ in range(40):
            if self.cfg["topmost"] and set_window_topmost(True):
                break
            time.sleep(0.5)

    # ---------- log ----------
    def log(self, msg, kind="info"):
        with self.lock:
            self.log_id += 1
            self.logs.append({"id": self.log_id, "t": time.strftime("%H:%M:%S"),
                              "msg": msg, "kind": kind})
            if len(self.logs) > 200:
                self.logs = self.logs[-200:]

    # ---------- ค่าตั้ง ----------
    @staticmethod
    def _clean(key, val):
        """ตรวจค่าที่รับเข้ามา คืน (ok, ค่า)"""
        if key in BOOLS:
            return True, bool(val)
        if key in RANGES:
            lo, hi = RANGES[key]
            try:
                return True, int(max(lo, min(hi, int(float(val)))))
            except Exception:
                return False, None
        if key == "mode":
            return (val in MODES), val
        if key == "theme":
            return (val in THEME_IDS), val
        if key == "fx_kind":
            return (val in FX_IDS), val
        return False, None

    def set_cfg(self, key, val):
        ok, v = self._clean(key, val)
        if not ok:
            return False
        self.cfg[key] = v
        self.save_later()
        if key == "topmost":
            set_window_topmost(v)
        if key == "spam_hold" and v:
            self.spam_on = False
        return True

    def reset(self):
        keep = {k: self.cfg[k] for k in ("hotkey", "spam_hotkey", "spam_key", "theme", "bg_ver", "logo_ver")}
        self.cfg = dict(DEFAULTS)
        self.cfg.update(keep)
        set_window_topmost(self.cfg["topmost"])
        self.save_later()
        self.log("รีเซ็ตค่าเป็นค่าเริ่มต้นแล้ว")

    def save_later(self):
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = threading.Timer(0.5, self.save)
        self._save_timer.daemon = True
        self._save_timer.start()

    # ---------- ที่จัดเก็บข้อมูล ----------
    @property
    def settings_path(self):
        return os.path.join(self.data_dir, SETTINGS_NAME) if self.data_dir else ""

    def debug_path(self, name):
        return os.path.join(self.data_dir, name) if self.data_dir else name

    def _load_settings_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            return False
        for k in DEFAULTS:
            if k not in saved:
                continue
            if k in ("hotkey", "spam_hotkey", "spam_key"):
                try:
                    if isinstance(saved[k], str) and 0 < len(saved[k]) < 40:
                        self.cfg[k] = hk_normalize(saved[k])
                except Exception:
                    pass                      # ค่าเก่าใช้ไม่ได้ (เช่นบันทึกเป็นตัวอักษรไทย) -> ใช้ค่าเริ่มต้น
            else:
                ok, v = self._clean(k, saved[k])
                if ok:
                    self.cfg[k] = v
        return True

    def _load_location(self):
        """อ่านว่าเคยเลือกที่เก็บไว้ที่ไหน ถ้าไม่มี/เข้าถึงไม่ได้ -> ต้องเลือกใหม่"""
        try:
            with open(BOOT_FILE, "r", encoding="utf-8") as f:
                path = json.load(f).get("data_dir", "")
        except Exception:
            return
        if not path:
            return
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            self.setup_error = f"เข้าถึงที่เก็บเดิมไม่ได้ ({path}) — กรุณาเลือกใหม่"
            return
        self.data_dir = path
        self.needs_setup = False
        self._load_settings_file(self.settings_path)

    def set_data_dir(self, path):
        """ตั้ง/ย้ายที่เก็บข้อมูล คืน (ok, ข้อความ error)"""
        path = os.path.abspath(os.path.expanduser(str(path or "").strip()))
        if not path or path == os.path.abspath(os.sep):
            return False, "โฟลเดอร์ไม่ถูกต้อง"
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".write_test")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
        except Exception as e:
            return False, f"เขียนไฟล์ในโฟลเดอร์นี้ไม่ได้ ({e}) ลองเลือกที่อื่น หรือเปิดโปรแกรมแบบ Administrator"
        old = self.data_dir
        target = os.path.join(path, SETTINGS_NAME)
        if os.path.exists(target) and old != path and self._load_settings_file(target):
            self.log("พบการตั้งค่าเดิมในที่เก็บนี้ — โหลดมาใช้แล้ว", "ok")
        self.data_dir = path
        self.needs_setup = False
        self.setup_error = ""
        if old and os.path.normcase(old) != os.path.normcase(path):
            try:
                for fn in (BG_FILE, LOGO_FILE):
                    ob, nb = os.path.join(old, fn), os.path.join(path, fn)
                    if os.path.isfile(ob) and not os.path.exists(nb):
                        shutil.copy2(ob, nb)
            except Exception:
                pass
        self.save()
        try:
            os.makedirs(os.path.dirname(BOOT_FILE), exist_ok=True)
            with open(BOOT_FILE, "w", encoding="utf-8") as f:
                json.dump({"data_dir": path}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.log(f"จำตำแหน่งที่เก็บไม่สำเร็จ: {e}", "warn")
        if old and os.path.normcase(old) != os.path.normcase(path):   # ย้ายแล้ว ลบไฟล์เก่าของเรา
            try:
                os.remove(os.path.join(old, SETTINGS_NAME))
                for fn in (BG_FILE, LOGO_FILE):
                    if os.path.isfile(os.path.join(old, fn)):
                        os.remove(os.path.join(old, fn))
                os.rmdir(old)
            except Exception:
                pass
        self.log(f"เก็บข้อมูลที่ {path}", "ok")
        return True, ""

    def bg_path(self):
        return os.path.join(self.data_dir, BG_FILE) if self.data_dir else ""

    def has_bg(self):
        p = self.bg_path()
        return bool(p) and os.path.isfile(p)

    def set_bg(self, data_url):
        """รับรูป (data URL) -> ตรวจ/ย่อ -> เก็บเป็น bg.jpg ในโฟลเดอร์เก็บข้อมูล คืน (ok, error)"""
        path = self.bg_path()
        if not path:
            return False, "ยังไม่ได้เลือกที่เก็บข้อมูล"
        try:
            raw = base64.b64decode(str(data_url).split(",", 1)[-1])
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return False, "ไฟล์รูปไม่ถูกต้อง"
            h, w = img.shape[:2]
            sc = min(1.0, 1920.0 / w, 1200.0 / h)
            if sc < 1.0:
                img = cv2.resize(img, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 86])
            if not ok:
                return False, "บันทึกรูปไม่สำเร็จ"
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(buf.tobytes())
            os.replace(tmp, path)
        except Exception as e:
            return False, f"ตั้งรูปไม่สำเร็จ ({e})"
        self.cfg["bg_ver"] += 1
        self.cfg["bg_on"] = True
        self.save_later()
        self.log("ตั้งรูปพื้นหลังแล้ว", "ok")
        return True, ""

    def clear_bg(self):
        try:
            os.remove(self.bg_path())
        except Exception:
            pass
        self.cfg["bg_on"] = False
        self.cfg["bg_ver"] += 1
        self.save_later()
        self.log("ลบรูปพื้นหลังแล้ว")

    def logo_path(self):
        """ที่เก็บโลโก้ที่ผู้ใช้เลือกเอง (ในโฟลเดอร์เก็บข้อมูล)"""
        return os.path.join(self.data_dir, LOGO_FILE) if self.data_dir else ""

    def _logo_file(self):
        """ลำดับความสำคัญ: 1) ที่ผู้ใช้เลือกเอง  2) logo.* ข้างไฟล์โปรแกรม  3) รูปที่ฝังในโค้ด -> (path|None, mime)"""
        p = self.logo_path()
        if p and os.path.isfile(p):
            return p, "image/png"
        for n in LOGO_BESIDE:
            q = os.path.join(SCRIPT_DIR, n)
            if os.path.isfile(q):
                ext = n.rsplit(".", 1)[-1]
                return q, "image/" + ("jpeg" if ext in ("jpg", "jpeg") else ext)
        return None, ""

    def has_logo(self):
        return bool(self._logo_file()[0]) or bool(DEFAULT_LOGO_B64.strip())

    def logo_bytes(self):
        p, mime = self._logo_file()
        if p:
            with open(p, "rb") as f:
                return f.read(), mime
        if DEFAULT_LOGO_B64.strip():
            return base64.b64decode(DEFAULT_LOGO_B64), "image/png"
        raise FileNotFoundError("no logo")

    def set_logo(self, data_url):
        """รับรูปโลโก้ (data URL) -> ย่อไม่เกิน 256px (คงพื้นโปร่งใส) -> เก็บเป็น logo.png"""
        path = self.logo_path()
        if not path:
            return False, "ยังไม่ได้เลือกที่เก็บข้อมูล"
        try:
            raw = base64.b64decode(str(data_url).split(",", 1)[-1])
            img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
            if img is None:
                return False, "ไฟล์รูปไม่ถูกต้อง"
            h, w = img.shape[:2]
            sc = min(1.0, 256.0 / max(w, h))
            if sc < 1.0:
                img = cv2.resize(img, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                return False, "บันทึกรูปไม่สำเร็จ"
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(buf.tobytes())
            os.replace(tmp, path)
        except Exception as e:
            return False, f"ตั้งโลโก้ไม่สำเร็จ ({e})"
        self.cfg["logo_ver"] += 1
        self.save_later()
        self.log("เปลี่ยนโลโก้แล้ว", "ok")
        return True, ""

    def clear_logo(self):
        try:
            os.remove(self.logo_path())
        except Exception:
            pass
        self.cfg["logo_ver"] += 1
        self.save_later()
        self.log("ลบโลโก้ที่เลือกเองแล้ว (กลับไปใช้โลโก้เริ่มต้น)")

    def open_data_dir(self):
        if self.data_dir and os.name == "nt":
            try:
                os.startfile(self.data_dir)
            except Exception:
                pass

    def save(self):
        if not self.data_dir:
            return
        try:
            tmp = self.settings_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.settings_path)
        except Exception:
            pass

    # ---------- สลับเปิด/ปิด ----------
    def _debounce(self, name, gap=0.35):
        now = time.time()
        if now - self._tog.get(name, 0) < gap:
            return True
        self._tog[name] = now
        return False

    def toggle(self):
        if self._debounce("bot"):
            return
        if self.needs_setup and not self.enabled:
            self.log("เลือกที่จัดเก็บข้อมูลก่อนเริ่มใช้งาน", "warn")
            return
        self.enabled = not self.enabled
        self.log("เปิดบอทมินิเกม" if self.enabled else "หยุดบอทมินิเกม",
                 "ok" if self.enabled else "info")

    def toggle_spam(self):
        if self._debounce("spam"):
            return
        if self.cfg["spam_hold"]:
            self.log("โหมดกดค้าง: กดปุ่มลัดค้างไว้เพื่อรัว", "warn")
            return
        self.spam_on = not self.spam_on
        self.log(f"กดรัว {self.cfg['spam_key'].upper()}: " + ("เปิด" if self.spam_on else "ปิด"),
                 "ok" if self.spam_on else "info")

    # ---------- ปุ่มลัด ----------
    def _mouse_down(self, mods, tok):
        u = ctypes.windll.user32
        if not (u.GetAsyncKeyState(MOUSE_VK[tok]) & 0x8000):
            return False
        for m in mods:
            if not any(u.GetAsyncKeyState(vk) & 0x8000 for vk in MOD_VK[m]):
                return False
        return True

    def hk_down(self, text):
        """ปุ่ม/คอมโบนี้ถูกกดค้างอยู่ไหม (รองรับทั้งคีย์บอร์ดและปุ่มเมาส์)"""
        try:
            mods, mouse = hk_mouse_parts(text)
            if mouse:
                return os.name == "nt" and self._mouse_down(mods, mouse)
            import keyboard
            return keyboard.is_pressed(hk_codes(text))
        except Exception:
            return False

    def _mouse_loop(self):
        """เฝ้าปุ่มเมาส์ที่ตั้งเป็นปุ่มลัด (ไลบรารี keyboard อ่านเมาส์ไม่ได้)"""
        if os.name != "nt":
            return
        last = {}
        while True:
            time.sleep(0.01)
            for target, (mods, tok) in list(self.mouse_binds.items()):
                try:
                    down = self._mouse_down(mods, tok)
                except Exception:
                    down = False
                if down and not last.get(target):
                    (self.toggle if target == "hotkey" else self.toggle_spam)()
                last[target] = down

    def bind(self, target):
        import keyboard
        self.unbind(target)
        fn = self.toggle if target == "hotkey" else self.toggle_spam
        try:
            mods, mouse = hk_mouse_parts(self.cfg[target])
            if mouse:
                self.mouse_binds[target] = (mods, mouse)
            else:
                self.handles[target] = keyboard.add_hotkey(hk_codes(self.cfg[target]), fn)
        except Exception as e:
            self.log(f"ตั้งปุ่มลัดไม่สำเร็จ: {e}", "err")

    def unbind(self, target):
        self.mouse_binds.pop(target, None)
        h = self.handles.pop(target, None)
        if h is not None:
            try:
                import keyboard
                keyboard.remove_hotkey(h)
            except Exception:
                pass

    def capture(self, target):
        if self.capturing or target not in ("hotkey", "spam_hotkey", "spam_key"):
            return
        import keyboard
        self.capturing = target
        if target in ("hotkey", "spam_hotkey"):
            self.unbind(target)

        def work():
            old = self.cfg[target]
            pressed, names = [], {}
            done = threading.Event()
            st = {"cancel": False, "bad": False}

            def on_event(e):
                sc = e.scan_code
                if e.event_type == "down":
                    if sc == 1 and not pressed:          # Esc = ยกเลิก
                        st["cancel"] = True
                        done.set()
                        return
                    nm = sc_to_name(sc, getattr(e, "is_keypad", False))
                    if nm is None:
                        st["bad"] = True
                        return
                    if sc not in pressed:
                        pressed.append(sc)
                        names[sc] = nm
                elif pressed:
                    done.set()

            hook = keyboard.hook(on_event)
            u = ctypes.windll.user32 if os.name == "nt" else None
            mouse_seen = None
            t0 = time.time()
            while not done.is_set() and time.time() - t0 < 30:
                if u:
                    for tok, vk in MOUSE_VK.items():
                        if u.GetAsyncKeyState(vk) & 0x8000:
                            mouse_seen = tok
                    if mouse_seen and not (u.GetAsyncKeyState(MOUSE_VK[mouse_seen]) & 0x8000):
                        done.set()
                time.sleep(0.01)
            try:
                keyboard.unhook(hook)
            except Exception:
                pass

            result = old
            if st["cancel"]:
                self.log("ยกเลิกการตั้งปุ่ม")
            elif not pressed and not mouse_seen:
                self.log("ปุ่มนี้ไม่รองรับ ลองปุ่มอื่น (ใช้ได้ทั้งแป้นไทย/อังกฤษ)" if st["bad"] else "หมดเวลาตั้งปุ่ม", "warn")
            else:
                ns = [names[c] for c in pressed]
                mods = [m for m in MOD_ORDER if m in ns]
                rest = [n for n in ns if n not in MOD_ORDER]
                if mouse_seen:
                    result = mouse_seen if target == "spam_key" else "+".join(mods + [mouse_seen])
                elif target == "spam_key":
                    result = (rest or mods)[-1]
                else:
                    result = "+".join(mods + rest)
                self.log(f"ตั้งปุ่มเป็น {hk_label(result)}", "ok")
            self.cfg[target] = result
            if target in ("hotkey", "spam_hotkey"):
                self.bind(target)
            self.capturing = None
            self.save_later()

        threading.Thread(target=work, daemon=True).start()

    def snapshot(self, since):
        self.last_poll = time.time()
        self.bye_time = 0.0
        with self.lock:
            logs = [l for l in self.logs if l["id"] > since]
            last_id = self.log_id
        return {"cfg": self.cfg, "enabled": self.enabled, "spam_on": self.spam_on,
                "capturing": self.capturing, "stats": self.stats,
                "logs": logs, "last_id": last_id,
                "needs_setup": self.needs_setup, "data_dir": self.data_dir, "has_bg": self.has_bg(), "has_logo": self.has_logo(),
                "setup_error": self.setup_error}


# =====================================================================
#  เซิร์ฟเวอร์ในเครื่อง (เสิร์ฟหน้า UI + API)
# =====================================================================
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    core = None
    token = ""
    port = 0
    discord_cache = {"at": 0.0, "payload": None}
    discord_lock = threading.Lock()

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _auth(self, q):
        host_ok = self.headers.get("Host", "") in (f"127.0.0.1:{self.port}", f"localhost:{self.port}")
        tok = self.headers.get("X-Token") or q.get("t", [""])[0]
        return host_ok and secrets.compare_digest(tok, self.token)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._auth(q):
            return self._send(403, "forbidden", "text/plain")
        if u.path == "/":
            return self._send(200, HTML.replace("__TOKEN__", self.token), "text/html")
        if u.path == "/api/state":
            try:
                since = int(q.get("since", ["0"])[0])
            except ValueError:
                since = 0
            payload = self.core.snapshot(since)
            payload["license"] = _license_ui_snapshot()
            return self._send(200, json.dumps(payload))
        if u.path == "/api/discord_widget":
            now = time.monotonic()
            with self.discord_lock:
                cached = self.discord_cache.get("payload")
                if cached is None or now - self.discord_cache.get("at", 0.0) >= 30:
                    try:
                        req = urllib.request.Request(
                            DISCORD_WIDGET_API,
                            headers={"User-Agent": _UA, "Accept": "application/json"},
                        )
                        with urllib.request.urlopen(req, timeout=6) as response:
                            raw = json.loads(response.read(1024 * 1024).decode("utf-8"))
                        if not isinstance(raw, dict):
                            raise ValueError("invalid widget response")
                        members = []
                        for member in raw.get("members", [])[:100]:
                            if not isinstance(member, dict):
                                continue
                            status = member.get("status")
                            if status not in ("online", "idle", "dnd", "offline"):
                                status = "online"
                            avatar = str(member.get("avatar_url") or "")
                            avatar_host = urlparse(avatar).hostname if avatar else None
                            if urlparse(avatar).scheme != "https" or avatar_host not in ("cdn.discordapp.com", "media.discordapp.net"):
                                avatar = ""
                            game = member.get("game")
                            game = str(game.get("name") or "")[:80] if isinstance(game, dict) else ""
                            members.append({
                                "username": str(member.get("username") or "สมาชิก")[:80],
                                "status": status,
                                "avatar_url": avatar,
                                "game": game,
                            })
                        try:
                            presence_count = max(0, int(raw.get("presence_count", len(members))))
                        except (TypeError, ValueError):
                            presence_count = len(members)
                        cached = {
                            "ok": True,
                            "name": str(raw.get("name") or "Discord")[:100],
                            "presence_count": presence_count,
                            "members": members,
                            "stale": False,
                        }
                        self.discord_cache.update({"at": now, "payload": cached})
                    except Exception:
                        if cached is None:
                            return self._send(200, json.dumps({
                                "ok": False,
                                "error": "ดึงข้อมูลวิดเจ็ตไม่ได้ ตรวจสอบการเปิด Server Widget และอินเทอร์เน็ต",
                            }, ensure_ascii=False))
                        cached = dict(cached)
                        cached["stale"] = True
            return self._send(200, json.dumps(cached, ensure_ascii=False))
        if u.path == "/api/drives":
            return self._send(200, json.dumps({"drives": list_drives()}))
        if u.path == "/logo":
            try:
                data, mime = self.core.logo_bytes()
                return self._send(200, data, mime)
            except Exception:
                return self._send(404, "{}", "text/plain")
        if u.path == "/bg":
            try:
                with open(self.core.bg_path(), "rb") as f:
                    return self._send(200, f.read(), "image/jpeg")
            except Exception:
                return self._send(404, "{}", "text/plain")
        self._send(404, "{}")

    def do_POST(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if not self._auth(q):
            return self._send(403, "forbidden", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 40 * 1024 * 1024:
            return self._send(413, json.dumps({"ok": False, "error": "ไฟล์ใหญ่เกินไป"}))
        try:
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        except Exception:
            body = {}
        c = self.core
        p = u.path
        ok = True
        if p == "/api/license/activate":
            if _license_ui_snapshot().get("state") == "active":
                return self._send(200, json.dumps({"ok": True, "license": _license_ui_snapshot()}))
            try:
                info = activate(str(body.get("key") or ""))
                _license_activate_ready(info, c)
                return self._send(200, json.dumps({"ok": True, "license": _license_ui_snapshot()}))
            except LicenseError as exc:
                _license_require_key(exc.msg, exc.code)
                return self._send(200, json.dumps({"ok": False, "error": exc.msg, "code": exc.code}))
            except Exception:
                message = "ตรวจสอบคีย์ไม่สำเร็จ กรุณาลองใหม่"
                _license_require_key(message, "error")
                return self._send(200, json.dumps({"ok": False, "error": message, "code": "error"}))
        if p not in ("/api/quit", "/api/bye") and _license_ui_snapshot().get("state") != "active":
            return self._send(423, json.dumps({"ok": False, "error": "กรุณาเปิดใช้งานด้วยคีย์ก่อน"}))
        if p == "/api/open_discord":
            try:
                import webbrowser
                ok = bool(webbrowser.open(DISCORD_INVITE_URL))
            except Exception:
                ok = False
        elif p == "/api/set":
            ok = c.set_cfg(body.get("key"), body.get("value"))
        elif p == "/api/toggle":
            c.toggle()
        elif p == "/api/toggle_spam":
            c.toggle_spam()
        elif p == "/api/capture":
            c.capture(body.get("target"))
        elif p == "/api/reset":
            c.reset()
        elif p == "/api/bye":
            c.bye_time = time.time()
        elif p == "/api/quit":
            c.quit_flag = True
        elif p == "/api/open_dir":
            c.open_data_dir()
        elif p == "/api/browse":
            return self._send(200, json.dumps({"path": browse_folder(str(body.get("initial") or ""))}))
        elif p == "/api/bg_upload":
            ok, err = c.set_bg(body.get("data", ""))
            return self._send(200, json.dumps({"ok": ok, "error": err}))
        elif p == "/api/bg_clear":
            c.clear_bg()
        elif p == "/api/logo_upload":
            ok, err = c.set_logo(body.get("data", ""))
            return self._send(200, json.dumps({"ok": ok, "error": err}))
        elif p == "/api/logo_clear":
            c.clear_logo()
        elif p == "/api/setup":
            ok, err = c.set_data_dir(body.get("path"))
            return self._send(200, json.dumps({"ok": ok, "error": err}))
        else:
            return self._send(404, "{}")
        self._send(200, json.dumps({"ok": ok}))


def launch_ui(url):
    """เปิด UI เป็นหน้าต่างแอป (Edge/Chrome --app) ถ้าไม่เจอจะเปิดในเบราว์เซอร์ปกติ"""
    import subprocess
    import webbrowser
    profile = os.path.join(tempfile.gettempdir(), "auto_minigame_ui_profile")
    exes = []
    for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env)
        if base:
            exes.append(os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"))
            exes.append(os.path.join(base, "Google", "Chrome", "Application", "chrome.exe"))
    for exe in exes:
        if os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--window-size=960,600",
                                  "--window-position=40,30", f"--user-data-dir={profile}",
                                  "--no-first-run", "--no-default-browser-check"])
                return True
            except Exception:
                continue
    webbrowser.open(url)
    return False


# =====================================================================
#  หน้า UI (HTML/CSS/JS)
# =====================================================================
HTML = r"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<title>Auto Minigame</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{
  --bg:#06070b; --panel:rgba(255,255,255,.05); --panel2:rgba(255,255,255,.08); --line:rgba(255,255,255,.09);
  --text:#eef0f7; --muted:#8a92a8; --a1:#7c5cff; --a2:#22d3ee; --a3:#5b8cff;
  --g1:124,92,255; --g2:34,211,238; --bgrgb:6,7,11; --soft:#c9bfff;
  --ok:#34d399; --bad:#fb7185; --warn:#fbbf24; --r:16px;
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  transition:background-color .35s;
  font-family:"Segoe UI","Leelawadee UI","Noto Sans Thai",system-ui,sans-serif;
  color:var(--text); background:var(--bg); overflow:hidden; user-select:none;
  background-image:
    radial-gradient(520px 340px at 96% -10%,rgba(var(--g1),.32),transparent 62%),
    radial-gradient(460px 320px at 8% 105%,rgba(var(--g2),.16),transparent 62%),
    radial-gradient(420px 300px at 55% 40%,rgba(var(--g1),.07),transparent 65%);
}
button{font:inherit;color:inherit;border:0;background:none;cursor:pointer}
svg{display:block}
.shell{height:100%;display:flex;flex-direction:column;border:1px solid rgba(255,255,255,.10)}

/* ---------- title bar (แทนแถบขาวของ Edge) ---------- */
.titlebar{height:42px;flex:none;display:flex;align-items:center;gap:12px;padding:0 6px 0 14px;
  background:linear-gradient(180deg,rgba(255,255,255,.05),rgba(0,0,0,.25));border-bottom:1px solid var(--line)}
.tb-brand{display:flex;align-items:center;gap:10px;flex:1;min-width:0}
.logo{width:26px;height:26px;border-radius:8px;display:grid;place-items:center;color:#fff;
  background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 4px 14px rgba(var(--g1),.5)}
.logo svg{width:14px;height:14px;pointer-events:none}
.tb-brand b{font-size:13.5px;font-weight:700;letter-spacing:.2px}
.tb-brand span{font-size:11.5px;color:var(--muted)}
.chips{display:flex;gap:6px}
.chip{display:flex;align-items:center;gap:6px;font-size:11.5px;font-weight:600;color:var(--muted);
  padding:4px 10px;border-radius:99px;background:var(--panel);border:1px solid var(--line);transition:.25s}
.chip i{width:7px;height:7px;border-radius:50%;background:var(--bad);box-shadow:0 0 0 3px rgba(251,113,133,.15);transition:.25s}
.chip.on{color:var(--text)}
.chip.on i{background:var(--ok);box-shadow:0 0 0 3px rgba(52,211,153,.2),0 0 12px var(--ok)}
.tb-ctl{display:none;gap:2px;margin-left:6px}
body.frameless .tb-ctl{display:flex}
.wbtn{width:40px;height:30px;display:grid;place-items:center;border-radius:8px;color:var(--muted);transition:.15s}
.wbtn svg{width:14px;height:14px;pointer-events:none}
.wbtn:hover{background:rgba(255,255,255,.1);color:#fff}
.wbtn.close:hover{background:#e5484d}
.wbtn.pin.on{color:var(--a2)}
.wbtn.pin.on svg{transform:rotate(-30deg)}

.winonly{display:none}
body.frameless .winonly{display:flex}

/* ---------- เอฟเฟกต์ + พื้นหลังรูป ---------- */
.shell{position:relative;overflow:hidden}
#bgimg{position:absolute;inset:-12px;z-index:0;display:none;pointer-events:none;background-size:cover;background-position:center;
  filter:blur(var(--blur,0px))}
#bgimg::after{content:"";position:absolute;inset:0;background:rgba(var(--bgrgb),var(--dim,.55))}
body.hasbg #bgimg{display:block}
#fx{position:absolute;inset:0;width:100%;height:100%;z-index:1;pointer-events:none}
.titlebar,.body{position:relative;z-index:2}
body.hasbg .card,body.hasbg .tile{background:rgba(var(--bgrgb),.52);backdrop-filter:blur(8px)}
body.hasbg .side{background:rgba(var(--bgrgb),.55);backdrop-filter:blur(8px)}
.logo.img{width:54px;height:36px;border-radius:0;box-shadow:none;background-color:transparent}
.logo.img svg{display:none}
.wbtn.fxb.on{color:var(--a2)}
.th small{display:block;color:var(--muted);font-weight:500;font-size:10.5px;margin-top:-3px}
.th.on small{color:var(--soft)}
.themes.fxk{margin:6px 0 4px}

/* ---------- ธีม ---------- */
.themes{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:8px;margin-top:8px}
.th{display:flex;flex-direction:column;gap:7px;padding:8px;border-radius:12px;text-align:left;font-size:12px;font-weight:600;
  background:var(--panel);border:1px solid var(--line);transition:.2s}
.th:hover{background:var(--panel2)}
.th .sw3{height:22px;border-radius:7px;border:1px solid rgba(255,255,255,.12)}
.th.on{border-color:var(--a2);box-shadow:0 0 0 3px rgba(var(--g2),.18);color:#fff}

/* ---------- ชุดสีธีม ---------- */
html[data-theme="violet"]{--bg:#06070b;--bgrgb:6,7,11;--a1:#7c5cff;--a2:#22d3ee;--a3:#5b8cff;--g1:124,92,255;--g2:34,211,238;--soft:#c9bfff}
html[data-theme="ocean"]{--bg:#050b14;--bgrgb:5,11,20;--a1:#0ea5e9;--a2:#2dd4bf;--a3:#3b82f6;--g1:14,165,233;--g2:45,212,191;--soft:#bae6fd}
html[data-theme="emerald"]{--bg:#040d0a;--bgrgb:4,13,10;--a1:#10b981;--a2:#a3e635;--a3:#22c55e;--g1:16,185,129;--g2:163,230,53;--soft:#bbf7d0}
html[data-theme="sunset"]{--bg:#0d0706;--bgrgb:13,7,6;--a1:#f97316;--a2:#f43f5e;--a3:#fb923c;--g1:249,115,22;--g2:244,63,94;--soft:#fed7aa}
html[data-theme="rose"]{--bg:#0d060a;--bgrgb:13,6,10;--a1:#ec4899;--a2:#a855f7;--a3:#f472b6;--g1:236,72,153;--g2:168,85,247;--soft:#fbcfe8}
html[data-theme="crimson"]{--bg:#0b0505;--bgrgb:11,5,5;--a1:#ef4444;--a2:#f59e0b;--a3:#dc2626;--g1:239,68,68;--g2:245,158,11;--soft:#fecaca}
html[data-theme="gold"]{--bg:#0b0904;--bgrgb:11,9,4;--a1:#eab308;--a2:#f97316;--a3:#facc15;--g1:234,179,8;--g2:249,115,22;--soft:#fef08a}
html[data-theme="cyber"]{--bg:#08040f;--bgrgb:8,4,15;--a1:#ff2bd6;--a2:#00f0ff;--a3:#7c3aed;--g1:255,43,214;--g2:0,240,255;--soft:#f5d0fe}
html[data-theme="mint"]{--bg:#050b0d;--bgrgb:5,11,13;--a1:#14b8a6;--a2:#67e8f9;--a3:#06b6d4;--g1:20,184,166;--g2:103,232,249;--soft:#99f6e4}
html[data-theme="aurora"]{--bg:#050a10;--bgrgb:5,10,16;--a1:#8b5cf6;--a2:#34d399;--a3:#38bdf8;--g1:139,92,246;--g2:52,211,153;--soft:#ddd6fe}
html[data-theme="slate"]{--bg:#08090b;--bgrgb:8,9,11;--a1:#94a3b8;--a2:#e2e8f0;--a3:#64748b;--g1:148,163,184;--g2:226,232,240;--soft:#e2e8f0}
html[data-theme="amoled"]{--bg:#000000;--bgrgb:0,0,0;--a1:#6366f1;--a2:#22d3ee;--a3:#818cf8;--g1:99,102,241;--g2:34,211,238;--soft:#c7d2fe}

/* ---------- layout ---------- */
.body{flex:1;min-height:0;display:flex}
.side{width:80px;flex:none;display:flex;flex-direction:column;align-items:center;gap:6px;padding:14px 8px;
  background:rgba(0,0,0,.2);border-right:1px solid var(--line)}
.nb{width:64px;padding:10px 0 8px;border-radius:14px;display:flex;flex-direction:column;align-items:center;gap:5px;
  font-size:11px;font-weight:600;color:var(--muted);transition:.2s}
.nb svg{width:21px;height:21px}
.nb:hover:not(.on){background:rgba(255,255,255,.06);color:var(--text)}
.nb.on{color:#fff;background:linear-gradient(135deg,var(--a1),var(--a3));box-shadow:0 8px 22px rgba(var(--g1),.42)}
.main{flex:1;min-width:0;display:flex;flex-direction:column;gap:10px;padding:12px 14px}
.pages{flex:1;min-height:0;position:relative}
.page{display:none;height:100%;flex-direction:column;gap:12px;overflow-y:auto;overflow-x:hidden;animation:fade .3s ease}
.page.on{display:flex}
.page::-webkit-scrollbar{width:6px}
.page::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:9px}
@keyframes fade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.cols{display:grid;gap:12px;flex:1}
.c-game{grid-template-columns:250px 1fr 1fr}
.c-spam{grid-template-columns:270px 1fr}
.c-set{grid-template-columns:1fr 1fr}
.stack{display:flex;flex-direction:column;gap:12px}
.stack>.card{flex:none}
.stack>.grow{flex:1}

.card{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:14px 16px;
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);transition:opacity .25s}
.card.dim{opacity:.4}
.card h2{font-size:11.5px;font-weight:700;letter-spacing:.9px;text-transform:uppercase;color:var(--muted);margin-bottom:4px}

/* ---------- Discord live server panel ---------- */
.discord-page{align-items:center;justify-content:center;padding:8px}
.discord-widget{width:min(100%,360px);height:min(100%,390px);min-height:270px;display:flex;flex-direction:column;overflow:hidden;
  border:1px solid #e2e4e8;border-radius:10px;background:#fff;color:#303338;box-shadow:0 5px 20px rgba(0,0,0,.18);font-family:"Segoe UI",system-ui,sans-serif}
.discord-head{min-height:74px;flex:none;display:flex;align-items:center;gap:10px;padding:12px 16px;background:#5865f2;color:#fff}
.discord-mark{width:31px;height:31px;flex:none}.discord-mark svg{width:100%;height:100%}
.discord-name{min-width:0;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:19px;font-weight:800}
.discord-count{flex:none;text-align:right;font-size:10.5px;line-height:1.4;white-space:nowrap}
.discord-count b{display:block;font-size:12px;font-weight:600}
.discord-list-head{display:flex;justify-content:space-between;gap:8px;padding:17px 18px 8px;color:#7c8188;font-size:11px;letter-spacing:.5px}
#discordStatus{max-width:48%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;letter-spacing:0;text-transform:none}
.discord-members{flex:1;min-height:0;overflow-y:auto;padding:0 15px 10px}
.discord-member{min-height:30px;display:flex;align-items:center;gap:8px;padding:3px 3px;font-size:12px;color:#4b5057}
.discord-avatar{width:21px;height:21px;flex:none;display:grid;place-items:center;overflow:hidden;border-radius:50%;background:#5865f2;color:#fff;font-size:10px;font-weight:700}
.discord-avatar img{width:100%;height:100%;object-fit:cover}
.discord-member-name{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1}
.discord-game{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#80858d;font-size:10px}
.discord-dot{width:9px;height:9px;flex:none;border:1px solid #fff;border-radius:50%;background:#3ba55d;box-shadow:0 0 0 1px #d9dce0}
.discord-dot.idle{background:#faa61a}.discord-dot.dnd{background:#ed4245}.discord-dot.offline{background:#747f8d}
.discord-empty{padding:8px 3px;color:#7c8188;font-size:12px}
.discord-foot{min-height:42px;flex:none;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:7px 12px;border-top:1px solid #d9dce0;background:#fff;font-size:11px;color:#51555b}
.discord-join{min-height:32px;padding:6px 11px;border-radius:5px;background:#5865f2;color:white;font-size:11px;font-weight:700;transition:filter .15s}
.discord-join:hover{filter:brightness(.92)}.discord-join:focus-visible{outline:3px solid #1f6feb;outline-offset:2px}
@media(max-width:560px){
  .tb-brand span,.chips{display:none}
  .tb-brand{gap:7px}.tb-brand b{font-size:12px}
  .discord-name{font-size:13px;line-height:1.15;white-space:normal;text-overflow:clip;overflow-wrap:anywhere}
  .discord-list-head{padding:13px 14px 6px}
  .discord-foot{padding:7px 9px}.discord-foot>span{font-size:10px}
}

/* seg */
.seg{position:relative;display:grid;grid-auto-flow:column;grid-auto-columns:1fr;padding:4px;border-radius:13px;
  background:rgba(0,0,0,.34);border:1px solid var(--line)}
.seg button{position:relative;z-index:1;padding:8px 4px;font-size:12.5px;font-weight:600;color:var(--muted);border-radius:10px;transition:color .2s}
.seg button.on{color:#fff}
.seg .thumb{position:absolute;top:4px;bottom:4px;left:4px;border-radius:10px;
  background:linear-gradient(135deg,var(--a1),var(--a3));box-shadow:0 6px 18px rgba(var(--g1),.4);
  transition:transform .28s cubic-bezier(.4,0,.2,1)}

/* stats */
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;flex:none}
.tile{display:flex;align-items:center;gap:12px;padding:10px 14px}
.tile .ti{width:34px;height:34px;border-radius:11px;display:grid;place-items:center;flex:none;color:var(--soft);
  background:linear-gradient(135deg,rgba(var(--g1),.28),rgba(var(--g2),.14));border:1px solid var(--line)}
.tile .ti svg{width:17px;height:17px}
.tile b{display:block;font-size:22px;line-height:1.1;font-weight:800;
  background:linear-gradient(135deg,#fff,var(--soft));-webkit-background-clip:text;background-clip:text;color:transparent}
.tile span{font-size:11.5px;color:var(--muted)}

/* hero */
.hero{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:16px 14px;
  background:linear-gradient(180deg,rgba(255,255,255,.07),rgba(255,255,255,.025))}
.hero .seg{width:100%;margin-top:4px}
.power{position:relative;width:112px;height:112px;border-radius:50%;display:grid;place-items:center;color:#cfd4e4;
  background:linear-gradient(145deg,#1f2433,#10131b);margin:8px 0 4px;
  box-shadow:inset 0 0 0 1px var(--line),0 14px 34px rgba(0,0,0,.5);transition:all .35s}
.power::before{content:"";position:absolute;inset:-10px;border-radius:50%;border:1px dashed rgba(255,255,255,.14);transition:.35s}
.power:hover{transform:scale(1.03)}
.power:active{transform:scale(.97)}
.power svg{width:44px;height:44px}
.power.on{color:#fff;background:linear-gradient(145deg,#10b981,#22d3ee);
  box-shadow:0 0 0 6px rgba(52,211,153,.13),0 0 50px rgba(34,211,238,.5);animation:pulse 2.2s ease-in-out infinite}
.power.on::before{border-color:rgba(52,211,153,.5);animation:spin 14s linear infinite}
@keyframes pulse{50%{box-shadow:0 0 0 14px rgba(52,211,153,.05),0 0 74px rgba(34,211,238,.65)}}
@keyframes spin{to{transform:rotate(360deg)}}
.state{font-size:20px;font-weight:700;transition:color .3s}
.state.ok{color:var(--ok)}
.sub{font-size:12.5px;color:var(--muted);display:flex;align-items:center;gap:8px;flex-wrap:wrap;justify-content:center}

/* keycaps */
.key{min-width:62px;padding:6px 13px;border-radius:10px;font:700 13px ui-monospace,Consolas,"Cascadia Mono",monospace;color:#fff;
  background:linear-gradient(#2c3242,#1c202b);border:1px solid rgba(255,255,255,.13);border-bottom-width:3px;
  box-shadow:0 3px 10px rgba(0,0,0,.35);transition:.15s}
button.key:hover{border-color:var(--a2)}
button.key:active{transform:translateY(2px);border-bottom-width:1px}
.key.cap{border-color:var(--a2);color:var(--a2);animation:blink 1s infinite}
@keyframes blink{50%{box-shadow:0 0 0 4px rgba(var(--g2),.25)}}
kbd.key{min-width:0;padding:2px 9px;font-size:12px;border-bottom-width:2px;display:inline-block}

.bigkey{width:120px;height:120px;border-radius:28px;display:grid;place-items:center;margin:6px 0;
  font:800 52px ui-monospace,Consolas,monospace;color:#cfd4e4;
  background:linear-gradient(160deg,#2c3242,#161a24);border:1px solid rgba(255,255,255,.13);border-bottom-width:7px;
  box-shadow:0 16px 36px rgba(0,0,0,.5);transition:all .3s}
.bigkey:hover{transform:translateY(-2px)}
.bigkey.on{color:#fff;border-color:rgba(52,211,153,.6);
  background:linear-gradient(160deg,#10b981,#0e8f9c);box-shadow:0 0 56px rgba(34,211,238,.5);
  animation:tap .12s infinite alternate}
@keyframes tap{to{transform:translateY(4px);border-bottom-width:3px}}

/* rows */
.row{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 0;font-size:13.5px}
.row+.row{border-top:1px solid var(--line)}
.row small{display:block;color:var(--muted);font-size:11.5px;margin-top:2px}

/* switch */
.sw{position:relative;width:42px;height:24px;flex:none}
.sw input{position:absolute;inset:0;opacity:0;cursor:pointer;z-index:1}
.sw i{position:absolute;inset:0;border-radius:99px;background:rgba(255,255,255,.14);transition:.25s}
.sw i::after{content:"";position:absolute;top:3px;left:3px;width:18px;height:18px;border-radius:50%;background:#fff;
  box-shadow:0 2px 6px rgba(0,0,0,.4);transition:.25s}
.sw input:checked+i{background:linear-gradient(135deg,var(--a1),var(--a2))}
.sw input:checked+i::after{transform:translateX(18px)}

/* slider */
.srow{padding:9px 0 11px}
.srow+.srow{border-top:1px solid var(--line)}
.shead{display:flex;justify-content:space-between;align-items:center;font-size:12.5px;margin-bottom:11px;gap:8px}
.shead span:first-child{color:var(--muted)}
.val{font-weight:700;font-size:11.5px;padding:3px 10px;border-radius:99px;background:rgba(var(--g1),.18);color:var(--soft);white-space:nowrap}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:6px;border-radius:99px;outline:none;cursor:pointer;
  background-color:#262a38;
  background-image:linear-gradient(90deg,var(--a1),var(--a2));
  background-size:var(--p,50%) 100%;background-repeat:no-repeat}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:19px;height:19px;border-radius:50%;background:#fff;
  box-shadow:0 0 0 5px rgba(var(--g1),.35),0 3px 10px rgba(0,0,0,.5);transition:box-shadow .15s}
input[type=range]:active::-webkit-slider-thumb{box-shadow:0 0 0 8px rgba(var(--g1),.35),0 3px 10px rgba(0,0,0,.5)}

/* buttons */
.btn{flex:1;padding:10px 12px;border-radius:12px;font-weight:700;font-size:13px;background:rgba(255,255,255,.07);
  border:1px solid var(--line);transition:.2s;display:flex;align-items:center;justify-content:center;gap:8px}
.btn svg{width:16px;height:16px}
.btn:hover{background:rgba(255,255,255,.12)}
.btn.primary{border:0;color:#fff;background:linear-gradient(135deg,var(--a1),var(--a3));box-shadow:0 8px 22px rgba(var(--g1),.4)}
.btn.primary:hover{filter:brightness(1.1)}
.btn.primary:disabled{opacity:.4;cursor:not-allowed;filter:none}
.btn.danger{color:var(--bad);border-color:rgba(251,113,133,.35);background:rgba(251,113,133,.08)}
.btn.danger:hover{background:rgba(251,113,133,.16)}
.btnrow{display:flex;gap:10px}
.tips{font-size:12.5px;color:var(--muted);line-height:1.85}
.tips b{color:var(--text)}

/* storage */
.store{display:flex;align-items:center;gap:12px;margin:8px 0 12px;padding:10px 12px;border-radius:13px;
  background:rgba(0,0,0,.28);border:1px solid var(--line)}
.store .di{width:40px;height:40px;border-radius:12px;flex:none;display:grid;place-items:center;color:#fff;
  background:linear-gradient(135deg,var(--a1),var(--a2))}
.store .di svg{width:20px;height:20px}
.store .inf{min-width:0}
.store .inf b{display:block;font-size:13.5px}
.store .inf span{display:block;font-size:11.5px;color:var(--muted);font:11.5px ui-monospace,Consolas,monospace;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;user-select:text}
.note{font-size:11.5px;color:var(--muted);margin-top:10px;line-height:1.6}

/* log */
.log{padding:8px 14px 6px;height:92px;display:flex;flex-direction:column;flex:none}
.loghead{display:flex;justify-content:space-between;align-items:center;gap:10px;font-size:10.5px;font-weight:700;letter-spacing:.9px;
  text-transform:uppercase;color:var(--muted);margin-bottom:3px}
.loghead>span:first-child{flex:1}
.loghead button{font-size:11px;color:var(--muted);padding:1px 8px;border-radius:7px}
.loghead button:hover{background:rgba(255,255,255,.08);color:var(--text)}
#log{flex:1;overflow-y:auto;font:11.5px/1.6 ui-monospace,Consolas,"Cascadia Mono",monospace;user-select:text}
#log::-webkit-scrollbar{width:5px}
#log::-webkit-scrollbar-thumb{background:rgba(255,255,255,.12);border-radius:9px}
#log div{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#aeb5c8}
#log .t{color:#586078;margin-right:8px}
#log .ok{color:var(--ok)} #log .warn{color:var(--warn)} #log .err{color:var(--bad)}

/* ---------- integrated license gate ---------- */
.license-gate{position:fixed;inset:0;z-index:30;display:grid;place-items:center;padding:24px;
  background:rgba(var(--bgrgb),.84);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px)}
.license-gate.hidden{display:none}
.license-card{position:relative;width:min(560px,100%);padding:30px;border:1px solid rgba(255,255,255,.15);border-radius:22px;
  background:linear-gradient(145deg,rgba(24,26,39,.96),rgba(12,14,22,.96));
  box-shadow:0 28px 90px rgba(0,0,0,.52),0 0 55px rgba(var(--g1),.12);overflow:hidden}
.license-card::before{content:"";position:absolute;left:12%;right:12%;top:0;height:2px;background:linear-gradient(90deg,transparent,var(--a1),var(--a2),transparent)}
.license-head{display:flex;align-items:center;gap:14px;margin-bottom:24px}
.license-mark{width:48px;height:48px;display:grid;place-items:center;flex:none;border-radius:15px;color:#fff;
  background:linear-gradient(135deg,var(--a1),var(--a2));box-shadow:0 8px 24px rgba(var(--g1),.36)}
.license-mark svg{width:23px;height:23px}
.license-brand{flex:1;min-width:0}.license-brand b{display:block;font-size:16px;letter-spacing:.2px}
.license-brand span{display:block;margin-top:3px;color:var(--muted);font-size:12px}
.license-close{width:36px;height:36px;border-radius:10px;color:var(--muted);font-size:20px}
.license-close:hover{background:rgba(255,255,255,.09);color:#fff}
.license-eyebrow{font-size:10px;letter-spacing:2px;font-weight:800;color:var(--soft);text-transform:uppercase}
.license-card h1{margin-top:8px;font-size:27px;line-height:1.25;letter-spacing:-.4px}
.license-copy{margin-top:8px;color:var(--muted);font-size:13px;line-height:1.65}
.license-form{margin-top:25px}.license-form[hidden]{display:none}
.license-form label{display:block;margin-bottom:9px;font-size:12px;font-weight:700;color:var(--text)}
.license-field{height:54px;display:flex;align-items:center;gap:12px;padding:0 15px;border-radius:13px;
  background:rgba(0,0,0,.28);border:1px solid rgba(255,255,255,.13);transition:border-color .2s,box-shadow .2s}
.license-field:focus-within{border-color:var(--a2);box-shadow:0 0 0 3px rgba(var(--g2),.16),0 0 24px rgba(var(--g1),.12)}
.license-field svg{width:18px;height:18px;flex:none;color:var(--soft)}
.license-field input{width:100%;min-width:0;border:0;outline:0;background:transparent;color:var(--text);font:500 14px ui-monospace,Consolas,monospace;user-select:text}
.license-field input::placeholder{color:#737b90}
.license-submit{width:100%;height:48px;margin-top:14px;border-radius:13px;color:#fff;font-size:13px;font-weight:800;
  background:linear-gradient(110deg,var(--a1),var(--a3),var(--a2));background-size:180% 100%;
  box-shadow:0 9px 24px rgba(var(--g1),.3);transition:filter .2s,transform .2s}
.license-submit:hover{filter:brightness(1.13);transform:translateY(-1px)}
.license-submit:disabled{opacity:.55;cursor:wait;transform:none}
.license-feedback{min-height:24px;display:flex;align-items:center;gap:9px;margin-top:15px;color:var(--muted);font-size:12px;line-height:1.5}
.license-indicator{width:19px;height:19px;flex:none;display:grid;place-items:center;border:1px solid transparent;border-radius:50%;font-size:15px;font-weight:900}
.license-feedback.busy .license-indicator{border:2px solid rgba(255,255,255,.18);border-top-color:var(--a2);animation:licenseSpin .8s linear infinite}
.license-feedback.error{color:var(--bad)}
.license-feedback.error .license-indicator{border-color:rgba(251,113,133,.5);background:rgba(251,113,133,.12)}
.license-feedback.error .license-indicator::before{content:"×"}
.license-feedback.ok{color:var(--ok)}
.license-feedback.ok .license-indicator{border-color:rgba(52,211,153,.45);background:rgba(52,211,153,.12)}
.license-feedback.ok .license-indicator::before{content:"✓"}
@keyframes licenseSpin{to{transform:rotate(360deg)}}
.license-foot{margin-top:18px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:11px;line-height:1.5}
.license-info{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px}
.license-info>div{padding:12px;border:1px solid var(--line);border-radius:12px;background:rgba(0,0,0,.18)}
.license-info small{display:block;color:var(--muted);font-size:11px}
.license-info b{display:block;margin-top:5px;color:var(--text);font-size:14px;line-height:1.4}
.license-chip{display:inline-flex;align-items:center;gap:7px;padding:5px 9px;border-radius:99px;background:rgba(52,211,153,.1);color:var(--ok);font-size:11px;font-weight:700}
.license-chip i{width:7px;height:7px;border-radius:50%;background:currentColor}
@media(max-width:560px){.license-gate{padding:14px}.license-card{padding:23px 19px;border-radius:18px}.license-card h1{font-size:23px}.license-head{margin-bottom:20px}.license-mark{width:42px;height:42px}}
@media(prefers-reduced-motion:reduce){.license-feedback.busy .license-indicator{animation:none}.license-submit{transition:none}}

/* ---------- first-run / change storage ---------- */
#setup{position:fixed;left:0;right:0;bottom:0;top:42px;z-index:8;display:none;place-items:center;padding:20px;
  background:rgba(var(--bgrgb),.9);backdrop-filter:blur(10px)}
#setup.show{display:grid;animation:fade .3s ease}
.sbox{width:100%;max-width:760px;padding:22px 24px 20px;border-radius:22px;background:rgba(18,20,30,.85);
  border:1px solid rgba(255,255,255,.12);box-shadow:0 30px 80px rgba(0,0,0,.6)}
.shd{display:flex;align-items:center;gap:14px;margin-bottom:6px}
.shd .logo{width:44px;height:44px;border-radius:14px}
.shd .logo svg{width:22px;height:22px}
.shd h3{font-size:20px;font-weight:800}
.shd p{font-size:12.5px;color:var(--muted);margin-top:2px}
.sq{font-size:13px;font-weight:700;margin:16px 0 10px;color:var(--text)}
.drives{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:10px;max-height:190px;overflow-y:auto;padding:2px}
.drive{text-align:left;padding:12px 14px;border-radius:14px;background:var(--panel);border:1px solid var(--line);transition:.2s}
.drive:hover{background:var(--panel2)}
.drive.sel{border-color:transparent;background:linear-gradient(rgba(24,26,40,.96),rgba(24,26,40,.96)) padding-box,
  linear-gradient(135deg,var(--a1),var(--a2)) border-box;border:1px solid transparent;box-shadow:0 0 0 4px rgba(var(--g1),.14)}
.drive .dt{display:flex;align-items:center;gap:10px;margin-bottom:9px}
.drive .dt .di{width:32px;height:32px;border-radius:10px;display:grid;place-items:center;background:rgba(255,255,255,.08);color:var(--soft)}
.drive .dt .di svg{width:17px;height:17px}
.drive.sel .dt .di{background:linear-gradient(135deg,var(--a1),var(--a2));color:#fff}
.drive .dt b{font-size:14px}
.drive .dt small{display:block;font-size:11px;color:var(--muted);margin-top:1px}
.dbar{height:5px;border-radius:9px;background:rgba(255,255,255,.1);overflow:hidden;margin-bottom:6px}
.dbar i{display:block;height:100%;border-radius:9px;background:linear-gradient(90deg,var(--a1),var(--a2))}
.drive span{font-size:11.5px;color:var(--muted)}
.spath{display:flex;align-items:center;gap:10px;margin-top:14px;padding:10px 12px;border-radius:12px;background:rgba(0,0,0,.35);border:1px solid var(--line)}
.spath small{font-size:11px;color:var(--muted);flex:none}
.spath code{font:12px ui-monospace,Consolas,monospace;color:var(--soft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;user-select:text}
#sErr{min-height:18px;margin-top:8px;font-size:12px;color:var(--bad)}
.sfoot{display:flex;gap:10px;margin-top:6px}
.sfoot .btn{flex:none;padding:10px 18px}
.sfoot .sp{flex:1}

#offline{position:fixed;inset:0;display:none;place-items:center;text-align:center;padding:30px;
  background:rgba(var(--bgrgb),.9);backdrop-filter:blur(8px);z-index:20;font-size:15px;line-height:1.7}
#offline.show{display:grid}
</style>
</head>
<body>
<div class="pywebview-drag-region shell">
  <div id="licenseGate" class="license-gate" role="dialog" aria-modal="true" aria-labelledby="licenseTitle">
    <div class="license-card">
      <div class="license-head">
        <div class="license-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M13 2 4 14h6l-1 8 9-12h-6z" fill="currentColor"/></svg></div>
        <div class="license-brand"><b>Auto Minigame</b><span>ปลอดภัย · พร้อมใช้งาน</span></div>
        <button class="license-close" id="licenseQuit" type="button" aria-label="ปิดโปรแกรม" title="ปิดโปรแกรม">×</button>
      </div>
      <div class="license-eyebrow">PREMIUM ACCESS</div>
      <h1 id="licenseTitle">เปิดใช้งานโปรแกรม</h1>
      <p class="license-copy">กรอกคีย์เพื่อยืนยันสิทธิ์ก่อนเริ่มใช้งาน</p>
      <form id="licenseForm" class="license-form" hidden>
        <label for="licenseKey">คีย์ใช้งาน</label>
        <div class="license-field">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="m11 12 9-9m-4 4 3 3m-6-1 3 3"/></svg>
          <input id="licenseKey" name="key" type="text" autocomplete="off" autocapitalize="characters" spellcheck="false" placeholder="วางคีย์ที่นี่" required>
        </div>
        <button class="license-submit" id="licenseSubmit" type="submit">เปิดใช้งาน</button>
      </form>
      <div id="licenseFeedback" class="license-feedback busy" role="status" aria-live="polite">
        <span class="license-indicator" aria-hidden="true"></span><span id="licenseMessage">กำลังตรวจสอบสิทธิ์การใช้งาน…</span>
      </div>
      <div class="license-foot">ข้อมูลสิทธิ์จะถูกตรวจสอบก่อนเปิดใช้งานโปรแกรม</div>
    </div>
  </div>
  <div id="bgimg"></div><canvas id="fx"></canvas>
  <!-- ===== แถบหัวหน้าต่าง (ลากเพื่อย้ายหน้าต่างได้) ===== -->
  <div class="titlebar pywebview-drag-region">
    <div class="tb-brand pywebview-drag-region">
      <div class="logo pywebview-drag-region"><svg viewBox="0 0 24 24"><path d="M13 2 4 14h6l-1 8 9-12h-6z" fill="currentColor"/></svg></div>
      <b class="pywebview-drag-region">Auto Minigame</b>
      <span class="pywebview-drag-region">เชื่อมเหล็ก · ขันน็อต · กดรัว</span>
    </div>
    <div class="chips pywebview-drag-region">
      <span class="chip" id="chipBot"><i></i>มินิเกม</span>
      <span class="chip" id="chipSpam"><i></i>กดรัว</span>
    </div>
    <button class="wbtn fxb" id="wFx" title="เปิด/ปิดเอฟเฟกต์"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/></svg></button>
    <div class="tb-ctl">
      <button class="wbtn pin" id="wPin" title="อยู่บนสุดเสมอ"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 17v5"/><path d="M9 3h6l-1 6 3 3v2H7v-2l3-3z"/></svg></button>
      <button class="wbtn" id="wMin" title="ย่อหน้าต่าง"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 12h14"/></svg></button>
      <button class="wbtn close" id="wClose" title="ปิดโปรแกรม"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
    </div>
  </div>

  <div class="pywebview-drag-region body">
    <!-- ===== เมนูซ้าย ===== -->
    <aside class="pywebview-drag-region side" id="nav">
      <button class="nb on" data-page="0"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/></svg>มินิเกม</button>
      <button class="nb" data-page="1"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="3"/><path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8"/></svg>กดรัว</button>
      <button class="nb" data-page="2"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>ตั้งค่า</button>
      <button class="nb" data-page="3" aria-label="Discord"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M6 7.5c3.8-2.2 8.2-2.2 12 0 1.2 2 2 4.6 2.1 7.3-1.6 1.7-3.3 2.5-5.2 3l-.8-1.3M10 16.5l-.8 1.3c-1.9-.5-3.6-1.3-5.2-3C4.1 12.1 4.8 9.5 6 7.5"/><path d="M9 12.5h.01M15 12.5h.01"/><path d="M8 9.3c2.7-.8 5.3-.8 8 0"/></svg>Discord</button>
    </aside>

    <section class="pywebview-drag-region main">
      <div class="pywebview-drag-region pages">

        <!-- ===== หน้า 1: มินิเกม ===== -->
        <section class="pywebview-drag-region page on" id="p0">
          <div class="pywebview-drag-region stats">
            <div class="card tile"><div class="ti"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 4 14h6l-1 8 9-12h-6z"/></svg></div><div><b id="stWeld">0</b><span>เชื่อมสำเร็จ</span></div></div>
            <div class="card tile"><div class="ti"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/></svg></div><div><b id="stBolt">0</b><span>น็อตที่คลิก</span></div></div>
            <div class="card tile"><div class="ti"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12" rx="3"/><path d="M8 14h8"/></svg></div><div><b id="stSpam">0</b><span>กดรัวแล้ว</span></div></div>
          </div>

          <div class="pywebview-drag-region cols c-game">
            <div class="card hero">
              <button class="power" id="power" title="เปิด/ปิด">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v9"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/></svg>
              </button>
              <div class="state" id="stateText">พร้อมใช้งาน</div>
              <div class="sub">กด <kbd class="key" data-keyshow="hotkey">F8</kbd> เพื่อเปิด/ปิด</div>
              <div class="seg" id="modeSeg">
                <span class="thumb"></span>
                <button data-mode="auto">อัตโนมัติ</button>
                <button data-mode="weld">เชื่อม</button>
                <button data-mode="bolt">น็อต</button>
              </div>
            </div>

            <div class="card" id="cardWeld">
              <h2>เชื่อมเหล็ก</h2>
              <div class="srow" data-key="weld_speed" data-label="ความเร็วลาก" data-min="300" data-max="4000" data-step="100" data-unit=" px/s"></div>
              <label class="row"><span>ลองใหม่อัตโนมัติ<small>ถ้ายังไม่ผ่านจะลากซ้ำให้ช้าลง</small></span>
                <span class="sw"><input type="checkbox" data-sw="retry"><i></i></span></label>
            </div>

            <div class="card" id="cardBolt">
              <h2>ขันน็อต</h2>
              <div class="srow" data-key="bolt_pre_ms" data-label="หน่วงก่อนคลิก" data-min="0" data-max="100" data-step="5" data-unit=" ms"></div>
              <div class="srow" data-key="bolt_post_ms" data-label="หน่วงหลังคลิก" data-min="0" data-max="400" data-step="10" data-unit=" ms"></div>
            </div>
          </div>
        </section>

        <!-- ===== หน้า 2: กดรัว ===== -->
        <section class="pywebview-drag-region page" id="p1">
          <div class="pywebview-drag-region cols c-spam">
            <div class="card hero">
              <button class="bigkey" id="bigKey" title="เปิด/ปิดกดรัว">E</button>
              <div class="state" id="spamText">ปิดอยู่</div>
              <div class="sub"><span id="rateText">≈ 30 ครั้ง/วินาที</span><span>·</span><span>กด <kbd class="key" data-keyshow="spam_hotkey">F7</kbd></span></div>
            </div>
            <div class="pywebview-drag-region stack">
              <div class="card">
                <h2>ปุ่ม</h2>
                <div class="row"><span>ปุ่มที่จะกดรัว</span><button class="key" data-target="spam_key">E</button></div>
                <div class="row"><span>ปุ่มลัดเปิด/ปิด</span><button class="key" data-target="spam_hotkey">F7</button></div>
              </div>
              <div class="card grow">
                <h2>ความเร็ว</h2>
                <div class="srow" data-key="spam_ms" data-label="ระยะห่างระหว่างการกด (น้อย = รัวไว)" data-min="1" data-max="300" data-step="1" data-unit=" ms"></div>
                <label class="row"><span>โหมดกดค้าง<small>กดปุ่มลัดค้างไว้ถึงจะรัว ปล่อยแล้วหยุด</small></span>
                  <span class="sw"><input type="checkbox" data-sw="spam_hold"><i></i></span></label>
              </div>
            </div>
          </div>
        </section>

        <!-- ===== หน้า 3: ตั้งค่า ===== -->
        <section class="pywebview-drag-region page" id="p2">
          <div class="pywebview-drag-region cols c-set">
            <div class="pywebview-drag-region stack">
              <div class="card">
                <h2>ปุ่มลัด</h2>
                <div class="row"><span>เปิด/ปิดบอทมินิเกม</span><button class="key" data-target="hotkey">F8</button></div>
              </div>
              <div class="card">
                <h2>ทั่วไป</h2>
                <label class="row"><span>หน้าต่างอยู่บนสุดเสมอ</span><span class="sw"><input type="checkbox" data-sw="topmost"><i></i></span></label>
                <label class="row"><span>บันทึกรูป debug<small>debug_weld.png / debug_bolt.png ในโฟลเดอร์เก็บข้อมูล</small></span><span class="sw"><input type="checkbox" data-sw="debug"><i></i></span></label>
              </div>
              <div class="card">
                <h2>หน้าต่าง</h2>
                <div class="btnrow" style="margin-top:8px">
                  <button class="btn winonly" id="btnMin"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 12h14"/></svg>ย่อหน้าต่าง</button>
                  <button class="btn danger" id="btnQuit"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 3v9"/><path d="M6.4 6.8a8 8 0 1 0 11.2 0"/></svg>ปิดโปรแกรม</button>
                </div>
              </div>
              <div class="btnrow">
                <button class="btn" id="btnReset">รีเซ็ตค่าตั้ง</button>
              </div>
            </div>
            <div class="pywebview-drag-region stack">
              <div class="card" id="licenseCard">
                <h2>สิทธิ์การใช้งาน</h2>
                <div><span class="license-chip"><i></i><span id="licenseMode">กำลังตรวจสอบ</span></span></div>
                <div class="license-info">
                  <div><small>เวลาคงเหลือ</small><b id="licenseRemain">—</b></div>
                  <div><small>หมดอายุ</small><b id="licenseExpiry">—</b></div>
                </div>
              </div>
              <div class="card">
                <h2>ธีม</h2>
                <div class="themes" id="themes"></div>
              </div>
              <div class="card">
                <h2>เอฟเฟกต์</h2>
                <label class="row"><span>เปิดเอฟเฟกต์พื้นหลัง<small>แต่ละธีมมีเอฟเฟกต์ของตัวเอง (ตามธีม) หรือเลือกเองได้</small></span><span class="sw"><input type="checkbox" data-sw="fx_on"><i></i></span></label>
                <div class="themes fxk" id="fxKinds"></div>
                <div class="srow" data-key="fx_amount" data-label="ความหนาแน่นเอฟเฟกต์" data-min="10" data-max="100" data-step="5" data-unit="%"></div>
                <label class="row"><span>หยุดเอฟเฟกต์ตอนบอททำงาน<small>ลดการใช้ CPU ให้บอทเล่นลื่นขึ้น</small></span><span class="sw"><input type="checkbox" data-sw="fx_pause"><i></i></span></label>
              </div>
              <div class="card">
                <h2>พื้นหลังรูปภาพ</h2>
                <label class="row"><span>ใช้รูปเป็นพื้นหลัง</span><span class="sw"><input type="checkbox" data-sw="bg_on"><i></i></span></label>
                <div class="btnrow" style="margin:8px 0">
                  <button class="btn" id="bgPick">เลือกรูป…</button>
                  <button class="btn" id="bgClear">ลบรูป</button>
                </div>
                <input type="file" id="bgFile" accept="image/*" hidden>
                <div class="note" id="bgMsg">รองรับ JPG / PNG / WebP — รูปจะถูกย่อและเก็บไว้ในโฟลเดอร์เก็บข้อมูล</div>
                <div class="srow" data-key="bg_dim" data-label="ความมืดของรูป" data-min="0" data-max="95" data-step="5" data-unit="%"></div>
                <div class="srow" data-key="bg_blur" data-label="ความเบลอของรูป" data-min="0" data-max="24" data-step="1" data-unit=" px"></div>
              </div>
              <div class="card">
                <h2>ที่จัดเก็บข้อมูล</h2>
                <div class="store">
                  <div class="di"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13 7.5 5h9L19 13"/><path d="M7 16.5h.01"/></svg></div>
                  <div class="inf"><b id="storeDrive">—</b><span id="storePath">—</span></div>
                </div>
                <div class="btnrow">
                  <button class="btn" id="btnOpen">เปิดโฟลเดอร์</button>
                  <button class="btn" id="btnChange">เปลี่ยนที่จัดเก็บ</button>
                </div>
                <div class="note">เก็บการตั้งค่าทั้งหมด (ความเร็ว ปุ่มลัด ฯลฯ) และรูป debug ไว้ที่นี่ ถ้าเปลี่ยนที่จัดเก็บ ระบบจะย้ายการตั้งค่าไปให้</div>
              </div>
              <div class="card grow">
                <h2>คำแนะนำ</h2>
                <div class="tips">
                  • เปิดโปรแกรมแบบ <b>Run as Administrator</b><br>
                  • เชื่อมเหล็กหลุดเส้น → <b>ลดความเร็วลาก</b><br>
                  • น็อตไม่ติด → <b>เพิ่มหน่วงก่อนคลิก</b><br>
                  • กดปุ่ม แล้วกดคีย์บนคีย์บอร์ดเพื่อเปลี่ยนได้ทุกปุ่ม<br>
                  • หน้าต่างบังเกม → <b>ย่อหน้าต่าง</b> (ตั้งค่า › หน้าต่าง) ปุ่มลัดยังทำงานปกติ<br>
                  • ลากโลโก้มุมซ้ายบนเพื่อย้ายหน้าต่าง
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- ===== หน้า 4: Discord server widget ===== -->
        <section class="pywebview-drag-region page discord-page" id="p3">
          <div class="discord-widget" aria-label="รายชื่อสมาชิกออนไลน์ใน Discord">
            <header class="discord-head">
              <div class="discord-mark" aria-hidden="true"><svg viewBox="0 0 24 24"><path fill="currentColor" d="M19.7 5.2a18.2 18.2 0 0 0-4.5-1.4l-.6 1.2a16.7 16.7 0 0 0-5.2 0l-.6-1.2a18.2 18.2 0 0 0-4.5 1.4C1.5 9.4.7 13.5 1.1 17.6a18.4 18.4 0 0 0 5.6 2.8l1.2-1.9-1.9-.9.5-.4c3.7 1.7 7.7 1.7 11.3 0l.5.4-1.9.9 1.2 1.9a18.4 18.4 0 0 0 5.6-2.8c.5-4.8-.8-8.9-3.5-12.4ZM8.7 15.2c-1.1 0-2-1-2-2.2s.9-2.2 2-2.2 2 .9 2 2.2-.9 2.2-2 2.2Zm6.6 0c-1.1 0-2-1-2-2.2s.9-2.2 2-2.2 2 .9 2 2.2-.9 2.2-2 2.2Z"/></svg></div>
              <div class="discord-name" id="discordName">Discord</div>
              <div class="discord-count"><b id="discordCount">—</b><span>Members Online</span></div>
            </header>
            <div class="discord-list-head"><span>MEMBERS ONLINE</span><span id="discordStatus" aria-live="polite">กำลังโหลด</span></div>
            <div class="discord-members" id="discordMembers" aria-live="polite"><div class="discord-empty">กำลังโหลดรายชื่อ…</div></div>
            <footer class="discord-foot">
              <span>Hangout with people who get it</span>
              <button class="discord-join" id="discordJoin" type="button">เปิด Discord</button>
            </footer>
          </div>
        </section>
      </div>

      <footer class="card log">
        <div class="loghead"><span>กิจกรรม</span>
          <button id="clearLog">ล้าง</button></div>
        <div id="log"></div>
      </footer>
    </section>
  </div>
</div>

<!-- ===== หน้าเลือกที่จัดเก็บข้อมูล (ครั้งแรก / เปลี่ยนภายหลัง) ===== -->
<div id="setup">
  <div class="sbox">
    <div class="shd">
      <div class="logo"><svg viewBox="0 0 24 24"><path d="M13 2 4 14h6l-1 8 9-12h-6z" fill="currentColor"/></svg></div>
      <div><h3 id="sTitle">ยินดีต้อนรับ</h3><p id="sSub">เลือกไดรฟ์ที่จะเก็บข้อมูลโปรแกรม เช่น การตั้งค่าต่าง ๆ</p></div>
    </div>
    <div class="sq">เลือกไดรฟ์</div>
    <div class="drives" id="drives"></div>
    <div class="spath"><small>จะเก็บที่</small><code id="sPath">—</code></div>
    <div id="sErr"></div>
    <div class="sfoot">
      <button class="btn" id="sBrowse">เลือกโฟลเดอร์เอง…</button>
      <span class="sp"></span>
      <button class="btn" id="sCancel" style="display:none">ยกเลิก</button>
      <button class="btn primary" id="sOk" disabled>เริ่มใช้งาน</button>
    </div>
  </div>
</div>
<div id="offline">การเชื่อมต่อกับโปรแกรมหลุด<br>โปรแกรมอาจถูกปิดไปแล้ว — เปิดใหม่ได้เลย</div>

<script>
const TOKEN="__TOKEN__";
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
let S=null, since=0, fails=0, licenseHoldUntil=0;

async function api(path, body){
  const r=await fetch(path,{method:body===undefined?"GET":"POST",
    headers:{"X-Token":TOKEN,"Content-Type":"application/json"},
    body:body===undefined?undefined:JSON.stringify(body)});
  return r.json();
}
function setLicenseFeedback(text,kind=""){
  const box=$("#licenseFeedback"); box.className="license-feedback"+(kind?" "+kind:"");
  $("#licenseMessage").textContent=text;
}
function licenseDuration(sec, precise=false){
  sec=Math.max(0,Math.floor(+sec||0));
  const d=Math.floor(sec/86400),h=Math.floor((sec%86400)/3600),m=Math.floor((sec%3600)/60);
  if(!precise&&sec>=20*3600) return `ประมาณ ${Math.ceil(sec/86400)} วัน`;
  if(d) return `${d} วัน ${h} ชม.`;
  if(h) return `${h} ชั่วโมง ${m} นาที`;
  return `${Math.max(1,m)} นาที`;
}
function renderLicense(l){
  l=l||{};
  const gate=$("#licenseGate"),form=$("#licenseForm"),input=$("#licenseKey"),submit=$("#licenseSubmit");
  if(l.state==="active"){
    const left=Math.max(0,+l.remaining||0);
    $("#licenseRemain").textContent=licenseDuration(left,true);
    $("#licenseExpiry").textContent=l.expiry?new Date(l.expiry*1000).toLocaleString("th-TH",{dateStyle:"medium",timeStyle:"short"}):"—";
    $("#licenseMode").textContent=l.offline?"ใช้งานได้ · ออฟไลน์":"ใช้งานได้";
    if(Date.now()>=licenseHoldUntil) gate.classList.add("hidden");
    return;
  }
  gate.classList.remove("hidden");
  if(l.state==="checking"){
    form.hidden=true; setLicenseFeedback("กำลังตรวจสอบสิทธิ์การใช้งาน…","busy");
  }else{
    form.hidden=false; input.disabled=false; submit.disabled=false;
    if(l.error) setLicenseFeedback(l.error,"error");
    else setLicenseFeedback("กรอกคีย์เพื่อเปิดใช้งานโปรแกรม");
  }
}
$("#licenseForm").addEventListener("submit",async e=>{
  e.preventDefault();
  const input=$("#licenseKey"),submit=$("#licenseSubmit"),key=input.value.trim();
  if(!key){setLicenseFeedback("กรุณากรอกคีย์ก่อน","error");input.focus();return;}
  input.disabled=true;submit.disabled=true;setLicenseFeedback("กำลังตรวจสอบคีย์…","busy");
  try{
    const r=await api("/api/license/activate",{key});
    if(r.ok){
      const l=r.license||{}; licenseHoldUntil=Date.now()+1400;
      const remaining=+l.remaining||0;
      setLicenseFeedback("เปิดใช้งานสำเร็จ · ใช้งานได้อีก "+licenseDuration(remaining),"ok");
      $("#licenseRemain").textContent=licenseDuration(remaining,true);
      $("#licenseExpiry").textContent=l.expiry?new Date(l.expiry*1000).toLocaleString("th-TH",{dateStyle:"medium",timeStyle:"short"}):"—";
      $("#licenseMode").textContent=l.offline?"ใช้งานได้ · ออฟไลน์":"ใช้งานได้";
      setTimeout(()=>$("#licenseGate").classList.add("hidden"),1400);
    }else{
      setLicenseFeedback(r.error||"คีย์ไม่ถูกต้องหรือหมดอายุแล้ว","error");
      input.disabled=false;submit.disabled=false;input.focus();input.select();
    }
  }catch(err){
    setLicenseFeedback("เชื่อมต่อเพื่อตรวจสอบคีย์ไม่ได้ กรุณาลองใหม่","error");
    input.disabled=false;submit.disabled=false;
  }
});
$("#licenseQuit").addEventListener("click",quitApp);
const MOUSE_NAME={mouse3:"เมาส์กลาง",mouse4:"เมาส์ข้าง 1",mouse5:"เมาส์ข้าง 2"};
const pretty=k=>String(k||"").split("+").map(s=>{s=s.trim(); return MOUSE_NAME[s]||s.toUpperCase();}).join(" + ");
/* กันปุ่มข้างเมาส์ไปสั่ง "ย้อนกลับ/ไปข้างหน้า" ของหน้าเว็บ */
["mousedown","mouseup","pointerup","auxclick"].forEach(t=>window.addEventListener(t,e=>{ if(e.button>=1) e.preventDefault(); },true));
const MODES=["auto","weld","bolt"];

/* ---------- window controls (โหมดไร้กรอบ) ---------- */
function enableFrameless(){ document.body.classList.add("frameless"); }
if(window.pywebview) enableFrameless();
window.addEventListener("pywebviewready",enableFrameless);
const winCall=n=>{ if(window.pywebview&&pywebview.api&&pywebview.api[n]) pywebview.api[n](); };
$("#btnMin").addEventListener("click",()=>winCall("minimize"));

/* ---------- ลากหน้าต่าง (เรียก Windows โดยตรง ไม่พึ่งระบบลากของ pywebview) ---------- */
window.addEventListener("mousedown",e=>{
  if(e.button!==0||!document.body.classList.contains("frameless")) return;
  if(!/Win/i.test(navigator.platform)) return;
  if(!e.target.classList||!e.target.classList.contains("pywebview-drag-region")) return;
  if(!(window.pywebview&&pywebview.api&&pywebview.api.start_drag)) return;
  e.preventDefault(); e.stopImmediatePropagation();
  pywebview.api.start_drag();
},true);

/* ---------- ธีม ---------- */
const THEMES=[
  {id:"violet", name:"ม่วงนีออน", c:["#7c5cff","#22d3ee"]},
  {id:"ocean",  name:"มหาสมุทร",  c:["#0ea5e9","#2dd4bf"]},
  {id:"emerald",name:"มรกต",      c:["#10b981","#a3e635"]},
  {id:"sunset", name:"พระอาทิตย์ตก",c:["#f97316","#f43f5e"]},
  {id:"rose",   name:"ชมพูหวาน",  c:["#ec4899","#a855f7"]},
  {id:"crimson",name:"แดงเลือด",  c:["#ef4444","#f59e0b"]},
  {id:"gold",   name:"ทองคำ",     c:["#eab308","#f97316"]},
  {id:"cyber",  name:"ไซเบอร์พังก์",c:["#ff2bd6","#00f0ff"]},
  {id:"mint",   name:"มิ้นต์เย็น", c:["#14b8a6","#67e8f9"]},
  {id:"aurora", name:"ออโรรา",    c:["#8b5cf6","#34d399"]},
  {id:"slate",  name:"เทาเรียบ",  c:["#94a3b8","#e2e8f0"]},
  {id:"amoled", name:"ดำสนิท",    c:["#6366f1","#22d3ee"]},
];
let curTheme=null;
function applyTheme(id){
  if(!THEMES.some(t=>t.id===id)) id="violet";
  if(id===curTheme) return; curTheme=id;
  document.documentElement.dataset.theme=id;
  $$("#themes .th").forEach(b=>b.classList.toggle("on",b.dataset.theme===id));
}
function buildThemes(){
  $("#themes").innerHTML=THEMES.map(t=>`<button class="th" data-theme="${t.id}">
    <span class="sw3" style="background:linear-gradient(135deg,${t.c[0]},${t.c[1]})"></span>${t.name}<small>${FX_NAME[THEME_FX[t.id]]}</small></button>`).join("");
  $("#themes").addEventListener("click",e=>{
    const b=e.target.closest(".th"); if(!b) return;
    applyTheme(b.dataset.theme);
    if(S) S.cfg.theme=b.dataset.theme;
    api("/api/set",{key:"theme",value:b.dataset.theme});
  });
}

/* ---------- nav ---------- */
function setThumb(seg,idx,n){
  const t=seg.querySelector(".thumb");
  t.style.width=`calc((100% - 8px) / ${n})`;
  t.style.transform=`translateX(${idx*100}%)`;
}
$("#nav").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b) return;
  const i=+b.dataset.page;
  $$("#nav button").forEach(x=>x.classList.toggle("on",x===b));
  $$(".page").forEach((p,j)=>p.classList.toggle("on",j===i));
  if(i===3) startDiscordRefresh();
});

let discordTimer=null, discordBusy=false;
function renderDiscord(data){
  $("#discordName").textContent=data.name||"Discord";
  $("#discordCount").textContent=Math.max(0,+data.presence_count||0).toLocaleString("en-US");
  $("#discordStatus").textContent=data.stale?"ข้อมูลล่าสุด":"อัปเดตแล้ว";
  const list=$("#discordMembers"); list.replaceChildren();
  const members=Array.isArray(data.members)?data.members:[];
  if(!members.length){
    const empty=document.createElement("div"); empty.className="discord-empty"; empty.textContent="ไม่มีสมาชิกออนไลน์ที่แสดง"; list.append(empty); return;
  }
  for(const member of members){
    const row=document.createElement("div"); row.className="discord-member";
    const avatar=document.createElement("span"); avatar.className="discord-avatar";
    if(member.avatar_url){
      const img=document.createElement("img"); img.src=member.avatar_url; img.alt=""; img.loading="lazy";
      img.onerror=()=>{ avatar.textContent=(member.username||"?").trim().slice(0,1).toUpperCase(); };
      avatar.append(img);
    }else avatar.textContent=(member.username||"?").trim().slice(0,1).toUpperCase();
    const name=document.createElement("span"); name.className="discord-member-name";
    name.textContent=member.username||"สมาชิก";
    if(member.game){ const game=document.createElement("small"); game.className="discord-game"; game.textContent="กำลังเล่น "+member.game; name.append(game); }
    const dot=document.createElement("i"); dot.className="discord-dot "+(["online","idle","dnd","offline"].includes(member.status)?member.status:"online");
    dot.setAttribute("aria-label",member.status||"online");
    row.append(avatar,name,dot); list.append(row);
  }
}
async function refreshDiscord(){
  if(discordBusy) return; discordBusy=true;
  $("#discordStatus").textContent="กำลังโหลด";
  try{
    const data=await api("/api/discord_widget");
    if(!data.ok) throw new Error(data.error||"โหลดไม่สำเร็จ");
    renderDiscord(data);
  }catch(e){
    $("#discordStatus").textContent="เชื่อมต่อไม่ได้";
    const list=$("#discordMembers"); list.replaceChildren();
    const empty=document.createElement("div"); empty.className="discord-empty";
    empty.textContent="ตรวจสอบอินเทอร์เน็ตและการเปิด Server Widget"; list.append(empty);
  }finally{discordBusy=false;}
}
function startDiscordRefresh(){
  refreshDiscord();
  if(discordTimer===null) discordTimer=setInterval(()=>{
    if($("#p3").classList.contains("on")) refreshDiscord();
  },30000);
}
$("#discordJoin").addEventListener("click",()=>api("/api/open_discord",{}).catch(()=>{}));
$("#modeSeg").addEventListener("click",e=>{
  const b=e.target.closest("button"); if(!b) return;
  api("/api/set",{key:"mode",value:b.dataset.mode});
  if(S) S.cfg.mode=b.dataset.mode; renderMode(b.dataset.mode);
});
/* FXBEGIN */
const FX_KINDS=[
  {id:"auto",name:"ตามธีม"},{id:"snow",name:"หิมะตก"},{id:"rain",name:"ฝนตก"},{id:"stars",name:"ดาวระยิบ"},
  {id:"bubbles",name:"ฟองอากาศ"},{id:"fireflies",name:"หิ่งห้อย"},{id:"embers",name:"ประกายไฟ"},
  {id:"petals",name:"กลีบดอกไม้"},{id:"sparkles",name:"ประกายทอง"},{id:"matrix",name:"รหัสดิจิทัล"},{id:"aurora",name:"แสงเหนือ"}];
const FX_NAME=Object.fromEntries(FX_KINDS.map(k=>[k.id,k.name]));
const THEME_FX={violet:"stars",ocean:"bubbles",emerald:"fireflies",sunset:"embers",rose:"petals",crimson:"rain",
  gold:"sparkles",cyber:"matrix",mint:"snow",aurora:"aurora",slate:"rain",amoled:"stars"};
const GLYPHS="01ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ<>/\\|+=*";
const fx={cv:$("#fx"),run:false,kind:"",theme:"",amount:60,parts:[],cols:null,w:0,h:0,rgb:{},raf:0,last:0,t:0,dpr:1,
  shoot:null,nextShoot:0,dirty:false};
const fxx=fx.cv.getContext("2d");
const hex2rgb=h=>{h=String(h||"").trim().replace("#",""); if(h.length===3)h=h.split("").map(c=>c+c).join(""); const n=parseInt(h||"ffffff",16); return [(n>>16)&255,(n>>8)&255,n&255];};
const rgba=(c,a)=>"rgba("+c[0]+","+c[1]+","+c[2]+","+a+")";
const rnd=(a,b)=>a+Math.random()*(b-a);
const glyph=()=>GLYPHS[Math.floor(Math.random()*GLYPHS.length)];
function fxColors(){
  const cs=getComputedStyle(document.documentElement);
  fx.rgb={a1:hex2rgb(cs.getPropertyValue("--a1")),a2:hex2rgb(cs.getPropertyValue("--a2")),
          a3:hex2rgb(cs.getPropertyValue("--a3")),soft:hex2rgb(cs.getPropertyValue("--soft"))};
}
function fxCount(){
  const f=fx.amount/60, area=Math.max(.6,Math.min(2,(fx.w*fx.h)/640000));
  const base={snow:90,rain:110,stars:80,bubbles:34,fireflies:36,embers:60,petals:26,sparkles:38,aurora:46}[fx.kind]||0;
  return Math.max(4,Math.round(base*f*area));
}
function mkCol(i){
  const len=Math.floor(rnd(8,20));
  return {x:i*18+9,y:rnd(-fx.h,0),v:rnd(50,150),len,ch:Array.from({length:len},glyph),
          on:Math.random()<.3+.55*fx.amount/100,wait:rnd(0,3)};
}
function newP(init){
  const w=fx.w,h=fx.h,k=fx.kind,p={ph:rnd(0,6.283),t:0},pick=()=>["a1","a3","soft"][Math.floor(rnd(0,3))];
  switch(k){
    case "snow": p.r=rnd(1,3.4); p.x=rnd(0,w); p.y=init?rnd(0,h):rnd(-20,-2); p.vy=14+p.r*12; break;
    case "rain": p.len=rnd(9,24); p.vy=rnd(460,780); p.x=rnd(-80,w+80); p.y=init?rnd(0,h):-p.len; p.a=rnd(.12,.34); break;
    case "stars": case "aurora": p.x=rnd(0,w); p.y=rnd(0,k==="aurora"?h*.7:h); p.r=rnd(.4,1.5); p.sp=rnd(.6,2.2); p.big=Math.random()<.12; break;
    case "bubbles": p.r=rnd(3,11); p.x=rnd(0,w); p.y=init?rnd(0,h):h+p.r; p.vy=-rnd(14,40); break;
    case "fireflies": p.r=rnd(1.4,2.8); p.x=rnd(0,w); p.y=rnd(0,h); p.ang=rnd(0,6.283); p.sp=rnd(6,20); break;
    case "embers": p.r=rnd(.8,2.4); p.x=rnd(0,w); p.y=init?rnd(0,h):h+4; p.vy=-rnd(26,78); p.vx=rnd(-14,14); p.c=Math.random()<.5?"a1":"a2"; break;
    case "petals": p.s=rnd(4.5,8.5); p.x=rnd(-20,w); p.y=init?rnd(0,h):rnd(-30,-5); p.vy=rnd(18,42); p.rot=rnd(0,6.283); p.vr=rnd(-1.2,1.2); p.c=pick(); break;
    case "sparkles": p.x=rnd(0,w); p.y=rnd(0,h); p.s=rnd(3,9); p.dur=rnd(1.6,3.6); p.t=init?Math.random():0; p.c=pick(); break;
  }
  return p;
}
function fxSeed(){
  fx.parts=[]; fx.shoot=null; fx.cols=null;
  if(!fx.w||!fx.kind) return;
  if(fx.kind==="matrix"){ fx.cols=[]; for(let i=0;i<Math.ceil(fx.w/18);i++) fx.cols.push(mkCol(i)); return; }
  const n=fxCount(); for(let i=0;i<n;i++) fx.parts.push(newP(true));
}
function drawAurora(ctx,t){
  const w=fx.w,h=fx.h,R=fx.rgb,cols=[R.a2,R.a3,R.a1];
  cols.forEach((c,i)=>{
    const base=h*(.16+i*.09),amp=h*(.05+i*.012),f1=.006+i*.0018,sp=.35+i*.15,top=[],bot=[];
    for(let x=0;x<=w+12;x+=12){
      const y=base+Math.sin(x*f1+t*sp+i*2)*amp+Math.sin(x*.013-t*.4+i)*amp*.45;
      const th=h*.12+Math.sin(x*.008+t*.5+i)*h*.04;
      top.push([x,y]); bot.push([x,y+th]);
    }
    ctx.beginPath(); ctx.moveTo(top[0][0],top[0][1]);
    for(const p of top) ctx.lineTo(p[0],p[1]);
    for(let j=bot.length-1;j>=0;j--) ctx.lineTo(bot[j][0],bot[j][1]);
    ctx.closePath();
    const g=ctx.createLinearGradient(0,base-amp,0,base+amp+h*.16);
    g.addColorStop(0,rgba(c,0)); g.addColorStop(.45,rgba(c,.26)); g.addColorStop(1,rgba(c,0));
    ctx.fillStyle=g; ctx.fill();
  });
}
function fxStep(dt){
  const ctx=fxx,w=fx.w,h=fx.h,R=fx.rgb,k=fx.kind;
  ctx.clearRect(0,0,w,h); fx.dirty=true; fx.t+=dt; const t=fx.t;
  ctx.globalCompositeOperation=(k==="rain"||k==="snow"||k==="bubbles"||k==="petals")?"source-over":"lighter";
  if(k==="matrix"&&fx.cols){
    ctx.font="14px monospace"; ctx.textAlign="center";
    for(const c of fx.cols){
      if(!c.on) continue;
      if(c.wait>0){ c.wait-=dt; continue; }
      c.y+=c.v*dt;
      if(c.y-c.len*16>h){ c.y=rnd(-120,0); c.v=rnd(50,150); c.wait=rnd(0,3); }
      if(Math.random()<dt*6) c.ch[Math.floor(Math.random()*c.len)]=glyph();
      for(let j=0;j<c.len;j++){
        const y=c.y-j*16; if(y<-16||y>h+16) continue;
        ctx.fillStyle=j===0?rgba(R.soft,.9):rgba(R.a2,(1-j/c.len)*.55);
        ctx.fillText(c.ch[j],c.x,y);
      }
    }
    return;
  }
  if(k==="aurora") drawAurora(ctx,t);
  for(const p of fx.parts){
    switch(k){
      case "snow":
        p.y+=p.vy*dt; p.x+=Math.sin(t*.8+p.ph)*14*dt;
        if(p.y>h+6||p.x<-10||p.x>w+10) Object.assign(p,newP(false));
        ctx.fillStyle="rgba(235,245,255,"+(.3+p.r*.16)+")"; ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,6.283); ctx.fill(); break;
      case "rain":
        p.y+=p.vy*dt; p.x-=p.vy*.12*dt;
        if(p.y>h+p.len) Object.assign(p,newP(false));
        ctx.strokeStyle=rgba(R.soft,p.a); ctx.lineWidth=1; ctx.beginPath();
        ctx.moveTo(p.x,p.y); ctx.lineTo(p.x+p.len*.12,p.y-p.len); ctx.stroke(); break;
      case "stars": case "aurora": {
        const a=.2+.8*(.5+.5*Math.sin(t*p.sp+p.ph));
        ctx.fillStyle=rgba(p.big?R.a2:R.soft,a); ctx.beginPath(); ctx.arc(p.x,p.y,p.big?p.r*1.8:p.r,0,6.283); ctx.fill(); break; }
      case "bubbles":
        p.y+=p.vy*dt; p.x+=Math.sin(t*1.1+p.ph)*10*dt;
        if(p.y<-p.r-4) Object.assign(p,newP(false));
        ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,6.283); ctx.fillStyle=rgba(R.a2,.07); ctx.fill();
        ctx.strokeStyle=rgba(R.soft,.4); ctx.lineWidth=1; ctx.stroke();
        ctx.beginPath(); ctx.arc(p.x-p.r*.35,p.y-p.r*.35,p.r*.25,0,6.283); ctx.fillStyle=rgba(R.soft,.45); ctx.fill(); break;
      case "fireflies": {
        p.ang+=(Math.random()-.5)*6.6*dt; p.x+=Math.cos(p.ang)*p.sp*dt; p.y+=Math.sin(p.ang)*p.sp*dt;
        if(p.x<-10)p.x=w+10; if(p.x>w+10)p.x=-10; if(p.y<-10)p.y=h+10; if(p.y>h+10)p.y=-10;
        const a=.12+.88*(.5+.5*Math.sin(t*1.3+p.ph)),g=ctx.createRadialGradient(p.x,p.y,0,p.x,p.y,p.r*7);
        g.addColorStop(0,rgba(R.a2,a)); g.addColorStop(.25,rgba(R.a2,a*.35)); g.addColorStop(1,rgba(R.a2,0));
        ctx.fillStyle=g; ctx.beginPath(); ctx.arc(p.x,p.y,p.r*7,0,6.283); ctx.fill(); break; }
      case "embers": {
        p.y+=p.vy*dt; p.x+=(p.vx+Math.sin(t*2+p.ph)*10)*dt;
        if(p.y<-4) Object.assign(p,newP(false));
        const a=Math.max(0,Math.min(1,p.y/h*1.4))*(.65+.35*Math.sin(t*10+p.ph));
        ctx.fillStyle=rgba(R[p.c],a*.18); ctx.beginPath(); ctx.arc(p.x,p.y,p.r*3.2,0,6.283); ctx.fill();
        ctx.fillStyle=rgba(R[p.c],a); ctx.beginPath(); ctx.arc(p.x,p.y,p.r,0,6.283); ctx.fill(); break; }
      case "petals":
        p.y+=p.vy*dt; p.x+=Math.sin(t*.9+p.ph)*20*dt; p.rot+=p.vr*dt;
        if(p.y>h+12) Object.assign(p,newP(false));
        ctx.save(); ctx.translate(p.x,p.y); ctx.rotate(p.rot); ctx.beginPath();
        ctx.ellipse(0,0,p.s,p.s*.55*Math.abs(Math.cos(t*1.4+p.ph))+.8,0,0,6.283);
        ctx.fillStyle=rgba(R[p.c],.55); ctx.fill(); ctx.restore(); break;
      case "sparkles": {
        p.t+=dt/p.dur; if(p.t>=1) Object.assign(p,newP(false));
        const a=Math.sin(Math.PI*Math.min(1,p.t)),s=p.s*a,x=p.x,y=p.y;
        ctx.fillStyle=rgba(R[p.c],.9*a); ctx.beginPath(); ctx.moveTo(x,y-s);
        ctx.quadraticCurveTo(x,y,x+s,y); ctx.quadraticCurveTo(x,y,x,y+s);
        ctx.quadraticCurveTo(x,y,x-s,y); ctx.quadraticCurveTo(x,y,x,y-s); ctx.fill(); break; }
    }
  }
  if(k==="stars"){                                   /* ดาวตกนาน ๆ ครั้ง */
    if(!fx.shoot){
      if(t>fx.nextShoot){ fx.shoot={x:rnd(w*.2,w),y:rnd(0,h*.4),vx:-rnd(380,560),vy:rnd(160,260),life:0}; fx.nextShoot=t+rnd(3.5,8); }
    }else{
      const s=fx.shoot; s.x+=s.vx*dt; s.y+=s.vy*dt; s.life+=dt;
      const a=Math.max(0,1-s.life/1.1),g=ctx.createLinearGradient(s.x,s.y,s.x-s.vx*.18,s.y-s.vy*.18);
      g.addColorStop(0,rgba(R.soft,a)); g.addColorStop(1,rgba(R.soft,0));
      ctx.strokeStyle=g; ctx.lineWidth=1.6; ctx.beginPath(); ctx.moveTo(s.x,s.y); ctx.lineTo(s.x-s.vx*.18,s.y-s.vy*.18); ctx.stroke();
      if(s.life>1.1) fx.shoot=null;
    }
  }
}
function fxFrame(ts){
  fx.raf=0; if(!fx.run) return;
  const el=ts-fx.last;
  if(el>=33){ fx.last=ts; if(!document.hidden) fxStep(Math.min(.1,el/1000)); }   /* ~30 เฟรม/วินาที เบา CPU */
  fx.raf=requestAnimationFrame(fxFrame);
}
function fxStart(){ if(fx.run) return; fx.run=true; fx.last=performance.now(); if(!fx.raf) fx.raf=requestAnimationFrame(fxFrame); }
function fxStop(){ fx.run=false; if(fx.raf){ cancelAnimationFrame(fx.raf); fx.raf=0; } }
function fxClear(){ fxx.clearRect(0,0,fx.w,fx.h); fx.dirty=false; }
function fxResize(){
  const r=fx.cv.getBoundingClientRect(); if(!r.width||!r.height) return;
  fx.dpr=Math.min(window.devicePixelRatio||1,1.5); fx.w=r.width; fx.h=r.height;
  fx.cv.width=Math.round(r.width*fx.dpr); fx.cv.height=Math.round(r.height*fx.dpr);
  fxx.setTransform(fx.dpr,0,0,fx.dpr,0,0); fxSeed();
}
window.addEventListener("resize",()=>{ clearTimeout(fx._rt); fx._rt=setTimeout(fxResize,150); });
function applyFx(c,d){
  const kind=(c.fx_kind&&c.fx_kind!=="auto")?c.fx_kind:(THEME_FX[c.theme]||"stars");
  const want=!!c.fx_on&&!(c.fx_pause&&(d.enabled||d.spam_on));
  if(!fx.w) fxResize();
  if(kind!==fx.kind||c.theme!==fx.theme){ fx.kind=kind; fx.theme=c.theme; fxColors(); fx.amount=c.fx_amount; fxSeed(); fxClear(); }
  else if(c.fx_amount!==fx.amount){ fx.amount=c.fx_amount; fxSeed(); }
  if(want) fxStart();
  else{ fxStop(); if(!c.fx_on&&fx.dirty) fxClear(); }          /* หยุดชั่วคราวตอนบอททำงาน = ค้างภาพไว้ */
}
function buildFx(){
  $("#fxKinds").innerHTML=FX_KINDS.map(k=>'<button class="th" data-fx="'+k.id+'">'+k.name+'</button>').join("");
  $("#fxKinds").addEventListener("click",e=>{
    const b=e.target.closest(".th"); if(!b) return;
    if(S) S.cfg.fx_kind=b.dataset.fx;
    api("/api/set",{key:"fx_kind",value:b.dataset.fx});
  });
  $("#wFx").addEventListener("click",()=>{
    const v=!(S&&S.cfg.fx_on); if(S) S.cfg.fx_on=v; api("/api/set",{key:"fx_on",value:v});
  });
}
function renderFxKinds(c){ $$("#fxKinds .th").forEach(b=>b.classList.toggle("on",b.dataset.fx===(c.fx_kind||"auto"))); $("#wFx").classList.toggle("on",!!c.fx_on); }

/* ---------- พื้นหลังรูป ---------- */
let bgVer=-1;
function applyBg(c,d){
  const on=!!c.bg_on&&!!d.has_bg;
  document.body.classList.toggle("hasbg",on);
  if(on&&bgVer!==c.bg_ver){ bgVer=c.bg_ver; $("#bgimg").style.backgroundImage='url("/bg?t='+TOKEN+'&v='+c.bg_ver+'")'; }
  const st=document.documentElement.style; st.setProperty("--dim",(c.bg_dim/100).toFixed(2)); st.setProperty("--blur",c.bg_blur+"px");
}
$("#bgPick").addEventListener("click",()=>$("#bgFile").click());
$("#bgFile").addEventListener("change",async e=>{
  const f=e.target.files[0]; e.target.value=""; if(!f) return;
  const msg=$("#bgMsg"); msg.textContent="กำลังประมวลผลรูป…";
  try{
    const url=URL.createObjectURL(f);
    const img=await new Promise((res,rej)=>{ const i=new Image(); i.onload=()=>res(i); i.onerror=()=>rej(new Error("อ่านไฟล์รูปไม่ได้")); i.src=url; });
    const sc=Math.min(1,1920/img.naturalWidth,1200/img.naturalHeight);
    const cv=document.createElement("canvas"); cv.width=Math.max(1,Math.round(img.naturalWidth*sc)); cv.height=Math.max(1,Math.round(img.naturalHeight*sc));
    cv.getContext("2d").drawImage(img,0,0,cv.width,cv.height); URL.revokeObjectURL(url);
    const r=await api("/api/bg_upload",{data:cv.toDataURL("image/jpeg",.86)});
    msg.textContent=r.ok?"ตั้งรูปพื้นหลังแล้ว":(r.error||"ตั้งรูปไม่สำเร็จ");
  }catch(err){ msg.textContent=String(err.message||err); }
});
$("#bgClear").addEventListener("click",async()=>{ await api("/api/bg_clear",{}); $("#bgMsg").textContent="ลบรูปพื้นหลังแล้ว"; });
/* ---------- โลโก้ ---------- */
let logoVer=-2;
function applyLogo(c,d){
  const on=!!d.has_logo, el=$(".logo"), v=on?c.logo_ver:-1;
  el.classList.toggle("img",on);
  if(v!==logoVer){ logoVer=v; el.style.background=on?'center/contain no-repeat url("/logo?t='+TOKEN+'&v='+c.logo_ver+'")':""; }
}
/* FXEND */
function renderMode(m){
  const i=MODES.indexOf(m);
  $$("#modeSeg button").forEach(b=>b.classList.toggle("on",b.dataset.mode===m));
  setThumb($("#modeSeg"),i,3);
  $("#cardWeld").classList.toggle("dim",m==="bolt");
  $("#cardBolt").classList.toggle("dim",m==="weld");
}

/* ---------- sliders ---------- */
function buildSliders(){
  $$(".srow").forEach(row=>{
    const {key,label,min,max,step,unit}=row.dataset;
    row.innerHTML=`<div class="shead"><span>${label}</span><span class="val"></span></div>
      <input type="range" min="${min}" max="${max}" step="${step}">`;
    const inp=row.querySelector("input"), val=row.querySelector(".val");
    const paint=()=>{
      inp.style.setProperty("--p",((inp.value-min)/(max-min)*100)+"%");
      val.textContent=inp.value+unit;
    };
    row._paint=paint; row._inp=inp;
    let busy=false;
    inp.addEventListener("input",()=>{
      paint(); if(S) S.cfg[key]=+inp.value;
      if(!busy){busy=true;setTimeout(()=>{busy=false;api("/api/set",{key,value:+inp.value});},60);}
      if(key==="spam_ms") renderRate(+inp.value);
    });
    inp.addEventListener("change",()=>api("/api/set",{key,value:+inp.value}));
    inp.addEventListener("pointerdown",()=>row._drag=true);
    window.addEventListener("pointerup",()=>row._drag=false);
  });
  $$("[data-sw]").forEach(cb=>{
    cb.addEventListener("change",()=>{ if(S) S.cfg[cb.dataset.sw]=cb.checked; api("/api/set",{key:cb.dataset.sw,value:cb.checked}); });
  });
}
function renderRate(ms){ $("#rateText").textContent="≈ "+Math.round(1000/(ms+8))+" ครั้ง/วินาที"; }

/* ---------- keys ---------- */
$$("button.key[data-target]").forEach(b=>b.addEventListener("click",()=>api("/api/capture",{target:b.dataset.target})));
window.addEventListener("keydown",e=>{ if(S&&S.capturing){e.preventDefault();e.stopPropagation();} },true);
$("#power").addEventListener("click",()=>api("/api/toggle",{}));
$("#bigKey").addEventListener("click",()=>api("/api/toggle_spam",{}));
$("#btnReset").addEventListener("click",()=>api("/api/reset",{}));
async function quitApp(){
  try{ await api("/api/quit",{}); }catch(e){}
  winCall("close");
  $("#offline").textContent="ปิดโปรแกรมแล้ว — ปิดหน้าต่างนี้ได้เลย"; $("#offline").classList.add("show");
}
$("#btnQuit").addEventListener("click",quitApp);
$("#wClose").addEventListener("click",quitApp);
$("#wMin").addEventListener("click",()=>winCall("minimize"));
$("#wPin").addEventListener("click",()=>{
  const v=!(S&&S.cfg.topmost); if(S) S.cfg.topmost=v; api("/api/set",{key:"topmost",value:v});
});
$("#clearLog").addEventListener("click",()=>{$("#log").innerHTML="";});
$("#btnOpen").addEventListener("click",()=>api("/api/open_dir",{}));
window.addEventListener("beforeunload",()=>{ navigator.sendBeacon("/api/bye?t="+TOKEN,"{}"); });

/* ---------- เลือกที่จัดเก็บข้อมูล ---------- */
let setupOpen=false, setupFirst=true, pick=null;
const esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const fmtSize=b=>{ const g=b/1073741824; return (g>=100?g.toFixed(0):g.toFixed(1))+" GB"; };
const DRIVE_SVG='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13 7.5 5h9L19 13"/><path d="M7 16.5h.01"/></svg>';

function setPick(p){
  pick=p;
  $("#sPath").textContent=p?p.path:"—";
  $("#sOk").disabled=!p;
  $$("#drives .drive").forEach(el=>el.classList.toggle("sel",!!p&&el.dataset.path===p.path));
}
async function openSetup(first){
  setupOpen=true; setupFirst=first; pick=null;
  $("#sTitle").textContent=first?"ยินดีต้อนรับ":"เปลี่ยนที่จัดเก็บข้อมูล";
  $("#sSub").textContent=first?"เลือกไดรฟ์ที่จะเก็บข้อมูลโปรแกรม เช่น การตั้งค่าต่าง ๆ":"การตั้งค่าปัจจุบันจะถูกย้ายไปที่ใหม่";
  $("#sOk").textContent=first?"เริ่มใช้งาน":"ย้ายไปที่นี่";
  $("#sCancel").style.display=first?"none":"";
  $("#sErr").textContent=(first&&S&&S.setup_error)?S.setup_error:"";
  $("#setup").classList.add("show");
  let list=[];
  try{ list=(await api("/api/drives")).drives||[]; }catch(e){}
  $("#drives").innerHTML=list.map(d=>{
    const used=d.total?Math.round((d.total-d.free)/d.total*100):0;
    return `<button class="drive" data-path="${esc(d.suggest)}">
      <div class="dt"><div class="di">${DRIVE_SVG}</div><div><b>${esc(d.name)}</b><small>${esc(d.kind)}</small></div></div>
      <div class="dbar"><i style="width:${used}%"></i></div>
      <span>ว่าง ${fmtSize(d.free)} จาก ${fmtSize(d.total)}</span></button>`;
  }).join("")||'<div class="note">ไม่พบไดรฟ์ — กด "เลือกโฟลเดอร์เอง…"</div>';
  $$("#drives .drive").forEach((el,i)=>el.addEventListener("click",()=>setPick({path:el.dataset.path})));
  const cur=S&&S.data_dir;
  const pre=list.find(d=>d.suggest===cur)||(first?(list.find(d=>!d.system)||list[0]):null);
  if(pre) setPick({path:pre.suggest}); else if(cur&&!first) setPick({path:cur}); else setPick(null);
}
function closeSetup(){ setupOpen=false; $("#setup").classList.remove("show"); }
$("#sBrowse").addEventListener("click",async()=>{
  $("#sBrowse").disabled=true;
  try{
    const r=await api("/api/browse",{initial:pick?pick.path:""});
    if(r.path){ setPick({path:r.path,custom:true}); $("#sErr").textContent=""; }
  }catch(e){}
  $("#sBrowse").disabled=false;
});
$("#sOk").addEventListener("click",async()=>{
  if(!pick) return;
  $("#sOk").disabled=true; $("#sErr").textContent="";
  let r={ok:false,error:"เชื่อมต่อโปรแกรมไม่ได้"};
  try{ r=await api("/api/setup",{path:pick.path}); }catch(e){}
  if(r.ok){ closeSetup(); } else { $("#sErr").textContent=r.error||"บันทึกไม่สำเร็จ"; $("#sOk").disabled=false; }
});
$("#sCancel").addEventListener("click",closeSetup);
$("#btnChange").addEventListener("click",()=>openSetup(false));

/* ---------- render ---------- */
function addLogs(list){
  if(!list.length) return;
  const box=$("#log");
  for(const l of list){
    const d=document.createElement("div"); if(l.kind!=="info") d.className=l.kind;
    d.innerHTML=`<span class="t">${l.t}</span>`; d.appendChild(document.createTextNode(l.msg)); box.appendChild(d);
  }
  while(box.children.length>120) box.removeChild(box.firstChild);
  box.scrollTop=box.scrollHeight;
}
function render(d){
  const c=d.cfg;
  renderLicense(d.license);
  if(d.needs_setup&&!setupOpen) openSetup(true);
  $("#power").classList.toggle("on",d.enabled);
  const st=$("#stateText"); st.textContent=d.enabled?"กำลังทำงาน":"พร้อมใช้งาน"; st.classList.toggle("ok",d.enabled);
  $("#chipBot").classList.toggle("on",d.enabled);
  $("#bigKey").classList.toggle("on",d.spam_on);
  const kp=pretty(c.spam_key);
  $("#bigKey").textContent=kp;
  $("#bigKey").style.fontSize=kp.length>3?"22px":"52px";
  const sp=$("#spamText"); sp.textContent=c.spam_hold?"โหมดกดค้าง":(d.spam_on?"กำลังรัว":"ปิดอยู่"); sp.classList.toggle("ok",d.spam_on);
  $("#chipSpam").classList.toggle("on",d.spam_on);
  applyTheme(c.theme);
  applyBg(c,d); applyLogo(c,d); applyFx(c,d); renderFxKinds(c);
  $("#wPin").classList.toggle("on",!!c.topmost);
  $$("[data-keyshow]").forEach(el=>el.textContent=pretty(c[el.dataset.keyshow]));
  $$("button.key[data-target]").forEach(el=>{
    const t=el.dataset.target;
    if(d.capturing===t){el.textContent="กดปุ่ม… (Esc ยกเลิก)";el.classList.add("cap");}
    else{el.textContent=pretty(c[t]);el.classList.remove("cap");}
  });
  renderMode(c.mode);
  $$(".srow").forEach(row=>{
    if(row._drag) return;
    const v=c[row.dataset.key]; if(+row._inp.value!==v){row._inp.value=v;} row._paint();
  });
  $$("[data-sw]").forEach(cb=>{ if(document.activeElement!==cb) cb.checked=!!c[cb.dataset.sw]; });
  renderRate(c.spam_ms);
  $("#stWeld").textContent=d.stats.weld; $("#stBolt").textContent=d.stats.bolts; $("#stSpam").textContent=d.stats.spam;
  const dd=d.data_dir||"";
  $("#storePath").textContent=dd||"ยังไม่ได้เลือก";
  $("#storeDrive").textContent=/^[A-Za-z]:/.test(dd)?("ไดรฟ์ "+dd.slice(0,2)):(dd?"โฟลเดอร์ที่เลือก":"—");
  addLogs(d.logs);
}
async function tick(){
  try{
    const d=await api("/api/state?since="+since);
    since=d.last_id; S=d; fails=0; $("#offline").classList.remove("show"); render(d);
  }catch(e){ if(++fails>=4) $("#offline").classList.add("show"); }
  setTimeout(tick,150);
}
$$(".card h2,.loghead>span:first-child,.tile span,.tile b").forEach(e=>e.classList.add("pywebview-drag-region"));
buildThemes(); buildFx(); buildSliders(); setThumb($("#modeSeg"),0,3); tick();
</script>
</body>
</html>
"""


# =====================================================================
def test_image(path):
    full = cv2.imread(path)
    H, W = full.shape[:2]
    scale = H / 1080.0
    x1, y1, x2, y2 = int(CROP[0] * W), int(CROP[1] * H), int(CROP[2] * W), int(CROP[3] * H)
    img = np.ascontiguousarray(full[y1:y2, x1:x2])
    rings = find_bolt_rings(img, scale)
    dots = find_red_dots(img)
    print("วงแหวนน็อต:", [(int(x) + x1, int(y) + y1) for x, y in rings])
    print("จุดแดงเชื่อมเหล็ก:", [(int(x) + x1, int(y) + y1) for x, y in dots])
    paths = build_paths(img, dots, scale) if len(dots) == 4 else None
    if paths:
        for i, p in enumerate(paths):
            print(f"เส้น {i + 1}: {len(p)} จุดหัก")
    save_debug(img, paths=paths, rings=rings, name="debug_test.png")
    print("บันทึก debug_test.png แล้ว")


def make_server(core):
    Handler.core = core
    Handler.token = secrets.token_urlsafe(16)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    Handler.port = srv.server_address[1]
    return srv


class WindowApi:
    """ฟังก์ชันที่หน้า UI เรียกได้ (ปุ่มย่อ/ปิดโปรแกรมในหน้าตั้งค่า)"""
    def __init__(self):
        self._window = None

    def minimize(self):
        if self._window:
            self._window.minimize()

    def close(self):
        if self._window:
            self._window.destroy()

    def _find_hwnd(self):
        """หา handle หน้าต่างหลักของโปรเซสนี้ (ไม่พึ่งชื่อหน้าต่าง)"""
        from ctypes import wintypes
        u = ctypes.windll.user32
        found = []
        pid = os.getpid()
        EnumProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            p = wintypes.DWORD()
            u.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid and u.IsWindowVisible(hwnd) and not u.GetWindow(hwnd, 4):  # 4 = GW_OWNER
                r = wintypes.RECT()
                u.GetWindowRect(hwnd, ctypes.byref(r))
                found.append(((r.right - r.left) * (r.bottom - r.top), hwnd))
            return True
        u.EnumWindows(EnumProc(cb), 0)
        if found:
            return max(found)[1]
        return u.FindWindowW(None, WINDOW_TITLE) or None

    def start_drag(self):
        """ลากหน้าต่างตามเมาส์ขณะกดปุ่มซ้ายค้าง (ทำด้วย Win32 ล้วน ไม่ขึ้นกับ DPI/เวอร์ชัน pywebview)"""
        if os.name != "nt":
            return False
        try:
            from ctypes import wintypes
            u = ctypes.windll.user32
            hwnd = self._find_hwnd()
            if not hwnd:
                return False
            pt = wintypes.POINT()
            rc = wintypes.RECT()
            u.GetCursorPos(ctypes.byref(pt))
            u.GetWindowRect(hwnd, ctypes.byref(rc))
            sx, sy, wx, wy = pt.x, pt.y, rc.left, rc.top
            SWP = 0x0001 | 0x0004 | 0x0010      # NOSIZE | NOZORDER | NOACTIVATE
            t0 = time.time()
            while (u.GetAsyncKeyState(0x01) & 0x8000) and time.time() - t0 < 60:
                u.GetCursorPos(ctypes.byref(pt))
                u.SetWindowPos(hwnd, 0, wx + pt.x - sx, wy + pt.y - sy, 0, 0, SWP)
                time.sleep(0.006)
            return True
        except Exception:
            return False


def run_frameless(url, core):
    """หน้าต่างไร้กรอบด้วย pywebview — ไม่มีแถบขาวของ Edge/Chrome"""
    import webview
    api = WindowApi()
    win = webview.create_window(
        WINDOW_TITLE, url, js_api=api, width=960, height=600, min_size=(820, 520),
        x=40, y=30, frameless=True, easy_drag=False, resizable=True,
        on_top=core.cfg["topmost"], background_color="#06070b")
    api._window = win
    webview.start()      # บล็อกจนกว่าจะปิดหน้าต่าง


def main():
    if os.name == "nt":
        try:
            ctypes.windll.user32.SetProcessDPIAware()   # กันปัญหาสเกลจอ
            ctypes.windll.winmm.timeBeginPeriod(1)      # ให้ sleep แม่นระดับ ~1ms
        except Exception:
            pass
    core = Core()
    core.start(workers=False)
    srv = make_server(core)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    _license_bootstrap(core)
    url = f"http://127.0.0.1:{Handler.port}/?t={Handler.token}"
    print("Auto Minigame กำลังทำงาน — ปิดหน้าต่าง UI หรือกด Ctrl+C เพื่อออก")
    try:
        import webview  # noqa: F401
        have_webview = True
    except Exception:
        have_webview = False
    if have_webview:
        try:
            run_frameless(url, core)
            core.shutdown()
            return
        except KeyboardInterrupt:
            core.shutdown()
        except Exception as e:
            print(f"เปิดหน้าต่างไร้กรอบไม่สำเร็จ ({e}) — ใช้ Edge/Chrome แทน")
    else:
        print("ยังไม่ได้ติดตั้ง pywebview จึงมีแถบหัวหน้าต่างของเบราว์เซอร์ "
              "(ติดตั้งด้วย: python -m pip install pywebview เพื่อเอาแถบนั้นออก)")
    if not launch_ui(url):
        print("ไม่พบ Edge/Chrome แบบแอป เปิดในเบราว์เซอร์ปกติแทน หรือเปิดลิงก์นี้เอง:\n" + url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        core.shutdown()


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        test_image(sys.argv[2])
    else:
        main()      # หน้ากรอกคีย์แสดงใน UI หลักก่อนเปิดใช้งาน
