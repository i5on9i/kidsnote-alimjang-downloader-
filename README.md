# 키즈노트 알림장 이미지 다운로더 (Windows용)

키즈노트에 로그인해서 **원하는 알림장**을 골라, 그 안에 있는 이미지들을 한 번에 다운로드하는 윈도우용 Python 앱입니다.

참고한 원본: https://github.com/bestend/kidsnote  
원본 `kd`는 **앨범** 전용 CLI + `install.sh`(리눅스/맥용)이라서, 이 앱은 아래처럼 바꿨습니다.

|  | 원본 `bestend/kidsnote` | 이 앱 |
|---|---|---|
| 대상 | 앨범 | **알림장** (공지/앨범 링크도 목록에 같이 뜸) |
| 형태 | CLI (`kd login / fetch / download`) | **GUI (Tkinter)** + CLI 옵션도 있음 |
| 설치 | `curl ... install.sh \| bash` | **`run.bat` 더블클릭** (윈도우) |
| 로그인 | 브라우저 열고 닫으면 세션 저장 | 동일 (비밀번호를 앱이 저장하지 않음) |
| 저장 | `~/Pictures/kidsnote` | `~/Pictures/kidsnote-alimjang` (기본값, 변경 가능) |
| 목록이 안 잡힐 때 | 없음 | **URL 직접 붙여넣기 탭**으로 우회 가능 |

## 1. 실행 방법 (윈도우, 가장 쉬운 방법)

1. **Python 설치** (아직 없으면)
   - https://www.python.org/downloads/ 에서 Python 3.10 이상 설치
   - 설치 화면에서 **`Add python.exe to PATH` 체크 필수**
2. 이 폴더를 원하는 곳에 풀기 (예: `C:\kidsnote-downloader`)
3. **`run.bat` 더블클릭**
   - 처음 한 번만 가상환경 + 패키지 + Chromium 설치라서 몇 분 걸릴 수 있습니다.
   - 그 다음부터는 바로 앱이 뜹니다.
4. 앱이 뜨면 아래 순서대로 사용하세요.

> 수동으로 실행하고 싶으면: `python -m venv .venv` → `.venv\Scripts\activate` → `pip install -r requirements.txt` → `python -m playwright install chromium` → `python app.py`

## 2. 사용 순서

```
1. [브라우저로 로그인] 클릭
   → 크롬 창이 뜹니다. 키즈노트에 평소대로 로그인하세요.
   → 로그인 후 아이별 앨범/알림장 화면을 한 번씩 열어두면 아이 정보가 잘 저장됩니다.
   → 다 됐으면 브라우저 창을 닫으세요. 닫으면 세션만 로컬에 저장됩니다.

2. [아이 새로고침] → 아이 선택
   (아이가 안 떠도 URL 입력으로는 다운로드됩니다)

3. 알림장 고르기 - 둘 중 하나
   A) [알림장 목록에서 선택] 탭
      → [알림장 목록 불러오기] → 원하는 글 제목을 클릭해서 ☑ 체크
      → 검색어 입력하면 제목으로 필터됩니다.
   B) [URL 직접 입력] 탭
      → 키즈노트 웹에서 원하는 알림장을 열고, 주소창 URL을 복사해서 한 줄에 하나씩 붙여넣기
      → 목록이 안 잡힐 때 가장 확실한 방법입니다.

4. 저장 폴더 확인 (기본: 내 사진\kidsnote-alimjang)
   → [날짜_제목 폴더로 정리] 체크 권장
   → [동영상도 함께 받기]는 필요할 때만 체크

5. [▶ 선택한 알림장 이미지 일괄 다운로드] 클릭
   → 로그에서 진행 상황을 확인하세요.
   → 이미 받은 파일은 기본적으로 건너뜁니다.
```

### 저장 구조 예시

```
Pictures\kidsnote-alimjang\
  └─ 김민준\
      ├─ 2026-05-12_오늘은 소풍 갔어요\
      │   ├─ 001_...jpg
      │   ├─ 002_...jpg
      │   └─ 003_...jpg
      └─ 2026-05-13_비 오는 날 실내놀이\
          └─ 001_...jpg
```

## 3. CLI로 쓰고 싶을 때

```bat
.venv\Scripts\activate
python app.py --cli --list
python app.py --cli --urls "https://www.kidsnote.com/..." "https://www.kidsnote.com/..."
python app.py --cli --urls "https://..." --output "C:\Users\내이름\Pictures\kidsnote-alimjang"
```

## 4. exe로 만들기 (선택)

`build_exe.bat` 더블클릭 → `dist\KidsnoteAlimjangDownloader.exe` 생성  
exe를 다른 PC로 옮겨서 실행해도 됩니다.

## 5. 문제 있을 때

| 증상 | 해결 |
|---|---|
| `Playwright가 설치되지 않았습니다` | `run.bat`을 다시 실행하거나 `python -m playwright install chromium` |
| 로그인했는데 목록이 비어 있음 | 키즈노트 웹 구조가 바뀌었을 수 있음. **[URL 직접 입력] 탭**으로 URL 붙여넣기 |
| 특정 알림장에 이미지가 0장 | 이미지가 없는 글이거나, 스크롤이 끝나기 전에 닫힌 경우. 다시 한 번 다운로드 시도 |
| `세션이 만료된 것 같습니다` | [브라우저로 로그인]을 다시 실행 |
| 아이가 안 보임 | 로그인할 때 아이별 앨범 화면까지 한 번씩 들어가야 함 (원본 kd와 동일) |
| `python을 찾을 수 없습니다` | Python 재설치 시 `Add python.exe to PATH` 체크, PC 재시작 |

## 6. 개인정보 / 보안

- **비밀번호를 앱이 저장하지 않습니다.** 브라우저에서 직접 로그인하고, 브라우저를 닫으면 세션(쿠키)만 로컬에 저장됩니다.
- 세션 저장 위치: `%APPDATA%\kidsnote-alimjang\session.json` (이 PC에만 있음)
- 로그아웃하면 세션 파일이 삭제됩니다.
- 이 앱은 본인 계정으로 본인이 볼 수 있는 알림장만 다운로드하는 용도입니다. 타인의 계정/게시물에는 사용하지 마세요.

## 7. 파일 구성

```
app.py             - GUI + CLI 진입점 (Tkinter)
kidsnote_core.py   - 로그인 세션, 목록/이미지 수집, 다운로드 핵심 로직
requirements.txt   - playwright, requests
run.bat            - 윈도우용 실행 (더블클릭)
build_exe.bat      - exe 빌드용 (선택)
```

## License

MIT (원본 레포와 동일)


## run.bat 인코딩 주의

`.bat` 파일은 반드시 ASCII(영문)만 써야 합니다. 한글을 넣으면 `cmd.exe`가 CP949로 읽으면서 깨집니다. 한글 메시지가 필요하면 `app.py` / `README.md`에만 넣고, `.bat`에는 영문만 쓰세요.
