import os
import sys

sys.path.insert(0, os.path.abspath("backend"))

from app.rag.services.vector_store import PGVectorAdapter

v_store = PGVectorAdapter()
v_store.delete_document('140572fe-0897-477e-a633-8614c735a77d')
