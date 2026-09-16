"""vault_obsidian/(24.7만 건, 아카이브 전용)에서 하이라이트만 뽑아
vault_browse/(옵시디언이 실제로 여는 작은 볼트)를 만든다.

왜 필요한가: 옵시디언 메타데이터 캐시가 전체 24.7만 개 파일을 스캔하는 데
며칠이 걸림(2026-09-14) — 파일 수 자체도 많지만, 이 머신에서 파일 I/O가
비정상적으로 느린 정황(회사 DLP 에이전트 PISupervisor.exe crash-loop 전례,
docs 메모리 project_pgportable_instability 참고)도 겹쳐 있어 단순 스캔조차
느리다. vault_obsidian은 아카이브로만 남기고, 옵시디언은 vault_browse(하이라이트
~1.2만 건)만 열게 하면 인덱싱이 분 단위로 끝난다.

사용법:
    python pipeline/build_browse_vault.py

재실행하면 매번 하이라이트 대상만 골라 vault_browse를 새로 채운다(증분 아님 —
전체 지우고 다시 복사, 하이라이트 규모가 작아 부담 없음).
"""
from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(line_buffering=True)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "vault_obsidian"
DST = ROOT / "vault_browse"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def is_highlighted(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER_RE.match(text)
    if not m:
        return False
    for line in m.group(1).split("\n"):
        if line.strip() == "highlight: true":
            return True
    return False


def copy_highlighted(folder: str) -> int:
    src = SRC / folder
    dst = DST / folder
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in src.glob("*.md"):
        if is_highlighted(f):
            shutil.copy(f, dst / f.name)
            count += 1
    return count


def copy_all(folder: str) -> int:
    src = SRC / folder
    dst = DST / folder
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for f in src.glob("*"):
        if f.is_file():
            shutil.copy(f, dst / f.name)
            count += 1
    return count


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)

    n_artists = copy_highlighted("artists")
    print(f"[browse] artists 하이라이트 {n_artists}건 복사")
    n_collectors = copy_highlighted("collectors")
    print(f"[browse] collectors 하이라이트 {n_collectors}건 복사")
    n_galleries = copy_all("galleries")
    print(f"[browse] galleries 전체 {n_galleries}건 복사")
    n_museums = copy_all("museums")
    print(f"[browse] museums 전체 {n_museums}건 복사")
    n_auctions = copy_all("auctions")
    print(f"[browse] auctions 전체 {n_auctions}건 복사")

    total = n_artists + n_collectors + n_galleries + n_museums + n_auctions
    dashboard = f"""---
type: "dashboard"
---
# 아트그래프 브라우징 볼트 (하이라이트만, {total:,}건)

이건 옵시디언이 실제로 여는 작은 볼트입니다. 전체 아카이브(247,507건,
`vault_obsidian/`)를 그대로 열면 옵시디언 메타데이터 캐시 인덱싱이 며칠씩 걸려서
(2026-09-14) 여기만 따로 뽑았습니다 — `pipeline/build_browse_vault.py`로 재생성.

## 작가 ({n_artists:,}명 — 전체 21만 명 중 하이라이트만)
[[artists/_작가.base|작가 보기]]

## 컬렉터 ({n_collectors:,}명 — 전체 3.4만 명 중 하이라이트만)
[[collectors/_컬렉터.base|컬렉터 보기]]

## 갤러리 ({n_galleries:,}곳 — 전체)
[[galleries/_갤러리.base|갤러리 보기]]

## 미술관 ({n_museums:,}곳 — 전체)
[[museums/_미술관.base|미술관 보기]]

## 경매사 ({n_auctions:,}곳 — 전체)
[[auctions/_경매사.base|경매사 보기]]

## 주의
- 여기 없는 작가/컬렉터로 걸린 링크는 빨간색(끊긴 링크)으로 보입니다 — 정상입니다.
  전체 기록은 `vault_obsidian/`(아카이브, 옵시디언으로 직접 열지 말 것)에 있습니다.
- 작품(artworks) 개별 문서는 이 볼트에도 포함되지 않습니다.
"""
    (DST / "00 대시보드.md").write_text(dashboard, encoding="utf-8")

    obsidian_src = SRC / ".obsidian"
    obsidian_dst = DST / ".obsidian"
    obsidian_dst.mkdir(exist_ok=True)
    for name in ("app.json", "appearance.json", "core-plugins.json"):
        shutil.copy(obsidian_src / name, obsidian_dst / name)
    if (obsidian_src / "themes").exists():
        shutil.copytree(obsidian_src / "themes", obsidian_dst / "themes", dirs_exist_ok=True)
    # workspace.json은 일부러 복사 안 함 — vault_obsidian 쪽 lastOpenFiles가
    # vault_browse에 없는 파일(하이라이트 제외된 문서)을 가리킬 수 있어서,
    # 옵시디언이 처음 열 때 새로 생성하게 둔다.

    print(f"[browse] 완료 — 총 {total}건 (vault_obsidian 24.7만 건 대비 {total/247507:.1%})")


if __name__ == "__main__":
    main()
