import os
import sys
import asyncio
import json

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.rag.config import settings
from app.rag.deps import get_hybrid_retriever, get_llm
from app.rag.services.rag_generator import GenerationPipeline

TEST_CASES = [
    {
        "id": 1,
        "type": "Basic Single-doc",
        "query": "Pasien memiliki blackhead dan whitehead. Treatment apa yang paling spesifik untuk concern tersebut?",
        "expected_evidence": "Deep Acne Extraction",
        "key_checks": ["Deep Acne Extraction"]
    },
    {
        "id": 2,
        "type": "Basic Single-doc",
        "query": "Apakah Blue Light Acne Therapy memiliki downtime?",
        "expected_evidence": "Tidak ada downtime",
        "key_checks": ["tidak ada downtime", "tidak memiliki downtime", "tanpa downtime", "no downtime"]
    },
    {
        "id": 3,
        "type": "Cross-doc",
        "query": "Pasien oily dan acne-prone. Treatment apa yang relevan dan facial wash apa yang cocok?",
        "expected_evidence": "Acne Intensive Program / Sebum Control Facial + Acneact Low pH Gentle Acne Facial Wash",
        "key_checks": ["Acne Intensive Program", "Low pH Gentle Acne Facial Wash"]
    },
    {
        "id": 4,
        "type": "Cross-doc",
        "query": "Pasien mild acne dan oily skin. Treatment apa yang cocok dan serum Acneact apa yang dapat mendukung concern tersebut?",
        "expected_evidence": "Acne Intensive Program + Acneact Anti Acne Serum",
        "key_checks": ["Anti Acne Serum"]
    },
    {
        "id": 5,
        "type": "Cross-doc",
        "query": "Pasien punya jerawat merah/meradang. Produk Acneact apa yang secara spesifik ditujukan untuk concern tersebut?",
        "expected_evidence": "Acneact BHA & Sulfur Acne Spot Gel",
        "key_checks": ["BHA & Sulfur", "Spot Gel"]
    },
    {
        "id": 6,
        "type": "Cross-doc",
        "query": "Pasien memiliki bekas jerawat dan noda hitam setelah acne membaik. Produk Acneact apa yang paling relevan?",
        "expected_evidence": "Acneact Post Acne Spot Serum",
        "key_checks": ["Post Acne Spot Serum"]
    },
    {
        "id": 7,
        "type": "Cross-doc",
        "query": "Setelah Acne Intensive Program, apakah Acneact Anti Acne Serum cocok untuk pasien oily/acne-prone?",
        "expected_evidence": "Cocok/relevan untuk oily/acne-prone, tidak mengklaim kombinasi pasca-treatment jika tidak tercantum",
        "key_checks": ["cocok", "Anti Acne Serum"]
    },
    {
        "id": 8,
        "type": "Cross-doc",
        "query": "Pasien menjalani Acne Peel Therapy. Produk Acneact apa yang sebaiknya langsung dipakai setelah treatment?",
        "expected_evidence": "KB tidak menentukan produk spesifik pasca-peel",
        "key_checks": ["tidak ada", "tidak menentukan", "tidak mewajibkan", "tidak dianjurkan", "tidak spesifik"]
    },
    {
        "id": 9,
        "type": "Cross-doc",
        "query": "Pasien baru selesai Deep Acne Extraction. Apa aftercare treatment-nya dan produk sunscreen Acneact apa yang tersedia untuk kulit berminyak/berjerawat?",
        "expected_evidence": "Aftercare: Hindari makeup 24 jam / jangan sering menyentuh wajah; Sunscreen: Acne Protection & Oil Control Sunscreen SPF45 PA+++",
        "key_checks": ["SPF45", "Oil Control Sunscreen"]
    },
    {
        "id": 10,
        "type": "Cross-doc",
        "query": "Pasien acne-prone ingin sunscreen yang tidak menyumbat pori dan bisa dipakai di bawah makeup. Produk apa yang sesuai?",
        "expected_evidence": "Acne Protection & Oil Control Sunscreen SPF45 PA+++",
        "key_checks": ["Acne Protection", "SPF45"]
    },
    {
        "id": 11,
        "type": "Cross-doc",
        "query": "Pasien memiliki acne aktif sekaligus bekas jerawat. Apakah Acneact Anti Acne Serum dan Post Acne Spot Serum memiliki target concern yang sama?",
        "expected_evidence": "Berbeda: Anti Acne Serum = active acne/oil/comedones; Post Acne Spot Serum = PIH/dark spots",
        "key_checks": ["berbeda", "Anti Acne", "Post Acne"]
    },
    {
        "id": 12,
        "type": "Multi-hop",
        "query": "Pasien oily skin, comedonal acne, dan blackhead. Berikan treatment yang relevan, produk cleanser, dan produk spot treatment yang relevan.",
        "expected_evidence": "Treatment: Acne Intensive Program / Deep Acne Extraction; Cleanser: Low pH Gentle Acne Facial Wash; Spot: BHA & Sulfur Acne Spot Gel",
        "key_checks": ["Extraction", "Facial Wash", "Spot Gel"]
    },
    {
        "id": 13,
        "type": "Multi-hop",
        "query": "Pasien acne-prone dengan active acne lalu mengalami PIH. Produk apa yang relevan untuk masing-masing fase concern?",
        "expected_evidence": "Active acne -> Anti Acne Serum / Spot Gel; PIH -> Post Acne Spot Serum",
        "key_checks": ["Anti Acne", "Post Acne"]
    },
    {
        "id": 14,
        "type": "Negative Groundedness",
        "query": "Apakah Acne Peel Therapy aman untuk semua ibu hamil karena menggunakan acid konsentrasi rendah?",
        "expected_evidence": "Kehamilan tidak disarankan / kontraindikasi",
        "key_checks": ["tidak disarankan", "kontraindikasi", "tidak aman"]
    },
    {
        "id": 15,
        "type": "Negative Groundedness",
        "query": "Berapa persen hasil perbaikan Acne Peel setelah 3 sesi?",
        "expected_evidence": "Data persentase tidak tersedia",
        "key_checks": ["tidak tersedia", "tidak tercantum", "tidak ada data"]
    },
    {
        "id": 16,
        "type": "Negative Groundedness",
        "query": "Berapa dosis atau konsentrasi parameter Blue Light yang digunakan pada setiap sesi?",
        "expected_evidence": "Hanya durasi 20 menit, parameter teknis dosis/konsentrasi tidak tersedia",
        "key_checks": ["20 menit", "tidak tersedia", "tidak tercantum"]
    },
    {
        "id": 17,
        "type": "Negative Groundedness",
        "query": "Bolehkah menggunakan Acneact Anti Acne Serum langsung setelah Microneedling?",
        "expected_evidence": "KB tidak menentukan kompatibilitas / aturan langsung",
        "key_checks": ["tidak ada", "tidak menentukan", "tidak mencantumkan", "tidak disarankan", "tidak ada aturan"]
    },
    {
        "id": 18,
        "type": "Negative Groundedness",
        "query": "Apakah Post Acne Spot Serum wajib digunakan setelah Acne Peel Therapy?",
        "expected_evidence": "Tidak wajib / tidak ditentukan sebagai kewajiban",
        "key_checks": ["tidak wajib", "bukan kewajiban", "tidak menentukan"]
    },
    {
        "id": 19,
        "type": "How-to",
        "query": "Bagaimana cara menggunakan Acneact Low pH Gentle Acne Facial Wash dan kapan digunakan?",
        "expected_evidence": "Basahi wajah -> tuang secukupnya -> pijat 30-60 detik -> bilas; pagi & malam",
        "key_checks": ["basahi", "pagi", "malam"]
    },
    {
        "id": 20,
        "type": "How-to",
        "query": "Bagaimana penggunaan Acneact Anti Acne Serum dan apa warning-nya?",
        "expected_evidence": "2-3 tetes setelah toner; warning: hindari eksfoliasi konsentrasi tinggi",
        "key_checks": ["2-3 tetes", "hindari"]
    },
    {
        "id": 21,
        "type": "How-to",
        "query": "Bagaimana penggunaan Acneact BHA & Sulfur Acne Spot Gel?",
        "expected_evidence": "Oleskan tipis pada jerawat 2-3 kali sehari; warning: hindari mata/bibir / luka terbuka",
        "key_checks": ["oleskan tipis", "2-3 kali", "hindari"]
    },
    {
        "id": 22,
        "type": "How-to",
        "query": "Bagaimana penggunaan Post Acne Spot Serum?",
        "expected_evidence": "Pagi dan malam setelah toner; sunscreen setiap pagi",
        "key_checks": ["pagi", "malam", "toner", "sunscreen"]
    },
    {
        "id": 23,
        "type": "Comparison",
        "query": "Bandingkan Acneact Anti Acne Serum dengan BHA & Sulfur Acne Spot Gel.",
        "expected_evidence": "Serum: whole-face routine, acne/oily; Spot Gel: spot treatment, red/inflamed acne",
        "key_checks": ["seluruh wajah", "spot treatment", "meradang"]
    },
    {
        "id": 24,
        "type": "Complex Multi-hop",
        "query": "Pasien oily skin dengan mild inflammatory acne, papules, dan bekas jerawat. Buat rekomendasi treatment + produk, tetapi pisahkan mana untuk active acne dan mana untuk post-acne.",
        "expected_evidence": "Active acne: Treatment + Anti Acne Serum/Spot Gel; Post-acne: Post Acne Spot Serum",
        "key_checks": ["active acne", "post-acne"]
    },
    {
        "id": 25,
        "type": "Grounding Audit L2 - General Medical",
        "query": "Apa perbedaan papule dan pustule?",
        "expected_evidence": "General medical definition without claiming ERHA origin",
        "key_checks": ["papule", "pustule"]
    },
    {
        "id": 26,
        "type": "Grounding Audit L3 - Mixed Query",
        "query": "Secara umum apa itu PIH dan produk ERHA apa yang digunakan?",
        "expected_evidence": "General PIH explanation + ERHA product evidence",
        "key_checks": ["pih", "noda", "serum"]
    },
    {
        "id": 27,
        "type": "Grounding Audit - Missing ERHA Product",
        "query": "Apakah ada produk ERHA khusus Vitiligo?",
        "expected_evidence": "Explicit absence statement without hallucinating ERHA facts",
        "key_checks": ["tidak tersedia", "tidak ada", "tidak tercantum"]
    },
    {
        "id": 28,
        "type": "LLM Synthesis & Contribution Test",
        "query": "Pasien oily skin, comedonal acne, dan blackhead. Buat analisis klinis dan alur rekomendasi perawatan.",
        "expected_evidence": "LLM active clinical reasoning and multi-source synthesis",
        "key_checks": ["rekomendasi", "extraction", "acne"]
    }
]

async def run_evaluation():
    print("=" * 80)
    print("RUNNING EVALUATION SUITE FOR ALL 24 CLINICAL TEST CASES")
    print("=" * 80)

    # Initialize RAG components
    from app.rag.services.factory import AdapterFactory
    from app.rag.services.rag_retriever import HybridRetriever, BM25Index

    vector_store = AdapterFactory.get_vector_store()
    bm25 = BM25Index()
    bm25.load(settings.bm25_index_path)
    retriever = HybridRetriever(vector_store=vector_store, bm25_index=bm25)
    llm = AdapterFactory.get_llm()
    pipeline = GenerationPipeline(retriever=retriever, llm_adapter=llm)

    passed_count = 0
    failed_count = 0

    for test in TEST_CASES:
        print(f"\n--- [Test #{test['id']}] {test['type']} ---")
        print(f"Query: {test['query']}")
        
        try:
            res = pipeline.generate_answer(query=test['query'])
            answer = res.get("answer", "")
            
            # Evaluate key checks
            ans_lower = answer.lower()
            matches = [chk for chk in test["key_checks"] if chk.lower() in ans_lower]
            is_pass = len(matches) > 0

            if is_pass:
                passed_count += 1
                status_str = "PASS"
            else:
                failed_count += 1
                status_str = "FAIL"

            print(f"Status   : {status_str}")
            print(f"Answer   : {answer[:250]}...")

        except Exception as e:
            failed_count += 1
            print(f"Status   : ERROR ({e})")

    print("\n" + "=" * 80)
    print(f"FINAL EVALUATION SUMMARY: {passed_count}/{len(TEST_CASES)} PASSED ({(passed_count/len(TEST_CASES))*100:.1f}%)")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(run_evaluation())
