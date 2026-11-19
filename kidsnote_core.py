
# kidsnote_core.py
# 키즈노트 알림장 이미지 다운로더 - 핵심 로직
# 참고: https://github.com/bestend/kidsnote (kd - 키즈노트 앨범 다운로더)
# 원본 레포의 핵심 아이디어를 가져왔다:
#  1) 비밀번호를 앱이 직접 받지 않는다. 브라우저에서 직접 로그인한다.
#  2) 로그인 후 브라우저를 닫으면 세션(쿠키/스토리지)만 로컬에 저장한다.
#  3) 그 세션으로 목록을 가져오고, 날짜별 폴더로 저장한다.
# 달라진 점:
#  - 대상이 앨범이 아니라 "알림장"이다.
#  - CLI가 아니라 윈도우용 Tkinter GUI이다.
#  - install.sh(리눅스/맥용)가 아니라 run.bat(윈도우용)이다.
#  - 목록이 안 잡혀도 "URL 직접 붙여넣기"로 다운로드할 수 있게 했다.
#
# 키즈노트는 공개 API를 제공하지 않으므로, 이 앱은 공식 웹페이지에
# 로그인한 브라우저 세션을 그대로 재사용한다. 사이트 구조가 바뀌면
# 아래 SELECTOR / URL 후보를 먼저 확인하면 된다.

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional
from urllib.parse import unquote, urljoin, urlparse

import requests

BASE_URL = "https://www.kidsnote.com"
SERVICE_REPORT_URL = "https://www.kidsnote.com/service/report"
KAPI_BASE = "https://kapi.kidsnote.com/v1_2"
# HTML 폴백용 후보 - 이제 기본 경로에서는 쓰지 않는다. API가 1순위다.
REPORT_LIST_URL_CANDIDATES = [SERVICE_REPORT_URL]

# 이미지로 보지 않을 것들 (로고, 아이콘, 프로필, 기본 이미지)
EXCLUDE_KEYWORDS = [
    "logo", "icon", "sprite", "profile", "avatar", "default",
    "placeholder", "blank", "emoji", "badge", "button",
    "kidsnote.com/static", "cdn-cgi",
]

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif", ".bmp")


# ----------------------------------------------------------------------
# 경로 / 파일명
# ----------------------------------------------------------------------

def get_app_dir() -> Path:
    """윈도우: %APPDATA%\\kidsnote-alimjang, 그 외: ~/.config/kidsnote-alimjang"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "kidsnote-alimjang"
    return Path.home() / ".config" / "kidsnote-alimjang"


def get_default_download_dir() -> Path:
    return Path.home() / "Pictures" / "kidsnote-alimjang"


def sanitize_filename(name: str, max_len: int = 80) -> str:
    r"""윈도우에서 못 쓰는 문자 \ / : * ? " < > | 를 제거한다."""
    name = unquote(str(name or "")).strip()
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        name = "untitled"
    return name[:max_len]


def sanitize_folder(name: str) -> str:
    return sanitize_filename(name, max_len=60)


def filename_from_url(url: str, index: int) -> str:
    """URL에서 원본 파일명을 뽑고, 없으면 해시로 만든다."""
    try:
        path = urlparse(url).path
        base = Path(path).name
        base = unquote(base).split("?")[0]
        base = sanitize_filename(base, max_len=100)
        if base and "." in base and len(base) > 4:
            stem = Path(base).stem
            ext = Path(base).suffix.lower()
            if ext in IMAGE_EXTS or ext in (".mp4", ".mov", ".webm", ".m4v"):
                return f"{index:03d}_{stem}{ext}"
    except Exception:
        pass
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:10]
    return f"{index:03d}_{h}.jpg"


# ----------------------------------------------------------------------
# 데이터
# ----------------------------------------------------------------------

@dataclass
class Child:
    id: str
    name: str

    def __str__(self) -> str:
        return self.name


@dataclass
class Report:
    id: str
    title: str
    date: str = ""
    url: str = ""
    child_name: str = ""
    image_count: int = 0
    kind: str = "알림장"
    selected: bool = False
    content: str = ""
    author_name: str = ""
    class_name: str = ""
    child_id: str = ""
    center_id: str = ""
    cls: str = ""
    image_urls: List[str] = field(default_factory=list)
    image_api_dates: List[object] = field(default_factory=list)  # attached_images에서 온 촬영/업로드 날짜 (datetime 또는 None, image_urls와 같은 순서)
    video_url: str = ""
    api_url: str = ""
    def folder_name(self) -> str:
        date_part = self.date.strip() if self.date else "날짜없음"
        title_part = sanitize_folder(self.title) if self.title else "알림장"
        return f"{date_part}_{title_part}"


def _make_report_title(content: str, date_written: str, class_name: str = "") -> str:
    text = (content or "").strip().replace("\r", "")
    first = ""
    for line in text.split("\n"):
        line = line.strip()
        if line:
            first = line
            break
    if not first:
        return f"알림장 {date_written}" if date_written else "알림장"
    if len(first) > 45:
        first = first[:45].rstrip() + "…"
    return first


def _pick_image_url(img: dict) -> str:
    for key in ("original", "large", "large_resize", "small", "small_resize"):
        v = img.get(key)
        if v and isinstance(v, str) and v.startswith("http"):
            return v
    return ""



def _parse_api_datetime(value) -> Optional[object]:
    """키즈노트 API의 날짜 필드를 datetime으로 바꾼다. 형식이 여러 가지라서 넓게 받는다."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            # 초 단위 timestamp (10자리) / 밀리초(13자리) 둘 다 처리
            if value > 1e12:
                value = value / 1000.0
            return datetime.fromtimestamp(float(value))
        except Exception:
            return None
    s = str(value).strip()
    if not s:
        return None
    # ISO8601: 2026-11-06T09:51:00+09:00, 2026-11-06T09:51:00Z, 2026-11-06 09:51:00
    try:
        iso = s.replace("Z", "+00:00")
        if "T" in iso or "-" in iso and ":" in iso:
            dt = datetime.fromisoformat(iso)
            # tz가 있으면 로컬 시간으로 바꿔서 tz 없이 비교하게 한다
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
    except Exception:
        pass
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _extract_image_api_date(img: dict):
    """attached_images 한 장에서 날짜 후보를 찾는다. 키는 서버마다 다를 수 있어서 넓게 본다."""
    if not isinstance(img, dict):
        return None
    # 직접 키
    for key in ("created_at", "created", "date_created", "date", "taken_at", "taken_date", "uploaded_at", "upload_date", "timestamp", "datetime", "date_taken", "shot_at"):
        if img.get(key):
            dt = _parse_api_datetime(img.get(key))
            if dt:
                return dt
    # 중첩된 image / file dict 안에 있을 수도 있다
    for sub_key in ("image", "file", "photo"):
        sub = img.get(sub_key)
        if isinstance(sub, dict):
            for key in ("created_at", "created", "date", "taken_at", "uploaded_at"):
                if sub.get(key):
                    dt = _parse_api_datetime(sub.get(key))
                    if dt:
                        return dt
    return None

def _parse_report_item(item: dict) -> "Report":
    rid = str(item.get("id", ""))
    date_written = str(item.get("date_written") or "")
    content = str(item.get("content") or "")
    child_id = str(item.get("child") or "")
    center_id = str(item.get("center") or "")
    cls = str(item.get("cls") or "")
    child_name = str(item.get("child_name") or "")
    class_name = str(item.get("class_name") or "")
    author_name = str(item.get("author_name") or "")
    if not author_name and isinstance(item.get("author"), dict):
        author_name = str(item["author"].get("name") or "")
    images: List[str] = []
    image_api_dates: List[object] = []
    for img in (item.get("attached_images") or []):
        if isinstance(img, dict):
            u = _pick_image_url(img)
            if u and u not in images:
                images.append(u)
                image_api_dates.append(_extract_image_api_date(img))
    video_url = ""
    av = item.get("attached_video")
    if isinstance(av, dict):
        video_url = str(av.get("original") or av.get("large") or av.get("url") or "")
    elif isinstance(av, str):
        video_url = av
    return Report(
        id=rid, title=_make_report_title(content, date_written, class_name), date=date_written,
        url=SERVICE_REPORT_URL, child_name=child_name, image_count=len(images), kind="알림장",
        content=content, author_name=author_name, class_name=class_name,
        child_id=child_id, center_id=center_id, cls=cls, image_urls=images, image_api_dates=image_api_dates, video_url=video_url,
        api_url=f"{KAPI_BASE}/children/{child_id}/reports/{rid}/" if child_id and rid else "",
    )


@dataclass
class DownloadResult:
    report: Report
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    files: List[Path] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# 세션
# ----------------------------------------------------------------------

class SessionManager:
    """Playwright storage_state + 쿠키를 로컬에만 저장한다. 비밀번호는 저장하지 않는다."""

    def __init__(self, app_dir: Optional[Path] = None):
        self.app_dir = Path(app_dir) if app_dir else get_app_dir()
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.app_dir / "session.json"
        self.meta_file = self.app_dir / "session_meta.json"
        self.api_context_file = self.app_dir / "api_context.json"

    @property
    def has_session(self) -> bool:
        return self.session_file.exists() and self.session_file.stat().st_size > 10

    def save_storage_state(self, storage_state: dict, children: Optional[List[Child]] = None):
        self.session_file.write_text(json.dumps(storage_state, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = {"saved_at": time.strftime("%Y-%m-%d %H:%M:%S"), "children": []}
        if children:
            meta["children"] = [{"id": c.id, "name": c.name} for c in children]
        self.meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_storage_state(self) -> Optional[dict]:
        if not self.has_session:
            return None
        try:
            return json.loads(self.session_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def load_children(self) -> List[Child]:
        if not self.meta_file.exists():
            return []
        try:
            meta = json.loads(self.meta_file.read_text(encoding="utf-8"))
            return [Child(id=str(c.get("id", "")), name=str(c.get("name", ""))) for c in meta.get("children", []) if c.get("name")]
        except Exception:
            return []

    def get_session_info(self) -> dict:
        state = self.load_storage_state()
        if not state:
            return {"has_file": False, "cookie_count": 0, "domains": [], "cookie_names": [], "has_kidsnote_session": False, "kidsnote_domains": []}
        cookies = state.get("cookies", [])
        domains = sorted({c.get("domain", "") for c in cookies})
        names = [c.get("name", "") for c in cookies]
        kidsnote_domains = sorted({c.get("domain", "") for c in cookies if "kidsnote" in (c.get("domain") or "")})
        # 세션 쿠키가 있는지: sessionid 같은 진짜 인증 쿠키만 본다.
        # csrftoken은 토큰이 아니고, _ga/_gid/AMP는 분석용이라 제외한다.
        _sess_names = {"sessionid", "session", "access", "access_token", "refresh_token", "jwt", "id_token", "auth_token", "kidsnote_session"}
        def _is_sess(c):
            n = (c.get("name") or "").lower()
            if "csrf" in n or n in ("_ga", "_gid", "_gat", "amp", "_amp"):
                return False
            if n in _sess_names:
                return True
            # session으로 시작하는 이름 (sessionid 등) - csrf는 위에서 제외됨
            return n.startswith("session") or n.startswith("auth")
        has_sess = any(("kidsnote" in (c.get("domain") or "")) and _is_sess(c) for c in cookies)
        return {"has_file": True, "cookie_count": len(cookies), "domains": domains, "cookie_names": names, "has_kidsnote_session": has_sess, "kidsnote_domains": kidsnote_domains}

        cookies = state.get("cookies", [])
        domains = sorted({c.get("domain", "") for c in cookies})
        names = [c.get("name", "") for c in cookies]
        return {"has_file": True, "cookie_count": len(cookies), "domains": domains, "cookie_names": names}

    def save_api_context(self, ctx: dict):
        try:
            prev: dict = {}
            if self.api_context_file.exists():
                prev = json.loads(self.api_context_file.read_text(encoding="utf-8"))
        except Exception:
            prev = {}
        merged = {**prev, **{k: v for k, v in (ctx or {}).items() if v}}
        try:
            self.api_context_file.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
        return merged

    def load_api_context(self) -> dict:
        try:
            if self.api_context_file.exists():
                data = json.loads(self.api_context_file.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def cookies_for_requests(self) -> dict:
        """requests용 쿠키 dict. Playwright storage_state에서 변환한다."""
        state = self.load_storage_state()
        cookies: dict = {}
        if not state:
            return cookies
        for c in state.get("cookies", []):
            # kidsnote.com 계열 도메인 쿠키만 쓴다
            if "kidsnote" in (c.get("domain") or ""):
                cookies[c["name"]] = c["value"]
        return cookies

    def clear(self):
        for f in (self.session_file, self.meta_file, self.api_context_file):
            try:
                if f.exists():
                    f.unlink()
            except Exception:
                pass


# ----------------------------------------------------------------------
# 이미지 URL 수집 - JS 평가 코드
# 키즈노트 페이지에서 <img>, <video poster>, 배경이미지, 원본 링크를 모은다.
# ----------------------------------------------------------------------

EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const push = (url, w) => {
    if (!url || typeof url !== 'string') return;
    url = url.trim();
    if (!url || url.startsWith('data:') || url.startsWith('blob:')) return;
    if (url.startsWith('//')) url = 'https:' + url;
    if (url.startsWith('/')) url = location.origin + url;
    if (!url.startsWith('http')) return;
    const low = url.toLowerCase();
    // 1x1, svg 아이콘 등은 제외
    if (low.endsWith('.svg')) return;
    if (low.includes('logo') || low.includes('icon') || low.includes('sprite')) return;
    if (low.includes('profile') || low.includes('avatar') || low.includes('default')) return;
    if (seen.has(url)) return;
    seen.add(url);
    out.push({url, w: w || 0});
  };

  // 1) 모든 img
  document.querySelectorAll('img').forEach(img => {
    const w = img.naturalWidth || img.width || 0;
    // 너무 작은 이미지는 아이콘일 확률이 높다
    if (w && w < 80) return;
    const src = img.currentSrc || img.src || img.getAttribute('data-src') || img.getAttribute('data-original');
    push(src, w);
    const srcset = img.getAttribute('srcset') || img.getAttribute('data-srcset');
    if (srcset) {
      // srcset에서 가장 큰 후보를 쓴다
      const parts = srcset.split(',').map(s => s.trim().split(' ')[0]).filter(Boolean);
      if (parts.length) push(parts[parts.length - 1], 9999);
    }
  });

  // 2) 원본 링크 (a href가 이미지인 경우)
  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (/\.(jpe?g|png|webp|gif|heic|heif)(\?|#|$)/i.test(href)) push(href, 9999);
  });

  // 3) video 포스터 / source
  document.querySelectorAll('video').forEach(v => {
    push(v.getAttribute('poster'), 9999);
    v.querySelectorAll('source').forEach(s => push(s.getAttribute('src'), 9999));
  });

  // 4) 배경 이미지 (썸네일 div 등)
  document.querySelectorAll('*').forEach(el => {
    const bg = getComputedStyle(el).backgroundImage;
    if (bg && bg !== 'none' && bg.includes('url(')) {
      const m = bg.match(/url\(["']?(.*?)["']?\)/);
      if (m) push(m[1], el.clientWidth || 0);
    }
  });

  // 제목 / 날짜 추정
  const titleEl = document.querySelector('h1, h2, [class*="title"], [class*="Title"]');
  const title = titleEl ? (titleEl.innerText || '').trim().split('\n')[0] : document.title;
  const bodyText = document.body ? document.body.innerText || '' : '';
  const dateMatch = bodyText.match(/(20\d{2})[.\-\/](\d{1,2})[.\-\/](\d{1,2})/);
  const date = dateMatch ? `${dateMatch[1]}-${dateMatch[2].padStart(2,'0')}-${dateMatch[3].padStart(2,'0')}` : '';

  return {images: out, title: (title || '').slice(0, 100), date};
}
"""

LIST_JS = r"""
() => {
  // 알림장 목록 페이지에서 링크들을 수집한다.
  // 사이트 구조가 바뀌어도 "제목 + 날짜 + 링크" 형태면 대부분 잡힌다.
  const items = [];
  const seen = new Set();
  const dateRe = /(20\d{2})[.\-\/](\d{1,2})[.\-\/](\d{1,2})/;

  document.querySelectorAll('a[href]').forEach(a => {
    const href = a.getAttribute('href') || '';
    if (!href || href === '#' || href.startsWith('javascript:')) return;
    const text = (a.innerText || '').trim().replace(/\s+/g, ' ');
    if (text.length < 2 || text.length > 120) return;
    // 메뉴, 페이지네이션, 로그아웃 등은 제외
    if (/로그아웃|로그인|회원가입|설정|프로필|메뉴|이전|다음|더보기/.test(text)) return;
    const abs = href.startsWith('http') ? href : location.origin + (href.startsWith('/') ? href : '/' + href);
    // 외부 링크는 알림장이 아니다. 푸터의 Google Play / App Store 같은 링크가 섞이는 걸 막는다.
    try { const _u = new URL(abs); if (_u.hostname && !_u.hostname.includes('kidsnote.com')) return; } catch(e) { return; }
    if (/play\.google|apps\.apple|apple\.com\/app|google\s*play|app\s*store/i.test(abs + ' ' + text)) return;
    if (seen.has(abs)) return;
    // 알림장/공지/앨범/보고서 관련 링크를 우선한다
    const low = abs.toLowerCase();
    const isReportLike = /report|diary|notice|album|post|detail|view|board|content|alim/.test(low) || /알림장|공지|앨범/.test(text);
    if (!isReportLike) return;
    seen.add(abs);
    const m = text.match(dateRe);
    const date = m ? `${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}` : '';
    const title = text.replace(dateRe, '').trim() || text;
    items.push({title, date, url: abs, kind: /공지/.test(text) ? '공지' : (/앨범/.test(text) ? '앨범' : '알림장')});
  });
  return items;
}
"""

CHILDREN_JS = r"""
() => {
  const names = [];
  const seen = new Set();
  // 상단 아이 선택 영역, 사이드바 등에서 아이 이름을 찾는다.
  const candidates = document.querySelectorAll('[class*="child"], [class*="kid"], [class*="student"], [class*="profile"], select option, [role="option"]');
  candidates.forEach(el => {
    const t = (el.innerText || el.textContent || '').trim();
    if (t && t.length >= 2 && t.length <= 12 && !/로그인|로그아웃|설정|알림장|공지|앨범|전체/.test(t)) {
      if (!seen.has(t)) { seen.add(t); names.push(t); }
    }
  });
  // 셀렉트 박스 옵션
  document.querySelectorAll('select option').forEach(o => {
    const t = (o.innerText || '').trim();
    if (t && t !== '전체' && !seen.has(t)) { seen.add(t); names.push(t); }
  });
  return names.slice(0, 10);
}
"""


# ----------------------------------------------------------------------
# 브라우저 클라이언트 (Playwright)
# ----------------------------------------------------------------------

class KidsNoteBrowser:
    """로그인한 브라우저 세션으로 알림장 목록/이미지를 가져온다."""

    def __init__(self, session: SessionManager, headless: bool = False):
        self.session = session
        self.headless = headless
        self.last_list_debug: List[str] = []  # 마지막 목록 호출의 진단 로그 (GUI에 뿌린다)

    def _check_playwright(self):
        try:
            import playwright  # noqa
        except ImportError as e:
            raise RuntimeError(
                "Playwright가 설치되지 않았습니다.\n"
                "run.bat을 다시 실행하거나, 아래 명령을 실행하세요:\n"
                "  pip install -r requirements.txt\n"
                "  python -m playwright install chromium"
            ) from e

    def login_interactive(self, on_status: Optional[Callable[[str], None]] = None) -> List[Child]:
        """브라우저를 열고, 로그인 감지 후 알림장 페이지까지 확인한 뒤 저장한다.
        [예전 버그] 예전 코드는 메인 페이지에서 '로그아웃' 글자만 보이면 바로 저장했다.
        그래서 /service/report 에서는 유효하지 않은 세션(쿠키 6개, kapi 인증 없음)이 저장돼도
        앱은 '저장됨'으로 보였다. YouTube 쿠키는 알림장 임베드에서 온 잡쿠키라 무시해도 된다.
        [고친 방식] 로그인 감지 -> 같은 브라우저에서 /service/report 로 이동 -> 로그인 페이지로
        튕기지 않고 kapi 요청이 잡히면 그때 저장한다. 튕기면 저장하지 않고 계속 기다린다.
        """
        self._check_playwright()
        from playwright.sync_api import sync_playwright
        from urllib.parse import urlparse as _up2, parse_qs as _pq2
        def log(msg: str):
            if on_status:
                on_status(msg)
        log("브라우저를 엽니다. 키즈노트에 로그인하세요.")
        log("로그인 후 자동으로 알림장 페이지까지 열어보고 검증한 뒤 저장합니다.")
        log("'알림장 페이지 확인됨'이 뜰 때까지 기다려주세요. 그 전에 닫으면 저장 안 됩니다.")
        children: List[Child] = []
        saved_once = False
        last_cookie_count = -1
        verifying = False
        verify_cooldown_until = 0.0
        api_ctx_verify: dict = {}
        kapi_count_verify: List[int] = [0]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False, args=["--start-maximized"])
            state = self.session.load_storage_state()
            if state:
                context = browser.new_context(storage_state=state)
                log(f"기존 세션({len(state.get('cookies', []))}개 쿠키)으로 브라우저를 열었습니다.")
            else:
                context = browser.new_context()
            page = context.new_page()
            # 검증용 kapi 캡처 (로그인 후 알림장 페이지에서만 의미 있음)
            def _on_resp_verify(resp):
                try:
                    u = resp.url or ""
                    if "kapi.kidsnote.com" not in u:
                        return
                    kapi_count_verify[0] += 1
                    if "/v1_2/children/" in u and "/reports/" in u and resp.status == 200:
                        try:
                            hdrs = resp.request.headers or {}
                            enr = hdrs.get("x-enrollment") or hdrs.get("X-Enrollment") or ""
                            if enr:
                                api_ctx_verify["enrollment"] = str(enr)
                        except Exception:
                            pass
                        try:
                            parsed = _up2(u)
                            qs = _pq2(parsed.query)
                            mm = re.search(r"/children/(\d+)/reports", u)
                            if mm:
                                api_ctx_verify["child_id"] = mm.group(1)
                            if qs.get("center_id"):
                                api_ctx_verify["center_id"] = qs["center_id"][0]
                            if qs.get("cls"):
                                api_ctx_verify["cls"] = qs["cls"][0]
                            if qs.get("child"):
                                api_ctx_verify["child_id"] = qs["child"][0]
                        except Exception:
                            pass
                        try:
                            data = resp.json()
                            for it in (data.get("results") or []):
                                if it.get("child") and it.get("child_name"):
                                    api_ctx_verify["child_id"] = str(it.get("child"))
                                    api_ctx_verify["child_name"] = str(it.get("child_name"))
                                if it.get("center"):
                                    api_ctx_verify["center_id"] = str(it.get("center"))
                                if it.get("cls"):
                                    api_ctx_verify["cls"] = str(it.get("cls"))
                        except Exception:
                            pass
                except Exception:
                    pass
            try:
                page.on("response", _on_resp_verify)
            except Exception:
                pass
            try:
                page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception as e:
                log(f"페이지 열기 중 오류 (무시하고 계속): {e}")
            while True:
                try:
                    if not browser.is_connected():
                        log("브라우저가 닫혔습니다.")
                        break
                    if not context.pages:
                        log("브라우저 페이지가 모두 닫혔습니다.")
                        break
                except Exception:
                    break
                # 사용자가 새 탭/팝업에서 로그인했을 수 있으니 항상 마지막 페이지를 본다
                try:
                    active = context.pages[-1] if context.pages else page
                except Exception:
                    active = page
                try:
                    cookies = context.cookies()
                    if len(cookies) != last_cookie_count:
                        last_cookie_count = len(cookies)
                        domains = sorted({c.get("domain", "") for c in cookies})
                        kids = [d for d in domains if "kidsnote" in d]
                        log(f"쿠키 {len(cookies)}개 확인 중... kidsnote 도메인: {', '.join(kids) if kids else '(없음 - 아직 로그인 안 됨)'} (YouTube 쿠키는 무시해도 됩니다)")
                    is_logged = False
                    reason = ""
                    try:
                        body_text = active.evaluate("() => (document.body ? document.body.innerText : '')") or ""
                        if ("로그아웃" in body_text) or ("마이페이지" in body_text and "로그인" not in body_text):
                            is_logged = True
                            reason = "페이지에 '로그아웃' 확인됨"
                    except Exception:
                        pass
                    if not is_logged:
                        for c in cookies:
                            name = (c.get("name") or "").lower()
                            val = c.get("value") or ""
                            _n = (c.get("name") or "").lower()
                            _is_sess2 = ("csrf" not in _n) and (_n in ("sessionid", "session", "access", "access_token", "refresh_token", "jwt", "id_token", "auth_token") or _n.startswith("session") or _n.startswith("auth"))
                            if "kidsnote" in (c.get("domain") or "") and len(val) >= 10 and _is_sess2:
                                is_logged = True
                                reason = f"로그인 쿠키 확인됨 ({c.get('name')})"
                                break
                    # 로그인 감지됐는데 아직 검증 안 했고, 쿨다운도 지났으면 검증 단계로
                    if is_logged and not saved_once and not verifying and time.time() >= verify_cooldown_until:
                        verifying = True
                        log(f"로그인 감지됨 ({reason}) - 알림장 페이지({SERVICE_REPORT_URL})에서도 확인 중...")
                        kapi_count_verify[0] = 0
                        api_ctx_verify.clear()
                        try:
                            active.goto(SERVICE_REPORT_URL, wait_until="domcontentloaded", timeout=30000)
                            active.wait_for_timeout(3000)
                            final_url = active.url or ""
                            body2 = active.evaluate("() => (document.body ? document.body.innerText : '')") or ""
                            is_login_page = ("login" in final_url.lower() or "signin" in final_url.lower() or ("로그인" in body2 and "로그아웃" not in body2))
                            log(f"알림장 페이지 최종 URL: {final_url}")
                            log(f"알림장 페이지에서 kapi 요청 {kapi_count_verify[0]}개 확인됨")
                            if is_login_page:
                                log("❌ 알림장 페이지에서 다시 로그인 화면이 뜹니다. 아직 저장하지 않았습니다.")
                                log("→ 알림장 페이지에서도 로그인해주세요. 로그인되면 다시 자동으로 검증합니다.")
                                verifying = False
                                verify_cooldown_until = time.time() + 5
                            else:
                                storage = context.storage_state()
                                self.session.save_storage_state(storage, children=children)
                                if api_ctx_verify:
                                    try:
                                        self.session.save_api_context(api_ctx_verify)
                                    except Exception:
                                        pass
                                saved_once = True
                                verifying = False
                                log(f"✅ 알림장 페이지 확인됨 - 세션 저장 완료! (쿠키 {len(storage.get('cookies', []))}개, kapi {kapi_count_verify[0]}개)")
                                log("이제 브라우저를 닫아도 됩니다.")
                        except Exception as e:
                            log(f"알림장 페이지 검증 중 오류: {e} - 계속 기다립니다")
                            verifying = False
                            verify_cooldown_until = time.time() + 3
                except Exception:
                    pass
                time.sleep(1)
            if not saved_once:
                log("❌ 검증된 세션이 저장되지 않았습니다. '알림장 페이지 확인됨'이 떴는지 확인하고, 안 떴으면 다시 로그인해서 알림장 페이지까지 들어가주세요.")
            try:
                browser.close()
            except Exception:
                pass
        return children

    def verify_session(self, on_status: Optional[Callable[[str], None]] = None) -> dict:
        """저장된 세션으로 /service/report 를 headless로 열어본다. 로그인 페이지로 튕기는지 확인한다."""
        self._check_playwright()
        from playwright.sync_api import sync_playwright
        def log(msg: str):
            if on_status:
                on_status(msg)
        if not self.session.has_session:
            return {"ok": False, "reason": "저장된 세션 파일이 없습니다", "final_url": "", "kapi_requests": 0, "reports": 0}
        kapi_reqs: List[str] = []
        reports_count = [0]
        api_ctx: dict = {}
        final_url = ""
        title = ""
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(storage_state=self.session.load_storage_state())
                page = ctx.new_page()
                def _on_req(req):
                    try:
                        if "kapi.kidsnote.com" in (req.url or ""):
                            kapi_reqs.append(req.url or "")
                    except Exception:
                        pass
                def _on_resp(resp):
                    try:
                        u = resp.url or ""
                        if "/v1_2/children/" in u and "/reports/" in u and resp.status == 200:
                            try:
                                d = resp.json()
                                if isinstance(d, dict) and "results" in d:
                                    reports_count[0] = max(reports_count[0], len(d.get("results") or []))
                            except Exception:
                                pass
                    except Exception:
                        pass
                page.on("request", _on_req)
                page.on("response", _on_resp)
                page.goto(SERVICE_REPORT_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                final_url = page.url or ""
                try:
                    title = page.title() or ""
                except Exception:
                    title = ""
                try:
                    body = page.evaluate("() => (document.body ? document.body.innerText : '')") or ""
                except Exception:
                    body = ""
                is_login = ("login" in final_url.lower() or "signin" in final_url.lower() or ("로그인" in body and "로그아웃" not in body))
            finally:
                browser.close()
        ok = (not is_login) and (len(kapi_reqs) > 0 or reports_count[0] > 0)
        # kapi 요청이 0개인데 로그인 페이지가 아니면, 아직 스크롤 전이라 0개일 수 있음 - 로그인 여부만으로 판단
        if is_login:
            ok = False
            reason = "알림장 페이지가 로그인 페이지로 튕겼습니다 - 세션이 유효하지 않습니다. 다시 로그인하세요."
        elif len(kapi_reqs) == 0 and reports_count[0] == 0:
            ok = False
            reason = "알림장 페이지는 열렸는데 kapi 요청이 0개입니다. 페이지가 아직 로딩 중이거나 세션이 만료됐을 수 있습니다."
        else:
            reason = "알림장 페이지 확인됨"
        log(f"[검증] 최종 URL: {final_url}")
        log(f"[검증] 제목: {title}")
        log(f"[검증] kapi 요청 {len(kapi_reqs)}개, reports 결과 최대 {reports_count[0]}건")
        log(f"[검증] {'✅ ' + reason if ok else '❌ ' + reason}")
        return {"ok": ok, "reason": reason, "final_url": final_url, "title": title, "kapi_requests": len(kapi_reqs), "reports": reports_count[0], "is_login_page": is_login}



    def _new_context(self, playwright):
        state = self.session.load_storage_state()
        if state:
            return playwright.chromium.launch(headless=self.headless).new_context(storage_state=state)
        return playwright.chromium.launch(headless=self.headless).new_context()

    def fetch_children(self) -> List[Child]:
        """아이 목록. API에서 온 child/child_name을 우선 쓴다."""
        cached = self.session.load_children()
        if cached and any(c.id.isdigit() for c in cached):
            return cached
        ctx = self.session.load_api_context()
        if ctx.get("child_id") and ctx.get("child_name"):
            ch = [Child(id=str(ctx["child_id"]), name=str(ctx["child_name"]))]
            try:
                state = self.session.load_storage_state()
                if state:
                    self.session.save_storage_state(state, children=ch)
            except Exception:
                pass
            return ch
        if not self.session.has_session:
            return []
        self._check_playwright()
        from playwright.sync_api import sync_playwright
        found: dict = {}
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx2 = browser.new_context(storage_state=self.session.load_storage_state())
                page = ctx2.new_page()
                def _on_resp(resp):
                    try:
                        url = resp.url or ""
                        if "/v1_2/children/" in url and "/reports/" in url and resp.status == 200:
                            data = resp.json()
                            for it in (data.get("results") or []):
                                cid = str(it.get("child") or "")
                                cname = str(it.get("child_name") or "")
                                if cid and cname and cid not in found:
                                    found[cid] = cname
                    except Exception:
                        pass
                page.on("response", _on_resp)
                page.goto(SERVICE_REPORT_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
            finally:
                browser.close()
        children: List[Child] = [Child(id=cid, name=cname) for cid, cname in found.items()]
        if children:
            try:
                state = self.session.load_storage_state()
                if state:
                    self.session.save_storage_state(state, children=children)
            except Exception:
                pass
        return children

    def _fetch_reports_via_requests(self, child_id: str, center_id: str = "", cls: str = "", enrollment: str = "", page_size: int = 50, limit: int = 100, keyword: str = "") -> List[Report]:
        """requests로 API를 직접 호출한다. next는 커서 토큰 -> ?cursor=<next> 로 넘긴다."""
        cookies = self.session.cookies_for_requests()
        headers = {
            "accept": "application/json, text/plain, */*",
            "accept-language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
            "origin": "https://www.kidsnote.com",
            "referer": "https://www.kidsnote.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        }
        if enrollment:
            headers["x-enrollment"] = str(enrollment)
        s = requests.Session()
        s.headers.update(headers)
        if cookies:
            s.cookies.update(cookies)
        url = f"{KAPI_BASE}/children/{child_id}/reports/"
        params: dict = {"page_size": str(page_size), "tz": "Asia/Seoul", "child": str(child_id)}
        if center_id:
            params["center_id"] = str(center_id)
        if cls:
            params["cls"] = str(cls)
        out: List[Report] = []
        seen: set = set()
        seen_cursors: set = set()
        for _ in range(30):
            if len(out) >= limit:
                break
            resp = s.get(url, params=params, timeout=30)
            if resp.status_code in (401, 403):
                raise RuntimeError(f"API 인증 실패 HTTP {resp.status_code}. 세션이 만료됐거나 enrollment가 없습니다. 다시 로그인하세요.")
            if resp.status_code != 200:
                raise RuntimeError(f"API 오류 HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            for it in (data.get("results") or []):
                rep = _parse_report_item(it)
                if rep.id in seen:
                    continue
                seen.add(rep.id)
                if keyword and keyword not in rep.title and keyword not in rep.content and keyword not in rep.child_name and keyword not in rep.date:
                    continue
                out.append(rep)
                if len(out) >= limit:
                    break
            nxt = data.get("next")
            if not nxt:
                break
            if nxt in seen_cursors:
                break
            seen_cursors.add(nxt)
            params = dict(params)
            params["cursor"] = nxt
        return out

    def _fetch_single_report_via_requests(self, report_id: str, child_id: str = "", center_id: str = "", cls: str = "", enrollment: str = "") -> Optional[Report]:
        ctx = self.session.load_api_context()
        child_id = child_id or str(ctx.get("child_id") or "")
        if not child_id:
            return None
        cookies = self.session.cookies_for_requests()
        headers = {
            "accept": "application/json, text/plain, */*",
            "origin": "https://www.kidsnote.com",
            "referer": "https://www.kidsnote.com/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        }
        enr = enrollment or str(ctx.get("enrollment") or "")
        if enr:
            headers["x-enrollment"] = enr
        s = requests.Session()
        s.headers.update(headers)
        if cookies:
            s.cookies.update(cookies)
        url = f"{KAPI_BASE}/children/{child_id}/reports/{report_id}/"
        resp = s.get(url, timeout=30)
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except Exception:
            return None
        if isinstance(data, dict) and data.get("id"):
            return _parse_report_item(data)
        return None


    def _scroll_to_bottom(self, page, max_scrolls: int = 25):
        prev = -1
        for _ in range(max_scrolls):
            h = page.evaluate("() => document.body.scrollHeight")
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(700)
            # lazy-load 이미지가 로드될 시간
            page.wait_for_timeout(300)
            new_h = page.evaluate("() => document.body.scrollHeight")
            if new_h == prev or new_h == h and _ > 3:
                # 한 번 더 확인하고 끝낸다
                page.wait_for_timeout(500)
                if page.evaluate("() => document.body.scrollHeight") == new_h:
                    break
            prev = new_h

    def list_reports(self, keyword: str = "", limit: int = 100, child_id: str = "", on_status: Optional[Callable[[str], None]] = None) -> List[Report]:
        """알림장 목록을 API로만 가져온다. HTML 폴백은 쓰지 않는다.
        왜? HTML 폴백이 푸터의 Google Play / App Store 같은 외부 링크를
        알림장으로 오인해서 제목에 'Google Play'가 뜨는 원인이었다.
        순서:
          1순위: 저장된 api_context로 requests 직접 호출 (가장 빠름, 브라우저 안 뜸)
          2순위: 브라우저로 /service/report 열고, kapi reports 응답을 가로챈다.
                 이때 모든 kapi 요청도 같이 기록해서 왜 0건인지 진단한다.
          3순위: 둘 다 0건이면 빈 리스트 + 진단 로그를 남긴다. HTML로 메우지 않는다.
        반환되는 Report에는 image_urls가 이미 들어있다.
        """
        if not self.session.has_session:
            raise RuntimeError("먼저 로그인하세요. 세션이 없습니다.")
        self._check_playwright()
        from playwright.sync_api import sync_playwright
        from urllib.parse import urlparse as _up, parse_qs as _pq
        keyword = (keyword or "").strip()
        debug: List[str] = []
        def log(msg: str):
            debug.append(msg)
            if on_status:
                try:
                    on_status(msg)
                except Exception:
                    pass
        self.last_list_debug = debug
        # --- 1순위: 직접 API ---
        saved = self.session.load_api_context()
        use_child = (child_id or str(saved.get("child_id") or "")).strip()
        log(f"[목록] 1순위 직접 API 시도 - child_id={'있음' if use_child else '없음'}, center={'있음' if saved.get('center_id') else '없음'}, cls={'있음' if saved.get('cls') else '없음'}, enrollment={'있음' if saved.get('enrollment') else '없음'}")
        if use_child:
            try:
                direct = self._fetch_reports_via_requests(
                    child_id=use_child,
                    center_id=str(saved.get("center_id") or ""),
                    cls=str(saved.get("cls") or ""),
                    enrollment=str(saved.get("enrollment") or ""),
                    page_size=50, limit=limit, keyword=keyword,
                )
                log(f"[목록] 1순위 직접 API 결과: {len(direct)}건")
                if direct:
                    return direct
                log("[목록] 1순위에서 0건 - 브라우저 캡처(2순위)로 넘어갑니다")
            except Exception as e:
                log(f"[목록] 1순위 직접 API 실패: {e}")
        else:
            log("[목록] 저장된 api_context에 child_id가 없어 1순위를 건너뜁니다. 2순위로 파라미터를 찾습니다")
        # --- 2순위: 브라우저 캡처 ---
        results: dict = {}
        api_ctx: dict = {}
        kapi_requests: List[str] = []
        kapi_responses: List[str] = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(storage_state=self.session.load_storage_state())
                page = ctx.new_page()
                def _on_request(req):
                    try:
                        u = req.url or ""
                        if "kapi.kidsnote.com" in u:
                            # 값(아이디)은 로그에 안 남기고, 경로 + 파라미터 이름만 남긴다
                            parsed = _up(u)
                            qs = _pq(parsed.query)
                            kapi_requests.append(f"{parsed.path} ? {','.join(sorted(qs.keys()))}")
                    except Exception:
                        pass
                def _on_response(resp):
                    try:
                        url = resp.url or ""
                        if "kapi.kidsnote.com" not in url:
                            return
                        parsed = _up(url)
                        kapi_responses.append(f"{parsed.path} -> HTTP {resp.status}")
                        if "/v1_2/children/" not in url or "/reports/" not in url:
                            return
                        if resp.status != 200:
                            return
                        data = resp.json()
                        if not isinstance(data, dict) or "results" not in data:
                            return
                        try:
                            req_headers = resp.request.headers or {}
                            enr = req_headers.get("x-enrollment") or req_headers.get("X-Enrollment") or ""
                            if enr:
                                api_ctx["enrollment"] = str(enr)
                        except Exception:
                            pass
                        try:
                            qs = _pq(parsed.query)
                            mm = re.search(r"/children/(\d+)/reports", url)
                            if mm:
                                api_ctx["child_id"] = mm.group(1)
                            if qs.get("center_id"):
                                api_ctx["center_id"] = qs["center_id"][0]
                            if qs.get("cls"):
                                api_ctx["cls"] = qs["cls"][0]
                            if qs.get("child"):
                                api_ctx["child_id"] = qs["child"][0]
                        except Exception:
                            pass
                        for it in (data.get("results") or []):
                            try:
                                rep = _parse_report_item(it)
                            except Exception:
                                continue
                            if rep.id and rep.id not in results:
                                results[rep.id] = rep
                            if rep.child_id and rep.child_name:
                                api_ctx["child_id"] = rep.child_id
                                api_ctx["child_name"] = rep.child_name
                            if rep.center_id:
                                api_ctx["center_id"] = rep.center_id
                            if rep.cls:
                                api_ctx["cls"] = rep.cls
                    except Exception:
                        pass
                page.on("request", _on_request)
                page.on("response", _on_response)
                log(f"[목록] 2순위 브라우저로 {SERVICE_REPORT_URL} 여는 중...")
                page.goto(SERVICE_REPORT_URL, wait_until="domcontentloaded", timeout=30000)
                log(f"[목록] 열린 후 최종 URL: {page.url}")
                log(f"[목록] 페이지 제목: {page.title()}")
                page.wait_for_timeout(2500)
                stall = 0
                for _ in range(30):
                    if len(results) >= limit:
                        break
                    prev = len(results)
                    try:
                        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    except Exception:
                        break
                    page.wait_for_timeout(1600)
                    if len(results) == prev:
                        stall += 1
                        if stall >= 3:
                            break
                    else:
                        stall = 0
                # localStorage 키만 확인 (값은 안 찍는다)
                try:
                    keys = page.evaluate("() => Object.keys(localStorage)") or []
                    log(f"[목록] localStorage 키 {len(keys)}개: {', '.join(keys[:20])}")
                except Exception as e:
                    log(f"[목록] localStorage 확인 실패: {e}")
            finally:
                browser.close()
        log(f"[목록] 2순위 캡처: kapi 요청 {len(kapi_requests)}개, kapi 응답 {len(kapi_responses)}개, reports 결과 {len(results)}건")
        for r in kapi_requests[:10]:
            log(f"[목록]  kapi 요청: {r}")
        for r in kapi_responses[:10]:
            log(f"[목록]  kapi 응답: {r}")
        if api_ctx:
            try:
                self.session.save_api_context(api_ctx)
                log("[목록] api_context 저장됨 (child/center/cls/enrollment)")
            except Exception as e:
                log(f"[목록] api_context 저장 실패: {e}")
        filtered: List[Report] = []
        for rep in results.values():
            if keyword and keyword not in rep.title and keyword not in rep.content and keyword not in rep.child_name and keyword not in rep.date:
                continue
            filtered.append(rep)
        filtered.sort(key=lambda r: (r.date, r.id), reverse=True)
        if filtered:
            log(f"[목록] 최종 {len(filtered)}건 반환 (API)")
            return filtered[:limit]
        log("[목록] 최종 0건. HTML 폴백은 사용하지 않습니다 (Google Play 같은 외부 링크가 섞이는 걸 막기 위해).")
        log("[목록] 다음을 확인하세요: 1) 브라우저에서 /service/report 에 들어가면 알림장이 보이는지, 2) 위 kapi 요청이 0개면 세션이 만료됐을 수 있음 -> 다시 로그인, 3) kapi 응답이 401/403이면 enrollment/세션 문제")
        return []


    def get_report_images(self, report: Report, include_video: bool = False) -> tuple[Report, List[str]]:
        """1순위: list_reports에서 채워진 image_urls. 2순위: API 단건. 3순위: HTML 폴백."""
        if getattr(report, "image_urls", None):
            imgs = list(report.image_urls)
            if include_video and getattr(report, "video_url", ""):
                imgs.append(report.video_url)
            if not include_video:
                imgs = [u for u in imgs if not u.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".m4v"))]
            return report, imgs
        rid = (report.id or "").strip()
        if not rid.isdigit():
            mm = re.search(r"/reports/(\d+)", report.url or "")
            if mm:
                rid = mm.group(1)
        if rid.isdigit():
            ctx = self.session.load_api_context()
            try:
                single = self._fetch_single_report_via_requests(
                    report_id=rid,
                    child_id=report.child_id or str(ctx.get("child_id") or ""),
                    center_id=report.center_id or str(ctx.get("center_id") or ""),
                    cls=report.cls or str(ctx.get("cls") or ""),
                    enrollment=str(ctx.get("enrollment") or ""),
                )
            except Exception:
                single = None
            if single is not None:
                report.title = single.title
                report.date = single.date
                report.content = single.content
                report.image_urls = list(single.image_urls)
                report.image_api_dates = list(getattr(single, "image_api_dates", []) or [])
                report.video_url = single.video_url
                report.image_count = len(single.image_urls)
                imgs = list(single.image_urls)
                if include_video and single.video_url:
                    imgs.append(single.video_url)
                if not include_video:
                    imgs = [u for u in imgs if not u.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".m4v"))]
                return report, imgs
            if (report.url or "") == SERVICE_REPORT_URL:
                raise RuntimeError(f"알림장 {rid} 단건 조회에 실패했습니다. 목록에서 다시 선택하거나, 세션을 다시 로그인하세요.")
        if not self.session.has_session:
            raise RuntimeError("먼저 로그인하세요. 세션이 없습니다.")
        self._check_playwright()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx2 = browser.new_context(storage_state=self.session.load_storage_state())
                page = ctx2.new_page()
                page.goto(report.url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1500)
                self._scroll_to_bottom(page, max_scrolls=30)
                data = page.evaluate(EXTRACT_JS) or {}
                images = [x["url"] for x in (data.get("images") or [])]
                if not include_video:
                    images = [u for u in images if not u.lower().split("?")[0].endswith((".mp4", ".mov", ".webm", ".m4v"))]
                if data.get("title"):
                    if len(data["title"]) <= 100 and "키즈노트" not in data["title"]:
                        report.title = data["title"]
                if data.get("date"):
                    report.date = data["date"]
                return report, images
            finally:
                browser.close()

    def get_images_for_urls(self, urls: List[str], include_video: bool = False) -> List[tuple[Report, List[str]]]:
        out = []
        for url in urls:
            url = url.strip()
            if not url:
                continue
            if url.isdigit():
                rep = Report(id=url, title=f"알림장 {url}", url=SERVICE_REPORT_URL)
            else:
                mm = re.search(r"/reports/(\d+)", url)
                if mm:
                    rep = Report(id=mm.group(1), title=f"알림장 {mm.group(1)}", url=url)
                elif url == SERVICE_REPORT_URL or url.rstrip("/") == SERVICE_REPORT_URL:
                    rep = Report(id="", title="실패: 목록 URL만으로는 알림장을 특정할 수 없습니다. 목록에서 선택하거나 알림장 ID(숫자)를 입력하세요.", url=url)
                    out.append((rep, []))
                    continue
                else:
                    rep = Report(id=hashlib.md5(url.encode()).hexdigest()[:12], title="URL로 가져온 알림장", url=url)
            try:
                rep2, imgs = self.get_report_images(rep, include_video=include_video)
                out.append((rep2, imgs))
            except Exception as e:
                out.append((rep, []))
                rep.title = f"실패: {e}"
        return out


# ----------------------------------------------------------------------
# 다운로드
# ----------------------------------------------------------------------

def download_images_for_report(
    report: Report,
    image_urls: List[str],
    dest_root: Path,
    session: SessionManager,
    *,
    organize_by_date: bool = True,
    skip_existing: bool = True,
    include_video: bool = False,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
) -> DownloadResult:
    """이미지 URL 목록을 폴더에 저장한다. 폴더: <dest>/<아이>/<날짜_제목>/"""
    result = DownloadResult(report=report)
    if not image_urls:
        return result

    if organize_by_date:
        dest = Path(dest_root)
        if report.child_name:
            dest = dest / sanitize_folder(report.child_name)
        dest = dest / report.folder_name()
    else:
        dest = Path(dest_root)
    dest.mkdir(parents=True, exist_ok=True)

    cookies = session.cookies_for_requests()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Referer": report.url or BASE_URL,
    }

    s = requests.Session()
    s.headers.update(headers)
    if cookies:
        s.cookies.update(cookies)

    total = len(image_urls)
    for idx, url in enumerate(image_urls, start=1):
        fname = filename_from_url(url, idx)
        fpath = dest / fname
        if on_progress:
            on_progress(idx, total, fname)

        if skip_existing and fpath.exists() and fpath.stat().st_size > 0:
            result.skipped += 1
            result.files.append(fpath)
            continue

        ok = False
        last_err = ""
        for attempt in range(3):
            try:
                resp = s.get(url, timeout=30, stream=True)
                if resp.status_code == 200:
                    # content-type이 이미지가 아니면 확장자를 보정한다
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                    if "image" not in ctype and "video" not in ctype and "octet-stream" not in ctype:
                        # HTML 로그인 페이지가 온 경우 = 세션 만료
                        if "text/html" in ctype:
                            raise RuntimeError("세션이 만료된 것 같습니다. 다시 로그인하세요.")
                    with open(fpath, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    if fpath.stat().st_size == 0:
                        fpath.unlink(missing_ok=True)
                        raise RuntimeError("빈 파일이 내려받아졌습니다.")
                    # 키즈노트 API 날짜가 있으면, 파일 수정 시간을 그 날짜로 맞춰둔다.
                    # 그래야 나중에 단독 rename_photos.py로 돌려도 다운로드 시간이 아니라 촬영/업로드 시간으로 바뀐다.
                    try:
                        _api_dates = getattr(report, "image_api_dates", None) or []
                        # idx는 1부터 시작, image_urls 순서와 같다
                        if 0 <= idx - 1 < len(_api_dates):
                            _adt = _api_dates[idx - 1]
                            if isinstance(_adt, datetime):
                                _ts = _adt.timestamp()
                                os.utime(fpath, (_ts, _ts))
                    except Exception:
                        pass
                    ok = True
                    break
                elif resp.status_code in (403, 404):
                    last_err = f"HTTP {resp.status_code}"
                    break
                else:
                    last_err = f"HTTP {resp.status_code}"
                    time.sleep(1 + attempt)
            except Exception as e:
                last_err = str(e)
                time.sleep(1 + attempt)
        if ok:
            result.downloaded += 1
            result.files.append(fpath)
        else:
            result.failed += 1
            result.errors.append(f"{fname}: {last_err}")
    return result


# ----------------------------------------------------------------------
# 사진 이름 자동 변경 - rename_photos.py --real 과 동일한 규칙
#  - 대상: 해당 폴더 바로 안의 파일만 (하위 폴더는 안 건드림)
#    .jpg / .jpeg / .png / .heic / .heif / .webp / .tiff 만 변경 (.gif/.mp4 등은 그대로)
#  - 새 이름: EXIF 촬영일(DateTimeOriginal -> DateTime)이 있으면 그걸로,
#    없으면 파일 수정 시간으로 YYYYMMDD_HHMMSS + 확장자
#  - 중복: 같은 시간이면 _1, _2 붙임 (예: 20260512_143210_1.jpg)
#  - rename_photos.py 단독 실행: python.exe rename_photos.py <target_dir> --real
#    앱에서는 이 함수를 다운로드가 끝난 알림장 폴더마다 --real 과 똑같이 부른다.
# ----------------------------------------------------------------------
RENAME_SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".tiff"}


def _inspect_exif_for_rename(image_path: Path):
    """EXIF를 자세히 들여다본다. 반환: (taken_date or None, reason, tag_count, tag_names)
    reason: 'EXIF' / 'Pillow 없음' / 'EXIF 없음' / 'EXIF 읽기 실패: ...'
    """
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
    except Exception as e:
        return None, "Pillow 없음", 0, []
    try:
        with Image.open(image_path) as img:
            exif_data = None
            try:
                # 신버전 API 먼저, 안 되면 구버전
                exif_data = img.getexif()
                if exif_data is not None and len(exif_data) == 0:
                    try:
                        exif_data = img._getexif()
                    except Exception:
                        pass
            except Exception:
                try:
                    exif_data = img._getexif()
                except Exception:
                    exif_data = None
            if not exif_data:
                return None, "EXIF 없음", 0, []
            tag_names = []
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                tag_names.append(str(tag))
                if tag in ("DateTimeOriginal", "DateTime"):
                    try:
                        dt = datetime.strptime(str(value), "%Y:%m:%d %H:%M:%S")
                        return dt, "EXIF", len(exif_data), tag_names
                    except Exception:
                        continue
            return None, "EXIF 없음 (DateTimeOriginal/DateTime 태그 없음)", len(exif_data), tag_names
    except Exception as e:
        return None, f"EXIF 읽기 실패: {e}", 0, []


def _get_taken_date_for_rename(image_path: Path):
    """예전 호환용: EXIF에서 촬영일만 반환, 없으면 None."""
    dt, _reason, _n, _names = _inspect_exif_for_rename(image_path)
    return dt


def rename_photos_in_folder(folder, on_log=None, image_dates=None, allow_mtime_fallback=False) -> dict:
    """folder 안의 사진들을 바꾼다.
    [고친 점 - 이번 버그 수정]
    예전에는 EXIF이 없으면 무조건 파일 수정 시간(mtime)으로 바꿨다.
    그런데 키즈노트 다운로드 파일의 mtime은 '다운로드한 시간(2026-11-18)'이라서,
    촬영일(2026-11-06)이 2026-11-18로 잘못 바뀌는 버그가 생겼다.
    그래서 이제 우선순위는: 1) EXIF  2) 키즈노트 API 날짜(image_dates)  3) 건너뜀
    mtime은 키즈노트 다운로드에서는 기본적으로 쓰지 않는다.
    로컬 사진(원래 rename_photos.py 용도)처럼 mtime이 촬영일과 비슷한 경우에만
    allow_mtime_fallback=True 로 부르면 mtime을 쓴다.
    image_dates: {파일명: datetime} 또는 [datetime...] (파일 정렬 순서와 같은 순서).
    반환: {"renamed": int, "skipped": int, "not_renamed_no_date": int, "pairs": [(old, new), ...]}
    """
    folder = Path(folder)
    if not folder.exists():
        return {"renamed": 0, "skipped": 0, "not_renamed_no_date": 0, "pairs": []}
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in RENAME_SUPPORTED_EXTS]
    files.sort()
    # image_dates를 파일명 -> datetime dict로 정규화
    date_by_name: dict = {}
    if isinstance(image_dates, dict):
        for k, v in image_dates.items():
            if isinstance(v, datetime):
                date_by_name[str(k)] = v
            elif v is not None:
                dt = _parse_api_datetime(v)
                if dt:
                    date_by_name[str(k)] = dt
    elif isinstance(image_dates, (list, tuple)):
        for p, v in zip(files, image_dates):
            if isinstance(v, datetime):
                date_by_name[p.name] = v
            elif v is not None:
                dt = _parse_api_datetime(v)
                if dt:
                    date_by_name[p.name] = dt
    renamed = 0
    skipped = 0
    no_date = 0
    pairs: list = []
    pillow_warned = False
    for original_path in files:
        taken_date, reason, tag_count, tag_names = _inspect_exif_for_rename(original_path)
        source = ""
        if taken_date:
            source = "EXIF"
        else:
            # Pillow 없음이면 EXIF을 아예 못 읽은 거라서, mtime으로 넘어가면 안 된다
            if reason == "Pillow 없음" and not pillow_warned:
                if on_log:
                    on_log("    [경고] Pillow가 없어서 EXIF을 읽을 수 없습니다. requirements.txt 설치 후 다시 실행하세요. (이 상태에서는 파일시간으로 바꾸지 않습니다)")
                pillow_warned = True
            # 2순위: 키즈노트 API 날짜
            api_dt = date_by_name.get(original_path.name)
            if api_dt:
                taken_date = api_dt
                source = "키즈노트 API"
            elif allow_mtime_fallback:
                try:
                    taken_date = datetime.fromtimestamp(os.path.getmtime(original_path))
                    source = "파일시간"
                except Exception:
                    taken_date = None
            else:
                # 3순위 없음: 다운로드 시간으로 잘못 바꾸지 않고 건너뛴다
                no_date += 1
                if on_log:
                    if reason == "Pillow 없음":
                        on_log(f"    [건너뜀] {original_path.name}: Pillow 없음 + 키즈노트 날짜 없음 - 다운로드 시간으로 바꾸지 않음")
                    else:
                        on_log(f"    [건너뜀] {original_path.name}: 촬영일을 알 수 없음 ({reason}, EXIF 태그 {tag_count}개) - 다운로드 시간({datetime.fromtimestamp(os.path.getmtime(original_path)).strftime('%Y-%m-%d %H:%M:%S') if original_path.exists() else '?'})으로 바꾸지 않음")
                continue
        if not taken_date:
            no_date += 1
            continue
        base_name = taken_date.strftime("%Y%m%d_%H%M%S")
        ext = original_path.suffix.lower()
        new_path = folder / f"{base_name}{ext}"
        counter = 1
        while new_path.exists() and new_path != original_path:
            new_path = folder / f"{base_name}_{counter}{ext}"
            counter += 1
        if original_path == new_path:
            skipped += 1
            continue
        try:
            original_path.rename(new_path)
        except Exception as e:
            if on_log:
                on_log(f"    [이름 변경 실패] {original_path.name}: {e}")
            continue
        renamed += 1
        pairs.append((original_path.name, new_path.name))
        if on_log:
            on_log(f"    [이름 변경 {source}] {original_path.name} -> {new_path.name}")
    return {"renamed": renamed, "skipped": skipped, "not_renamed_no_date": no_date, "pairs": pairs}
