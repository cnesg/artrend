"""Poly Auction(polypm.com.cn) 낙찰결과 1회성 적재 스크립트 (2026-09-22 파일럿, 중국 경매사 조사).

run.py를 거치지 않고 로더를 직접 호출한다(지시사항: run.py는 다른 에이전트가 동시 편집 중이라
건드리지 않음). DATABASE_URL은 호출부에서 인라인으로 export해야 한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import get_connection
from store import PgStore
import polypm

store = PgStore(get_connection())
n = polypm.load(store)
print(f"done, loaded={n}")
