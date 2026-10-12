import sys; sys.path.insert(0, "pipeline")
from db import get_connection
from store import PgStore
import bukowskis

store = PgStore(get_connection())
bukowskis.load(store)
