import os
import sys
import json
import asyncio

sys.path.insert(0, os.path.abspath("backend"))

from app.rag.services.general_knowledge_service import GeneralKnowledgeService, resolve_approved_file
from app.rag.services.rag_retriever import BM25Index, HybridRetriever
from app.rag.services.vector_store import PGVectorAdapter

async def run_e2e_mutation_trace():
    print("=== STARTING END-TO-END MUTATION TRACE ===")
    
    # 1. Target identification
    target_query = "Acne Peel Therapy"
    res = await GeneralKnowledgeService.find_target_document_and_item(target_query)
    if not res:
        print("ERROR: Target document not found for query")
        return
    
    knowledge_id, target_item, doc_data = res
    print(f"[TRACE Step 1] Target Resolved: knowledge_id='{knowledge_id}', target_item='{target_item}'")
    
    # Read old state
    approved_file = resolve_approved_file(knowledge_id)
    with open(approved_file, "r", encoding="utf-8") as f:
        old_json = json.load(f)
    old_version = old_json.get("updated_at") or "v1.0"
    old_chunks = old_json.get("chunks", [])
    print(f"[TRACE Step 2] Canonical JSON Read: file='{approved_file}', old_version='{old_version}', old_chunks_count={len(old_chunks)}")
    
    v_store = PGVectorAdapter()
    bm25 = BM25Index()
    if os.path.exists("data/bm25_index.pkl"):
        bm25.load("data/bm25_index.pkl")
        
    retriever = HybridRetriever(vector_store=v_store, bm25_index=bm25)
    
    # STEP 3: BEFORE EDIT RETRIEVAL
    print("\n--- TEST A1: Before Edit Retrieval ---")
    before_res = retriever.retrieve("kandungan Acne Peel Therapy", top_k=5)
    before_chunks = before_res.get("results", [])
    print(f"Before Edit Retrieved Chunks Count: {len(before_chunks)}")
    if before_chunks:
        print(f"Top Chunk ID: '{before_chunks[0].get('chunk_id') or before_chunks[0].get('id')}'")
        print(f"Top Content Snippet: {before_chunks[0].get('content', '')[:120]}...")
        
    # STEP 4: EXECUTE EDIT MUTATION
    print("\n--- TEST A2: Executing EDIT Mutation ---")
    edit_res = await GeneralKnowledgeService.apply_edit(
        knowledge_id=knowledge_id,
        field="kandungan",
        new_value="BHA 2% (Salicylic Acid)",
        vector_store=v_store,
        bm25_index=bm25,
        target_item=target_item,
        auto_approve=True
    )
    print(f"Edit Apply Result: success={edit_res.get('success')}, message='{edit_res.get('message')}'")
    
    # STEP 5: AFTER EDIT VERIFICATION
    print("\n--- TEST A3: After Edit Verification ---")
    with open(approved_file, "r", encoding="utf-8") as f:
        new_json = json.load(f)
    new_chunks = new_json.get("chunks", [])
    print(f"1. Canonical JSON Updated: 'BHA 2%' in summary = {'BHA 2%' in new_json.get('summary', '')}")
    print(f"2. New Chunks Count in JSON: {len(new_chunks)}")
    
    after_res = retriever.retrieve("kandungan Acne Peel Therapy berapa?", top_k=5)
    after_chunks = after_res.get("results", [])
    print(f"3. After Edit Retrieved Chunks Count: {len(after_chunks)}")
    if after_chunks:
        top_text = after_chunks[0].get('content', '')
        print(f"   Top Chunk ID: '{after_chunks[0].get('chunk_id') or after_chunks[0].get('id')}'")
        print(f"   Top Content Snippet: {top_text[:150]}...")
        has_new_val = "BHA 2%" in top_text
        print(f"4. Retrieved Content Grounded on NEW Value ('BHA 2%'): {has_new_val}")
        has_old_only = "Salicylic Acid (BHA)" in top_text and "BHA 2%" not in top_text
        print(f"5. Old Version Only Retrieved: {has_old_only}")

    print("\n=== END-TO-END TRACE COMPLETE ===")

if __name__ == "__main__":
    asyncio.run(run_e2e_mutation_trace())
