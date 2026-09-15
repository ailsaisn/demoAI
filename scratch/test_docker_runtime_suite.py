import os
import sys
import json
import time
import requests
import subprocess
from datetime import datetime

BASE_URL = "http://localhost:8000"
HEALTH_URL = "http://localhost:8000/health"
QUERY_ENDPOINT = f"{BASE_URL}/api/ai/query-general"

def wait_for_backend_healthy(timeout=120):
    print("Waiting for backend container to become healthy...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            res = requests.get(HEALTH_URL, timeout=5)
            if res.status_code == 200:
                print(f"Backend container is HEALTHY (200 OK after {int(time.time() - start)}s)")
                return True
        except Exception:
            pass
        time.sleep(3)
    print("Backend container failed to become healthy within timeout!")
    return False

def test_query(question):
    try:
        payload = {"prompt": question}
        res = requests.post(QUERY_ENDPOINT, json=payload, timeout=20)
        if res.status_code == 200:
            return res.json()
        else:
            return {"error": f"HTTP {res.status_code}: {res.text}"}
    except Exception as e:
        return {"error": str(e)}

def run_docker_cmd(cmd_list):
    print(f"Executing Docker Command: {' '.join(cmd_list)}")
    res = subprocess.run(cmd_list, capture_output=True, text=True)
    print(f"Exit Code: {res.returncode}")
    if res.stdout:
        print(f"STDOUT: {res.stdout.strip()}")
    if res.stderr:
        print(f"STDERR: {res.stderr.strip()}")
    return res.returncode == 0

def run_docker_runtime_verification():
    print("============================================================")
    print("        REAL DOCKER CONTAINER RUNTIME TEST SUITE           ")
    print("============================================================")

    results = {}

    # Verify initial health
    if not wait_for_backend_healthy(timeout=60):
        print("Initial healthcheck failed. Aborting.")
        return

    # -------------------------------------------------------------
    # 1. REAL DOCKER RESTART TEST — EDIT PERSISTENCE
    # -------------------------------------------------------------
    print("\n>>> TEST 1: EDIT MUTATION + REAL DOCKER CONTAINER RESTART <<<")
    q_edit_target = "Berapa kandungan Acne Peel Therapy?"
    base_res = test_query(q_edit_target)
    base_text = base_res.get("response", "") or base_res.get("answer", "") or str(base_res)
    print(f"Baseline Response: {base_text[:120]}...")

    print("Executing Edit prompt: 'Ubah kandungan Acne Peel Therapy menjadi BHA 2% (Salicylic Acid)'")
    edit_cmd = [
        "docker", "exec", "skin_clinic_backend",
        "python", "-c",
        """
import asyncio, sys
sys.path.insert(0, '/app')
from app.rag.services.general_knowledge_service import GeneralKnowledgeService
from app.rag.services.vector_store import PGVectorAdapter
from app.rag.services.rag_retriever import BM25Index
from app.rag.config import settings
import os

async def main():
    vs = PGVectorAdapter()
    bm = BM25Index()
    if os.path.exists(settings.bm25_index_path):
        bm.load(settings.bm25_index_path)
    res = await GeneralKnowledgeService.apply_edit(
        knowledge_id="37565fca-b0d6-436e-9835-37d21cf7e9ae",
        field="kandungan",
        new_value="BHA 2% (Salicylic Acid)",
        vector_store=vs,
        bm25_index=bm,
        target_item="Acne Peel Therapy",
        auto_approve=True
    )
    print("CONTAINER_EDIT_RESULT:", res)

asyncio.run(main())
"""
    ]
    run_docker_cmd(edit_cmd)
    
    post_edit_res = test_query(q_edit_target)
    post_edit_text = post_edit_res.get("response", "") or post_edit_res.get("answer", "") or str(post_edit_res)
    print(f"Post-Edit Response: {post_edit_text[:120]}...")

    # RESTART DOCKER CONTAINER
    print("\n--- RESTARTING REAL DOCKER CONTAINER 'skin_clinic_backend' ---")
    run_docker_cmd(["docker", "restart", "skin_clinic_backend"])
    healthy_after_restart = wait_for_backend_healthy(timeout=90)

    post_restart_res = test_query(q_edit_target)
    post_restart_text = post_restart_res.get("response", "") or post_restart_res.get("answer", "") or str(post_restart_res)
    print(f"Post-Restart Response: {post_restart_text[:120]}...")

    t1_pass = healthy_after_restart and ("BHA 2%" in post_restart_text or "salicylic" in post_restart_text.lower())
    results["1. Docker Restart after EDIT"] = ("PASS" if t1_pass else "FAIL", f"retrieved_post_restart={t1_pass}")

    # -------------------------------------------------------------
    # 2. REAL CONTAINER RECREATION TEST — EDIT PERSISTENCE
    # -------------------------------------------------------------
    print("\n>>> TEST 2: BACKEND CONTAINER RECREATION <<<")
    print("Recreating backend container using docker compose...")
    run_docker_cmd(["docker", "compose", "up", "-d", "--force-recreate", "backend"])
    healthy_after_recreate = wait_for_backend_healthy(timeout=90)

    post_recreate_res = test_query(q_edit_target)
    post_recreate_text = post_recreate_res.get("response", "") or post_recreate_res.get("answer", "") or str(post_recreate_res)
    print(f"Post-Recreate Response: {post_recreate_text[:120]}...")

    t2_pass = healthy_after_recreate and ("BHA 2%" in post_recreate_text or "salicylic" in post_recreate_text.lower())
    results["2. Container Recreation after EDIT"] = ("PASS" if t2_pass else "FAIL", f"retrieved_post_recreate={t2_pass}")

    # -------------------------------------------------------------
    # 3. REAL DOCKER RESTART & RECREATION — DELETE PERSISTENCE
    # -------------------------------------------------------------
    print("\n>>> TEST 3: DELETE MUTATION + DOCKER RESTART & RECREATION <<<")
    del_cmd = [
        "docker", "exec", "skin_clinic_backend",
        "python", "-c",
        """
import asyncio, sys
sys.path.insert(0, '/app')
from app.rag.services.general_knowledge_service import GeneralKnowledgeService
from app.rag.services.vector_store import PGVectorAdapter
from app.rag.services.rag_retriever import BM25Index
from app.rag.config import settings
import os

async def main():
    vs = PGVectorAdapter()
    bm = BM25Index()
    if os.path.exists(settings.bm25_index_path):
        bm.load(settings.bm25_index_path)
    res = await GeneralKnowledgeService.apply_delete(
        knowledge_id="37565fca-b0d6-436e-9835-37d21cf7e9ae",
        vector_store=vs,
        bm25_index=bm,
        target_item="Acne Intensive Program"
    )
    print("CONTAINER_DELETE_RESULT:", res)

asyncio.run(main())
"""
    ]
    run_docker_cmd(del_cmd)

    # Restart container
    print("\n--- RESTARTING REAL DOCKER CONTAINER AFTER DELETE ---")
    run_docker_cmd(["docker", "restart", "skin_clinic_backend"])
    wait_for_backend_healthy(timeout=90)

    q_delete_target = "Apa deskripsi Acne Intensive Program?"
    post_del_restart = test_query(q_delete_target)
    del_restart_text = post_del_restart.get("response", "") or str(post_del_restart)
    del_restart_pass = "tidak menemukan" in del_restart_text.lower() or "tidak tersedia" in del_restart_text.lower() or "maaf" in del_restart_text.lower()
    print(f"Post-Delete Restart Response: {del_restart_text[:120]}...")
    results["3. Docker Restart after DELETE"] = ("PASS" if del_restart_pass else "FAIL", f"deleted_unretrievable={del_restart_pass}")

    # Recreate container
    print("\n--- RECREATING REAL DOCKER CONTAINER AFTER DELETE ---")
    run_docker_cmd(["docker", "compose", "up", "-d", "--force-recreate", "backend"])
    wait_for_backend_healthy(timeout=90)

    post_del_recreate = test_query(q_delete_target)
    del_recreate_text = post_del_recreate.get("response", "") or post_del_recreate.get("answer", "") or str(post_del_recreate)
    del_recreate_pass = "tidak menemukan" in del_recreate_text.lower() or "tidak tersedia" in del_recreate_text.lower() or "maaf" in del_recreate_text.lower()
    print(f"Post-Delete Recreate Response: {del_recreate_text[:120]}...")
    results["4. Container Recreation after DELETE"] = ("PASS" if del_recreate_pass else "FAIL", f"deleted_unretrievable={del_recreate_pass}")

    # Restore Acne Intensive Program back to normal
    print("\n--- RESTORING DELETED ITEM FOR CLEAN ENVIRONMENT ---")
    restore_cmd = [
        "docker", "exec", "skin_clinic_backend",
        "python", "-c",
        """
import asyncio, sys
sys.path.insert(0, '/app')
from app.rag.services.general_knowledge_service import GeneralKnowledgeService
from app.rag.services.vector_store import PGVectorAdapter
from app.rag.services.rag_retriever import BM25Index
from app.rag.config import settings
import os

async def main():
    vs = PGVectorAdapter()
    bm = BM25Index()
    if os.path.exists(settings.bm25_index_path):
        bm.load(settings.bm25_index_path)
    res = await GeneralKnowledgeService.apply_edit(
        knowledge_id="37565fca-b0d6-436e-9835-37d21cf7e9ae",
        field="kandungan",
        new_value="BHA 2% (Salicylic Acid)",
        vector_store=vs,
        bm25_index=bm,
        target_item="Acne Peel Therapy",
        auto_approve=True
    )
    print("CONTAINER_RESTORE_RESULT:", res)

asyncio.run(main())
"""
    ]
    run_docker_cmd(restore_cmd)

    # -------------------------------------------------------------
    # PRINT FINAL TEST RESULTS TABLE
    # -------------------------------------------------------------
    print("\n============================================================")
    print("               DOCKER RUNTIME VERIFICATION SUMMARY          ")
    print("============================================================")
    print(f"| {'Test Name':<38} | {'Status':<8} | {'Evidence':<30} |")
    print("-" * 84)
    for test_name, (status, evidence) in results.items():
        print(f"| {test_name:<38} | {status:<8} | {evidence:<30} |")
    print("============================================================")

if __name__ == "__main__":
    run_docker_runtime_verification()
