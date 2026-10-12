import sys
sys.path.insert(0, "pipeline")
from db import get_connection
from store import PgStore
import lyonandturnbull

store = PgStore(get_connection())
lyonandturnbull.load(store)
