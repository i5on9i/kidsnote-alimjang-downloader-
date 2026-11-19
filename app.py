
# app.py
# 키즈노트 알림장 이미지 다운로더 - 윈도우용 GUI (Tkinter, 기본 라이브러리만 사용)
# 실행:  run.bat 더블클릭  또는  python app.py
# CLI:   python app.py --cli --list
#        python app.py --cli --urls "https://.../..." --output "C:\Users\...\Pictures\kidsnote-alimjang"

from __future__ import annotations

import argparse
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from kidsnote_core import (
    Child, Report, SessionManager, KidsNoteBrowser,
    download_images_for_report, get_app_dir, get_default_download_dir,
    rename_photos_in_folder,
    sanitize_folder,
)

VERSION = "1.0.0"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"키즈노트 알림장 다운로더 v{VERSION}  -  Windows용")
        self.geometry("920x760")
        self.minsize(860, 680)

        self.session = SessionManager()
        self.browser = KidsNoteBrowser(self.session, headless=True)
        self.reports: list[Report] = []
        # NOTE: DO NOT use self.children - Tk reserves .children (dict) for widgets.
        # That name breaks Widget creation with TypeError: list indices must be integers.
        self.kid_list: list[Child] = []
        self.selected_child: Child | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.busy = False

        self._build_ui()
        self._refresh_login_status()
        self.after(200, self._drain_log)
        # 시작 시 아이 목록은 로그인돼 있으면 조용히 불러온다
        if self.session.has_session:
            self.log("저장된 세션이 있습니다. 아이 목록을 불러오려면 [아이 새로고침]을 눌러주세요.")

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # --- 상단: 로그인 ---
        top = ttk.LabelFrame(self, text="1. 로그인")
        top.pack(fill="x", **pad)

        self.login_label = ttk.Label(top, text="로그인 상태 확인 중…")
        self.login_label.pack(side="left", padx=8, pady=6)

        ttk.Button(top, text="브라우저로 로그인", command=self.on_login).pack(side="left", padx=4)
        ttk.Button(top, text="로그아웃 (세션 삭제)", command=self.on_logout).pack(side="left", padx=4)

        # --- 아이 선택 ---
        child_frame = ttk.LabelFrame(self, text="2. 아이 선택")
        child_frame.pack(fill="x", **pad)
        ttk.Label(child_frame, text="아이:").pack(side="left", padx=8)
        self.child_var = tk.StringVar()
        self.child_combo = ttk.Combobox(child_frame, textvariable=self.child_var, state="readonly", width=24)
        self.child_combo.pack(side="left", padx=4)
        self.child_combo.bind("<<ComboboxSelected>>", self.on_child_selected)
        ttk.Button(child_frame, text="아이 새로고침", command=self.on_refresh_children).pack(side="left", padx=4)
        ttk.Label(child_frame, text="※ 아이가 안 보이면 로그인 때 아이별 앨범 화면까지 한 번씩 들어가주세요. (원본 kd와 동일)", foreground="#666").pack(side="left", padx=8)

        # --- 탭: 목록 / URL ---
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=False, **pad)

        # 탭 1: 목록
        tab_list = ttk.Frame(self.notebook)
        self.notebook.add(tab_list, text="  알림장 목록에서 선택  ")
        search_row = ttk.Frame(tab_list)
        search_row.pack(fill="x", padx=6, pady=6)
        ttk.Label(search_row, text="검색어:").pack(side="left")
        self.keyword_var = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.keyword_var, width=28).pack(side="left", padx=4)
        ttk.Button(search_row, text="알림장 목록 불러오기", command=self.on_fetch_list).pack(side="left", padx=4)
        ttk.Button(search_row, text="전체 선택", command=lambda: self._set_all(True)).pack(side="left", padx=4)
        ttk.Button(search_row, text="전체 해제", command=lambda: self._set_all(False)).pack(side="left", padx=4)
        self.list_count_label = ttk.Label(search_row, text="0개")
        self.list_count_label.pack(side="left", padx=8)

        # Treeview: 체크, 날짜, 종류, 제목
        cols = ("check", "date", "kind", "title")
        self.tree = ttk.Treeview(tab_list, columns=cols, show="headings", height=10, selectmode="extended")
        self.tree.heading("check", text="✓")
        self.tree.heading("date", text="날짜")
        self.tree.heading("kind", text="종류")
        self.tree.heading("title", text="제목 (클릭하면 선택/해제)")
        self.tree.column("check", width=36, anchor="center")
        self.tree.column("date", width=110, anchor="center")
        self.tree.column("kind", width=70, anchor="center")
        self.tree.column("title", width=560, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=6, pady=4)
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", self._on_tree_click)
        scrollbar = ttk.Scrollbar(tab_list, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        # 탭 2: URL 직접 입력
        tab_url = ttk.Frame(self.notebook)
        self.notebook.add(tab_url, text="  URL 직접 입력  ")
        ttk.Label(tab_url, text="원하는 알림장 주소를 한 줄에 하나씩 붙여넣으세요. 목록이 안 잡힐 때도 이걸로 됩니다.", wraplength=820).pack(anchor="w", padx=6, pady=6)
        ttk.Label(tab_url, text="예) 키즈노트 웹에서 알림장을 열고 주소창의 URL을 복사해서 붙여넣기", foreground="#666").pack(anchor="w", padx=6)
        self.url_text = tk.Text(tab_url, height=8, wrap="none")
        self.url_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.url_text.insert("1.0", "")

        # --- 다운로드 설정 ---
        opt = ttk.LabelFrame(self, text="3. 다운로드 설정")
        opt.pack(fill="x", **pad)
        ttk.Label(opt, text="저장 폴더:").pack(side="left", padx=8)
        self.output_var = tk.StringVar(value=str(get_default_download_dir()))
        ttk.Entry(opt, textvariable=self.output_var, width=52).pack(side="left", padx=4)
        ttk.Button(opt, text="찾아보기…", command=self.on_browse_output).pack(side="left", padx=4)

        opt2 = ttk.Frame(self)
        opt2.pack(fill="x", **pad)
        self.include_video_var = tk.BooleanVar(value=False)
        self.organize_var = tk.BooleanVar(value=True)
        self.skip_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt2, text="동영상도 함께 받기", variable=self.include_video_var).pack(side="left", padx=8)
        ttk.Checkbutton(opt2, text="날짜_제목 폴더로 정리", variable=self.organize_var).pack(side="left", padx=8)
        ttk.Checkbutton(opt2, text="이미 받은 파일 건너뛰기", variable=self.skip_var).pack(side="left", padx=8)

        opt3 = ttk.Frame(self)
        opt3.pack(fill="x", **pad)
        self.auto_rename_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt3, text="다운로드한 사진 이름 자동으로 변경한다 (기본값: 변경한다)", variable=self.auto_rename_var).pack(side="left", padx=8)
        ttk.Label(opt3, text="EXIF 촬영일 → 없으면 키즈노트 날짜로 YYYYMMDD_HHMMSS.jpg 로 변경, 둘 다 없으면 건너뜀 (다운로드 시간으로는 안 바꿈) / 끄면 원래 이름 그대로", foreground="#666").pack(side="left", padx=4)

        # --- 실행 ---
        run_row = ttk.Frame(self)
        run_row.pack(fill="x", **pad)
        self.download_btn = ttk.Button(run_row, text="▶  선택한 알림장 이미지 일괄 다운로드", command=self.on_download)
        self.download_btn.pack(side="left", padx=4, pady=4)
        self.progress = ttk.Progressbar(run_row, orient="horizontal", mode="determinate", length=340)
        self.progress.pack(side="left", padx=8, fill="x", expand=True)
        self.progress_label = ttk.Label(run_row, text="")
        self.progress_label.pack(side="left", padx=4)

        # --- 로그 ---
        log_frame = ttk.LabelFrame(self, text="로그")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=10, wrap="word")
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)
        self.log_text.config(state="disabled")

    # ---------------- 로그 ----------------
    def log(self, msg: str):
        self.log_queue.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.config(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._drain_log)

    def _set_busy(self, busy: bool):
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.download_btn.config(state=state)

    # ---------------- 로그인 / 아이 ----------------
    def _refresh_login_status(self):
        if self.session.has_session:
            self.login_label.config(text="● 로그인됨 (세션 있음)  -  저장 위치: " + str(get_app_dir()))
        else:
            self.login_label.config(text="○ 로그인 안 됨  -  [브라우저로 로그인]을 눌러 키즈노트에 로그인하세요.")
        # 저장된 아이 목록이 있으면 콤보에 채운다
        cached = self.session.load_children()
        if cached and not self.kid_list:
            self.kid_list = cached
            self._fill_child_combo()

    def _fill_child_combo(self):
        names = [c.name for c in self.kid_list] or ["(아이 정보 없음 - 로그인 후 새로고침)"]
        self.child_combo["values"] = names
        if names and self.child_combo.get() not in names:
            self.child_combo.set(names[0])
            if self.kid_list:
                self.selected_child = self.kid_list[0]

    def on_child_selected(self, event=None):
        name = self.child_var.get()
        for c in self.kid_list:
            if c.name == name:
                self.selected_child = c
                break
        self.log(f"아이 선택: {name}")

    def on_login(self):
        if self.busy:
            return
        self._set_busy(True)
        self.log("브라우저를 엽니다. 키즈노트에 로그인한 뒤 브라우저를 닫아주세요.")
        self.log("팁: 로그인 후 아이별 앨범/알림장 화면을 한 번씩 열어두면 아이 정보가 잘 저장됩니다.")
        def work():
            try:
                # 로그인 자체는 GUI 스레드를 막지 않게 별도 스레드에서,
                # Playwright는 동기 API라 이 스레드에서 실행한다.
                self.browser.login_interactive(on_status=self.log)
                self.after(0, self._refresh_login_status)
                self.log("로그인 세션 저장 완료. 이제 [알림장 목록 불러오기]를 눌러보세요.")
            except Exception as e:
                self.log(f"로그인 중 오류: {e}")
            finally:
                self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=work, daemon=True).start()

    def on_logout(self):
        if messagebox.askyesno("로그아웃", "저장된 로그인 세션을 삭제할까요?"):
            self.session.clear()
            self.kid_list = []
            self.selected_child = None
            self._fill_child_combo()
            self._refresh_login_status()
            self.log("세션을 삭제했습니다.")

    def on_refresh_children(self):
        if not self.session.has_session:
            messagebox.showwarning("로그인 필요", "먼저 로그인하세요.")
            return
        self._set_busy(True)
        def work():
            try:
                self.log("아이 목록을 불러오는 중…")
                kids = self.browser.fetch_children()
                if kids:
                    self.kid_list = kids
                    self.after(0, self._fill_child_combo)
                    self.log(f"아이 {len(kids)}명 확인: {', '.join(c.name for c in kids)}")
                else:
                    self.log("아이 이름을 자동으로 찾지 못했습니다. 그래도 URL 입력 탭으로는 다운로드할 수 있습니다.")
                    self.log("팁: 로그인할 때 아이별 화면을 한 번씩 열어두면 다음부터 잘 뜹니다.")
            except Exception as e:
                self.log(f"아이 목록 오류: {e}")
            finally:
                self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=work, daemon=True).start()

    def on_browse_output(self):
        d = filedialog.askdirectory(initialdir=self.output_var.get())
        if d:
            self.output_var.set(d)

    # ---------------- 목록 ----------------
    def on_fetch_list(self):
        if not self.session.has_session:
            messagebox.showwarning("로그인 필요", "먼저 로그인하세요.")
            return
        self._set_busy(True)
        keyword = self.keyword_var.get().strip()
        def work():
            try:
                self.log(f"알림장 목록을 불러오는 중… (검색어: {keyword or '없음'})")
                reports = self.browser.list_reports(keyword=keyword, limit=200)
                self.reports = reports
                self.after(0, self._fill_tree)
                self.log(f"알림장 {len(reports)}건을 찾았습니다.")
                if not reports:
                    self.log("목록이 비어 있습니다. 키즈노트 웹 구조가 바뀌었을 수 있어요.")
                    self.log("→ [URL 직접 입력] 탭에 알림장 주소를 붙여넣으면 바로 다운로드할 수 있습니다.")
            except Exception as e:
                self.log(f"목록 불러오기 오류: {e}")
            finally:
                self.after(0, lambda: self._set_busy(False))
        threading.Thread(target=work, daemon=True).start()

    def _fill_tree(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for r in self.reports:
            self.tree.insert("", "end", iid=r.id, values=("☐", r.date or "-", r.kind, r.title))
        self.list_count_label.config(text=f"{len(self.reports)}개")

    def _on_tree_click(self, event):
        # 제목 셀을 클릭하면 체크 토글. 헤더 클릭은 무시.
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        item = self.tree.identify_row(event.y)
        if not item:
            return
        for r in self.reports:
            if r.id == item:
                r.selected = not r.selected
                self.tree.set(item, "check", "☑" if r.selected else "☐")
                break

    def _set_all(self, val: bool):
        for r in self.reports:
            r.selected = val
            if self.tree.exists(r.id):
                self.tree.set(r.id, "check", "☑" if val else "☐")

    def _collect_targets(self) -> list[Report]:
        # 현재 탭에 따라 목록 선택 또는 URL 입력을 반환한다
        tab = self.notebook.index(self.notebook.select())
        if tab == 1:
            raw = self.url_text.get("1.0", "end").strip()
            urls = [u.strip() for u in re.split(r"[\s,]+", raw) if u.strip().startswith("http")]
            if not urls:
                messagebox.showwarning("URL 필요", "URL 입력 탭에 알림장 주소를 한 줄에 하나씩 붙여넣으세요.")
                return []
            out: list[Report] = []
            for i, u in enumerate(urls):
                out.append(Report(id=f"url-{i}", title=f"URL 알림장 {i+1}", url=u, selected=True))
            return out
        selected = [r for r in self.reports if r.selected]
        if not selected:
            messagebox.showwarning("선택 필요", "목록에서 다운로드할 알림장을 클릭해서 선택하세요. (제목을 클릭하면 ☑가 됩니다)")
            return []
        return selected

    # ---------------- 다운로드 ----------------
    def on_download(self):
        if self.busy:
            return
        targets = self._collect_targets()
        if not targets:
            return
        if not self.session.has_session:
            messagebox.showwarning("로그인 필요", "먼저 로그인하세요.")
            return
        out_dir = Path(self.output_var.get()).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            messagebox.showerror("폴더 오류", f"저장 폴더를 만들 수 없습니다:\n{e}")
            return

        child_name = self.selected_child.name if self.selected_child else ""
        include_video = self.include_video_var.get()
        organize = self.organize_var.get()
        skip = self.skip_var.get()
        auto_rename = self.auto_rename_var.get() if hasattr(self, "auto_rename_var") else True

        self._set_busy(True)
        self.progress["value"] = 0
        self.progress_label.config(text="")

        def work():
            try:
                total_reports = len(targets)
                grand_dl = grand_skip = grand_fail = 0
                grand_renamed = 0
                grand_no_date = 0
                rename_jobs = {}  # 폴더 -> {파일명: 키즈노트 API 날짜}
                for ri, report in enumerate(targets, start=1):
                    if child_name:
                        report.child_name = child_name
                    self.log(f"[{ri}/{total_reports}] {report.title} - 이미지 수집 중… ({report.url})")
                    try:
                        rep, images = self.browser.get_report_images(report, include_video=include_video)
                    except Exception as e:
                        self.log(f"  → 이미지 수집 실패: {e}")
                        grand_fail += 1
                        continue
                    self.log(f"  → 이미지 {len(images)}장 찾음. 다운로드 시작…")
                    if not images:
                        self.log("  → 이 알림장에는 다운로드할 이미지가 없습니다. (이미지가 없는 글이거나, 로그인 세션이 만료됐을 수 있습니다)")
                        continue

                    def on_prog(idx: int, total: int, fname: str):
                        # 전체 진행률 대신 현재 알림장 내 진행률을 표시한다
                        pct = int(idx / max(total, 1) * 100)
                        self.after(0, lambda: self._update_progress(pct, f"{ri}/{total_reports} - {fname} ({idx}/{total})"))

                    res = download_images_for_report(
                        rep, images, out_dir, self.session,
                        organize_by_date=organize, skip_existing=skip,
                        include_video=include_video, on_progress=on_prog,
                    )
                    grand_dl += res.downloaded
                    grand_skip += res.skipped
                    grand_fail += res.failed
                    self.log(f"  → 완료: 새로 {res.downloaded}장, 건너뜀 {res.skipped}장, 실패 {res.failed}장")
                    for err in res.errors[:5]:
                        self.log(f"     실패: {err}")
                    if res.files:
                        self.log(f"     저장 위치: {res.files[0].parent}")
                        try:
                            _folder = res.files[0].parent
                            _m = rename_jobs.setdefault(_folder, {})
                            # res.files 순서 = image_urls 순서 = image_api_dates 순서
                            _api_dates = getattr(rep, "image_api_dates", None) or []
                            for _f, _adt in zip(res.files, _api_dates):
                                if _adt is not None:
                                    try:
                                        from datetime import datetime as _dt
                                        if isinstance(_adt, _dt):
                                            _m[_f.name] = _adt
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                if auto_rename and rename_jobs:
                    self.log("사진 이름 자동 변경 중... (우선순위: EXIF 촬영일 → 키즈노트 API 날짜 → 없으면 건너뜀, 다운로드 시간으로는 바꾸지 않음)")
                    for _folder in sorted(rename_jobs):
                        try:
                            _r = rename_photos_in_folder(_folder, on_log=lambda m: self.log(m), image_dates=rename_jobs.get(_folder, {}), allow_mtime_fallback=False)
                            grand_renamed += _r.get("renamed", 0)
                            grand_no_date += _r.get("not_renamed_no_date", 0)
                            if _r.get("renamed", 0):
                                self.log(f"  → {_folder}: {_r.get('renamed', 0)}장 이름 변경 완료")
                            if _r.get("not_renamed_no_date", 0):
                                self.log(f"  → {_folder}: {_r.get('not_renamed_no_date', 0)}장 건너뜀 (EXIF도 키즈노트 날짜도 없어서 다운로드 시간으로 바꾸지 않음)")
                        except Exception as _e:
                            self.log(f"  → {_folder}: 이름 변경 실패: {_e}")
                    self.log(f"사진 이름 자동 변경 완료 - 총 {grand_renamed}장 변경됨, 건너뜀 {grand_no_date}장")
                elif not auto_rename:
                    self.log("사진 이름 자동 변경: 끔 - 원래 파일명 그대로 두었습니다.")
                self.log(f"전체 완료 - 새로 {grand_dl}장, 건너뜀 {grand_skip}장, 실패 {grand_fail}장, 이름 변경 {grand_renamed}장, 날짜 없어서 건너뜀 {grand_no_date}장 / 저장 폴더: {out_dir}")
                self.after(0, lambda: messagebox.showinfo("완료", f"다운로드 완료!\n새로 {grand_dl}장, 건너뜀 {grand_skip}장, 실패 {grand_fail}장, 이름 변경 {grand_renamed}장, 날짜 없어서 건너뜀 {grand_no_date}장\n\n저장 폴더:\n{out_dir}"))
            except Exception as e:
                self.log(f"다운로드 중 오류: {e}")
                self.after(0, lambda: messagebox.showerror("오류", str(e)))
            finally:
                self.after(0, lambda: self._set_busy(False))
                self.after(0, lambda: self.progress.config(value=0))
                self.after(0, lambda: self.progress_label.config(text=""))
        threading.Thread(target=work, daemon=True).start()

    def _update_progress(self, pct: int, text: str):
        self.progress["value"] = pct
        self.progress_label.config(text=text)


# ----------------------------------------------------------------------
# CLI (GUI 없이 쓰고 싶을 때)
# ----------------------------------------------------------------------

def run_cli(args) -> int:
    session = SessionManager()
    browser = KidsNoteBrowser(session, headless=True)
    if args.list:
        if not session.has_session:
            print("먼저 GUI에서 로그인하세요. (python app.py 실행 후 [브라우저로 로그인])")
            return 1
        reports = browser.list_reports(keyword=args.keyword or "", limit=200)
        for r in reports:
            print(f"{r.date}\t{r.kind}\t{r.title}\t{r.url}")
        print(f"총 {len(reports)}건")
        return 0
    if args.urls:
        if not session.has_session:
            print("먼저 GUI에서 로그인하세요.")
            return 1
        out_dir = Path(args.output or str(get_default_download_dir())).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        total = 0
        for url in args.urls:
            rep = Report(id="cli", title="CLI 알림장", url=url)
            rep2, images = browser.get_report_images(rep, include_video=args.video)
            print(f"{url} -> 이미지 {len(images)}장")
            res = download_images_for_report(rep2, images, out_dir, session, organize_by_date=True, skip_existing=True)
            print(f"  새로 {res.downloaded}장, 건너뜀 {res.skipped}장, 실패 {res.failed}장 -> {res.files[0].parent if res.files else out_dir}")
            total += res.downloaded
            if not getattr(args, "no_rename", False) and res.files:
                _m2 = {}
                _ad2 = getattr(rep2, "image_api_dates", None) or []
                for _f2, _adt2 in zip(res.files, _ad2):
                    if _adt2 is not None:
                        _m2[_f2.name] = _adt2
                _rr = rename_photos_in_folder(res.files[0].parent, on_log=lambda m: print(m), image_dates=_m2, allow_mtime_fallback=False)
                print(f"  이름 변경 {_rr.get('renamed', 0)}장, 날짜 없어서 건너뜀 {_rr.get('not_renamed_no_date', 0)}장")
        print(f"완료: 새로 {total}장")
        return 0
    print("CLI 사용법: python app.py --cli --list  또는  python app.py --cli --urls <URL> [--output 폴더]")
    return 1


def main():
    parser = argparse.ArgumentParser(description="키즈노트 알림장 이미지 다운로더 (Windows용)")
    parser.add_argument("--cli", action="store_true", help="GUI 없이 CLI로 실행")
    parser.add_argument("--list", action="store_true", help="알림장 목록 출력 (CLI)")
    parser.add_argument("--keyword", default="", help="목록 검색어")
    parser.add_argument("--urls", nargs="*", default=[], help="다운로드할 알림장 URL들")
    parser.add_argument("--output", default="", help="저장 폴더")
    parser.add_argument("--video", action="store_true", help="동영상도 함께")
    parser.add_argument("--no-rename", action="store_true", help="사진 이름 자동 변경 끄기 (기본값: 변경한다)")
    args = parser.parse_args()
    if args.cli:
        return run_cli(args)
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
