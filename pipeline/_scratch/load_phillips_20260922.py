import sys
sys.path.insert(0, "pipeline")
from db import get_connection
from store import PgStore
import phillips

store = PgStore(get_connection())
phillips.load(store)
