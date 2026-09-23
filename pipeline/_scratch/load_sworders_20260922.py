import sys
sys.path.insert(0, "pipeline")
from db import get_connection
from store import PgStore
import sworders

store = PgStore(get_connection())
sworders.load(store)
