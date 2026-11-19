import os
from pathlib import Path
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS

# 지원하는 확장자
SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png', '.heic', '.heif', '.webp', '.tiff'}

def get_taken_date(image_path: Path):
    """EXIF에서 촬영일 가져오기, 없으면 None"""
    try:
        with Image.open(image_path) as img:
            # 신버전 getexif() 먼저, 안 되면 구버전 _getexif()
            exif_data = None
            try:
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
            if exif_data:
                # 36867 = DateTimeOriginal, 306 = DateTime
                for tag_id, value in exif_data.items():
                    tag = TAGS.get(tag_id, tag_id)
                    if tag in ['DateTimeOriginal', 'DateTime']:
                        # 형식: "2023:05:20 14:32:10"
                        try:
                            return datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        except:
                            continue
    except Exception as e:
        pass
    return None

def rename_photos(folder_path, dry_run=True, allow_mtime_fallback=True):
    folder = Path(folder_path)
    if not folder.exists():
        print(f"폴더가 없습니다: {folder}")
        return

    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS]
    files.sort() # 순서 고정

    print(f"총 {len(files)}개 파일 발견")
    print(f"모드: {'미리보기 (dry-run)' if dry_run else '실제 변경'}")
    if not allow_mtime_fallback:
        print("주의: 파일시간 fallback 끔 - EXIF이 없으면 건너뜁니다 (키즈노트 다운로드처럼 파일시간이 다운로드 시간인 경우용)\n")
    else:
        print("EXIF 없으면 파일시간으로 fallback 합니다. 키즈노트 다운로드 파일은 파일시간이 다운로드 시간이라서 --no-mtime 을 쓰세요.\n")

    for original_path in files:
        taken_date = get_taken_date(original_path)

        # EXIF 없으면 파일 수정 시간으로 fallback (allow_mtime_fallback일 때만)
        if not taken_date:
            if not allow_mtime_fallback:
                print(f"[건너뜀] {original_path.name} EXIF 없음 - 파일시간(다운로드 시간)으로 바꾸지 않음")
                continue
            mtime = os.path.getmtime(original_path)
            taken_date = datetime.fromtimestamp(mtime)
            source = "파일시간"
        else:
            source = "EXIF"

        # 새 이름 만들기: YYYYMMDD_HHMMSS
        base_name = taken_date.strftime("%Y%m%d_%H%M%S")
        ext = original_path.suffix.lower()
        new_path = folder / f"{base_name}{ext}"

        # 중복 처리: 20240315_143210_1.jpg
        counter = 1
        while new_path.exists() and new_path != original_path:
            new_path = folder / f"{base_name}_{counter}{ext}"
            counter += 1

        if original_path == new_path:
            print(f"SKIP: {original_path.name} 이미 올바른 이름")
            continue

        print(f"[{source}] {original_path.name} -> {new_path.name}")

        if not dry_run:
            original_path.rename(new_path)

    print("\n완료!")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="사진 촬영일로 파일명 변경")
    parser.add_argument("folder", nargs="?", default=".", help="사진 폴더 경로 (기본: 현재 폴더)")
    parser.add_argument("--real", action="store_true", help="이 옵션을 넣어야 실제로 변경됨, 없으면 미리보기만 함")
    parser.add_argument("--no-mtime", action="store_true", help="EXIF 없으면 파일시간으로 바꾸지 않고 건너뜀 (키즈노트 다운로드 파일용)")
    
    args = parser.parse_args()
    rename_photos(args.folder, dry_run=not args.real, allow_mtime_fallback=not args.no_mtime)
