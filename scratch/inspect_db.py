import os
import sys
import json

sys.path.insert(0, os.path.abspath("backend"))

from app.rag.services.vector_store import PGVectorAdapter
from sqlalchemy import text

adapter = PGVectorAdapter()
with adapter.Session() as session:
    rows = session.execute(text("SELECT id, source_file, metadata->>'knowledge_id' as kid, metadata->>'file_name' as fn, metadata->>'product_name' as pn, metadata->>'title' as title FROM arya_noble_kb LIMIT 20")).fetchall()
    print("=== PGVECTOR TABLE SAMPLE ROWS ===")
    for r in rows:
        print(r)
