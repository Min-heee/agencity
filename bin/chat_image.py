#!/usr/bin/env python3
"""대화 사진. 서버(office_server.py)와 say.sh가 같은 검사를 써요.

- 형식은 파일 머리로만 판별해요. 파일 이름과 Content-Type은 믿지 않아요.
- 사진은 <층>/chat-images/(총괄 대화는 hq/chat-images/)에 새 이름으로 저장해요. 서버와 세션은 지우지 않아요.
- 표준 모듈만 쓰고 Python 3.9에서 돌아요. 픽셀까지 풀어 보지는 않아요.

say.sh: chat_image.py <보관할 곳> <.out 폴더> <사진 경로>...   저장한 이름 목록(JSON)을 내요. 하나라도 거절되면 아무것도 저장하지 않아요.
"""
import json
import os
import re
import secrets
import shutil
import stat
import struct
import sys

DIRNAME = "chat-images"
MAX_BYTES = 10 * 1024 * 1024         # 한 장
MAX_SIDE = 12000                     # 긴 변
MAX_PIXELS = 80000000
SAY_PIXELS = 24000000                # say.sh --image. 서버가 줄일 수 없어서 더 좁아요
MAX_DIR_BYTES = 500 * 1024 * 1024    # 층마다
MIN_FREE = 1024 * 1024 * 1024        # 맥의 빈 공간
MAX_PER_MSG = 4
JPEG_PARTS = 1000                    # JPEG 머리의 조각 수. 사진을 내줄 때마다 다시 재니까 오래 잡지 않게 해요
GIF_BLOCKS = 200000                  # GIF 안의 조각 수(확장, 프레임, 데이터 조각을 함께 세요). 같은 까닭이에요
NAME = re.compile(r"^[0-9a-f]{32}\.(?:png|jpg|gif|webp)\Z")
TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
HEIF = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif", b"avis"}

NOT_IMAGE = "PNG·JPG·GIF·WebP만 붙일 수 있어요."
HEIC = "HEIC는 안 돼요. JPG로 바꿔서 붙여요."
TOO_BIG = "사진이 너무 커요. 10MB 안으로 줄여서 붙여요."
TOO_LONG = "사진이 너무 커요(긴 변 12000px, 8000만 화소까지). 줄여서 붙여요."
BOX_FULL = "사진 보관함이 찼어요. Finder에서 지운 뒤 다시 보내요."
DISK_LOW = "맥 저장 공간이 모자라요. 비운 뒤 다시 보내요."
SAY_BIG = "사진이 너무 커요(긴 변 12000px, 2400만 화소까지). 줄여서 다시 올려요."


class Bad(Exception):
    def __init__(self, msg, code=415):
        super().__init__(msg)
        self.msg, self.code = msg, code


def _jpeg(b):
    i = 2
    for _ in range(JPEG_PARTS):
        if i + 9 >= len(b) or b[i] != 0xFF:
            break
        start = i
        while i < len(b) and b[i] == 0xFF:
            i += 1
            if i - start > 64:
                raise Bad(NOT_IMAGE)
        m = b[i]
        i += 1
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            continue
        if m in (0xD9, 0xDA):
            break
        n = struct.unpack(">H", b[i:i + 2])[0]
        if n < 2:
            break
        if 0xC0 <= m <= 0xCF and m not in (0xC4, 0xC8, 0xCC):
            h, w = struct.unpack(">HH", b[i + 3:i + 7])
            return w, h
        i += n
    raise Bad(NOT_IMAGE)


def _gif(b):
    """논리 화면과 프레임 범위의 최댓값. Chrome은 프레임이 더 크면 그 크기로 풀어서 머리만 재면 픽셀 상한이 듣지 않아요."""
    w, h = struct.unpack("<HH", b[6:10])
    i, blocks = 13 + (3 << ((b[10] & 7) + 1) if b[10] & 0x80 else 0), 0
    while i < len(b) and b[i] in (0x2C, 0x21):
        blocks += 1   # 빈 확장이나 빈 프레임만 잔뜩 넣어도 오래 잡지 않게 바깥 반복도 세요
        if blocks > GIF_BLOCKS:
            raise Bad(NOT_IMAGE)
        if b[i] == 0x2C:
            x, y, fw, fh = struct.unpack("<HHHH", b[i + 1:i + 9])
            w, h = max(w, x + fw), max(h, y + fh)
            i += 11 + (3 << ((b[i + 9] & 7) + 1) if b[i + 9] & 0x80 else 0)   # 프레임 머리, 색표, LZW 최소 코드 크기
        else:
            i += 2
        while i < len(b) and b[i]:
            i += b[i] + 1
            blocks += 1
            if blocks > GIF_BLOCKS:
                raise Bad(NOT_IMAGE)
        i += 1
    return w, h


def _head(b):
    if b[:8] == b"\x89PNG\r\n\x1a\n" and b[12:16] == b"IHDR" and len(b) >= 24:
        return ("png",) + struct.unpack(">II", b[16:24])
    if b[:3] == b"\xff\xd8\xff":
        return ("jpg",) + _jpeg(b)
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return ("gif",) + _gif(b)
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP" and len(b) >= 30:
        k = b[12:16]
        if k == b"VP8 " and b[23:26] == b"\x9d\x01\x2a":
            w, h = struct.unpack("<HH", b[26:30])
            return "webp", w & 0x3FFF, h & 0x3FFF
        if k == b"VP8L" and b[20] == 0x2F:
            v = int.from_bytes(b[21:25], "little")
            return "webp", (v & 0x3FFF) + 1, ((v >> 14) & 0x3FFF) + 1
        if k == b"VP8X":
            return "webp", int.from_bytes(b[24:27], "little") + 1, int.from_bytes(b[27:30], "little") + 1
    if b[4:8] == b"ftyp" and b[8:12] in HEIF:
        raise Bad(HEIC)
    raise Bad(NOT_IMAGE)


def sniff(b):
    """파일 머리로 (확장자, 가로, 세로)를 정해요. 사진이 아니거나 너무 크면 Bad예요."""
    if len(b) < 12:
        raise Bad(NOT_IMAGE)
    try:
        ext, w, h = _head(b)
    except (struct.error, IndexError):
        raise Bad(NOT_IMAGE)
    if not w or not h or max(w, h) > MAX_SIDE or w * h > MAX_PIXELS:
        raise Bad(TOO_LONG, 413)
    return ext, w, h


def _ignore_all(path, fd=None):
    """안에 .gitignore(*)를 둬요. 이미 있으면 그대로예요."""
    try:
        g = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=fd)
    except FileExistsError:
        return
    try:
        os.write(g, b"*\n")
    finally:
        os.close(g)


def open_dir(base, make=False):
    """보관 폴더를 링크를 따라가지 않고 열어요. make면 만들고 안에 .gitignore(*)도 둬요."""
    d = os.path.join(base, DIRNAME)
    try:
        if make:
            try:
                os.mkdir(d, 0o700)
            except FileExistsError:
                pass
        fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        raise Bad("사진 보관 폴더가 없어요", 404)
    except OSError:
        raise Bad("사진 보관 폴더를 쓸 수 없어요(링크는 받지 않아요)", 409)
    if make:
        try:
            _ignore_all(".gitignore", fd)
        except OSError:
            os.close(fd)
            raise
    return fd


def used(fd):
    n = 0
    with os.scandir(fd) as it:
        for e in it:
            try:
                s = e.stat(follow_symlinks=False)
                if stat.S_ISREG(s.st_mode):
                    n += s.st_size
            except OSError:
                pass
    return n


def _fits(base, fd, n):
    if fd is not None and used(fd) + n > MAX_DIR_BYTES:
        raise Bad(BOX_FULL, 507)
    if shutil.disk_usage(base).free < MIN_FREE:
        raise Bad(DISK_LOW, 507)


def room(base, n):
    """보관함에 n바이트가 들어갈지 봐요. 아직 폴더를 만들지 않아요."""
    try:
        fd = open_dir(base)
    except Bad as e:
        if e.code != 404:
            raise
        fd = None
    try:
        _fits(base, fd, n)
    finally:
        if fd is not None:
            os.close(fd)


def store(base, data):
    """검사하고 임시 파일에 쓴 뒤 이름을 바꿔요. 돌려주는 값은 {id, w, h, bytes}예요."""
    if len(data) > MAX_BYTES:
        raise Bad(TOO_BIG, 413)
    ext, w, h = sniff(data)
    fd = open_dir(base, make=True)
    try:
        _fits(base, fd, len(data))
        name, tmp = f"{secrets.token_hex(16)}.{ext}", f".{secrets.token_hex(8)}.tmp"
        f = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            with os.fdopen(f, "wb") as out:
                out.write(data)
            _fits(base, fd, 0)
            os.rename(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(tmp, dir_fd=fd)
            except OSError:
                pass
            raise
    finally:
        os.close(fd)
    return {"id": name, "w": w, "h": h, "bytes": len(data)}


def read_plain(where, name=None):
    """파일 바이트. 링크, FIFO, 하드링크는 따라가지 않아요."""
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        fd = os.open(name, flags, dir_fd=where) if name else os.open(where, flags)
    except OSError:
        raise Bad("파일을 열지 못했어요(링크는 받지 않아요)", 404)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Bad("보통 파일이 아니에요", 404)
        if st.st_nlink != 1:
            raise Bad("하드링크는 받지 않아요", 404)
        if st.st_size > MAX_BYTES:
            raise Bad(TOO_BIG, 413)
        with os.fdopen(os.dup(fd), "rb") as f:
            return f.read(MAX_BYTES + 1)
    finally:
        os.close(fd)


def load_stored(base, name):
    """보관한 사진 하나를 열 때마다 다시 확인해요. 머리와 확장자가 달라도 Bad예요."""
    if not isinstance(name, str) or not NAME.match(name):
        raise Bad("사진 이름이 이상해요", 404)
    fd = open_dir(base)
    try:
        data = read_plain(fd, name)
    finally:
        os.close(fd)
    if sniff(data)[0] != name.rsplit(".", 1)[1]:
        raise Bad("사진이 아니에요", 404)
    return data


def take(base, out, paths):
    """say.sh --image. 전부 검사한 뒤에만 저장해요. .out/이 링크면 밖의 원본을 올리고 지우게 돼서 받지 않아요."""
    if os.path.islink(out):
        raise Bad("사진은 링크가 아닌 .out/ 폴더에 둬요.", 409)
    try:
        _ignore_all(os.path.join(out, ".gitignore"))   # 세션이 먼저 만든 .out/일 수 있어요. 거절돼도 사본이 커밋되지 않게 먼저 둬요
    except OSError:
        pass
    out = os.path.realpath(out)
    if len(paths) > MAX_PER_MSG:
        raise Bad(f"사진은 한 번에 {MAX_PER_MSG}장까지예요.")
    blobs = []
    for p in paths:
        if os.path.realpath(os.path.dirname(p) or ".") != out:
            raise Bad(f"사진은 대화 파일 옆 .out/ 폴더에 둬요: {out}/")
        data = read_plain(p)
        try:
            w, h = sniff(data)[1:]
        except Bad as e:   # 세션 길의 상한으로 말해요. 서버 상한(8000만)대로 줄여도 다시 거절되면 안 돼요
            raise Bad(SAY_BIG, 413) if e.msg == TOO_LONG else e
        if w * h > SAY_PIXELS:
            raise Bad(SAY_BIG, 413)
        blobs.append(data)
    room(base, sum(len(d) for d in blobs))
    return [store(base, d)["id"] for d in blobs]


if __name__ == "__main__":
    try:
        print(json.dumps(take(sys.argv[1], sys.argv[2], sys.argv[3:])))
    except Bad as e:
        print(e.msg, file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"사진을 남기지 못했어요: {type(e).__name__}", file=sys.stderr)
        sys.exit(1)
