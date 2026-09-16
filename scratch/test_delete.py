import os
import sys
from sqlalchemy import text

sys.path.insert(0, os.path.abspath("backend"))

from app.rag.services.vector_store import PGVectorAdapter

adapter = PGVectorAdapter()
with adapter.Session() as session:
    res1 = session.execute(text("SELECT count(*) FROM arya_noble_kb WHERE metadata->>'knowledge_id' = '140572fe-0897-477e-a633-8614c735a77d'")).scalar()
    print(f"Count by knowledge_id='140572fe-0897-477e-a633-8614c735a77d': {res1}")
    
    rows = session.execute(text("SELECT id, source_file, metadata->>'knowledge_id' as kid, metadata->>'file_name' as fn, metadata->>'title' as title FROM arya_noble_kb WHERE source_file ILIKE '%acne%' OR metadata->>'title' ILIKE '%acne%' LIMIT 10")).fetchall()
    print("=== ACNE SEARCH ROWS ===")
    for r in rows:
        print(r)
