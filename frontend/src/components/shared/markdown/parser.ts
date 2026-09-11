import type {
	PricingTier,
	ProcedureStep,
	Segment,
} from "./types";
import { isValidImageUrl, parseBulletLines, resolveImageUrl } from "./utils";

export function parseMarkdownSegments(markdown: string): Segment[] {
	if (!markdown) return [];

	// Pattern 1: Product or Treatment Overview Cards
	const cardPattern =
		/(?:!\[([^\]]*)\]\(([^)]+)\)\s*\n+)?###\s*(Product\s+(?:Overview|Details|Info|Specification|Summary)|Overview\s+Produk|Spesifikasi\s+Produk|Info\s+Produk|Ringkasan\s+Produk|Detail\s+Produk|Treatment\s+(?:Overview|Details|Info|Procedure|Summary)|Overview\s+Tindakan|Detail\s+Tindakan|Info\s+Tindakan)\s*\n+(?:!\[([^\]]*)\]\(([^)]+)\)\s*\n+)?((?:[ \t]*[-*]\s*\*\*[^*]+\*\*\s*[:–-][^\n]+(?:\n|$))+)/gi;

	// Pattern 2: Skincare Regimen / Rutinitas Routine Card
	const regimenPattern =
		/###\s*(?:Cara\s+Penggunaan|Rutinitas|Aturan\s+Pakai|Skincare\s+Routine|Daily\s+Routine|Waktu\s+Pemakaian)\s*\n+((?:[ \t]*[-*]\s*\*\*(?:Pagi|Siang|Malam|Morning|Night|Evening|Sore)\*\*\s*[:–-][^\n]+(?:\n|$))+)/gi;

	// Pattern 3: Do's & Don'ts Comparison Card
	const dosDontsPattern =
		/###\s*(?:Anjuran\s+&\s+Larangan|Do's\s+&\s+Don'ts|Do's\s+and\s+Don'ts|Yang\s+Boleh\s+&\s+Dilarang|Instruksi\s+Pasien)\s*\n+((?:[ \t]*[-*]\s*\*\*(?:Do's?|Anjuran|Boleh|Disarankan|Don'ts?|Larangan|Dilarang|Tidak\s+Boleh)\*\*\s*[:–-][^\n]+(?:\n|$))+)/gi;

	// Pattern 4: Consecutive Images / Before & After Side-by-Side Images
	const beforeAfterPattern =
		/!\[([^\]]*)\]\(([^)]+)\)\s*\n+!\[([^\]]*)\]\(([^)]+)\)/gi;

	// Pattern 5: Clinical SOP & Procedure Stepper Card
	const sopPattern =
		/###\s*(?:Prosedur\s+Tindakan|Tahapan\s+Treatment|Protokol\s+Tindakan|Prosedur\s+Klinis|Prosedur\s+Medis|Protokol\s+Perawatan|Tahapan\s+Aplikasi|Langkah\s+(?:Pengerjaan|Aplikasi)|Tahapan\s+Prosedur)\s*\n+((?:[ \t]*(?:[-*]\s*\*\*[^*]+\*\*|\d+\.|\bLangkah\s+\d+)[^\n]+(?:\n|$))+)/gi;

	// Pattern 6: Promotional & Validity Campaign Card
	const promoPattern =
		/###\s*(?:Promo\s+Spesial|Penawaran\s+Khusus|Diskon\s+Khusus|Informasi\s+Promo|Program\s+Promo|Penawaran\s+Terbatas|Promo\s+Treatment|Promo\s+Produk)\s*\n+((?:[ \t]*[-*]\s*\*\*[^*]+\*\*\s*[:–-][^\n]+(?:\n|$))+)/gi;

	// Pattern 7: Clinical Consultation & Diagnosis Summary Card
	const diagnosisPattern =
		/###\s*(?:Diagnosis\s+Klinis|Ringkasan\s+Konsultasi|Hasil\s+Diagnosis(?:\s+Klinis)?|Konsultasi\s+Kasus)\s*\n+((?:[ \t]*[-*]\s*\*\*[^*]+\*\*\s*[:–-][^\n]+(?:\n|$))+)/gi;

	// Pattern 8: Tiered Package & Multi-Session Pricing Card
	const tieredPricingPattern =
		/###\s*(?:Paket\s+Harga|Pilihan\s+Paket(?:\s+Treatment)?|Daftar\s+Paket|Opsi\s+Harga(?:\s+Paket)?|Tier\s+Pricing|Paket\s+Perawatan)\s*\n+((?:[ \t]*[-*]\s*\*\*[^*]+\*\*\s*[:–-][^\n]+(?:\n|$))+)/gi;

	// Pattern 9: Action / Mutation Confirmation Card
	const actionConfirmationPattern =
		/(?:(?:\*\*(?:Pratinjau\s+Perubahan(?:\s+Data)?|Konfirmasi\s+Penghapusan|Preview\s+Knowledge\s+Changes|Knowledge\s+Base\s+Update\s+Preview|Confirm\s+Document\s+Deletion)\*\*)|###\s*(?:Pratinjau\s+Perubahan(?:\s+Data)?|Konfirmasi\s+Penghapusan|Preview\s+Knowledge\s+Changes|Knowledge\s+Base\s+Update\s+Preview|Confirm\s+Document\s+Deletion))\s*\n+((?:[ \t]*[-*]\s*\*\*[^*]+\*\*\s*[:–-][^\n]+(?:\n|$))+)(?:[ \t]*\n+)?(?:```(?:json)?\s*(\{[\s\S]*?"action"\s*:[\s\S]*?\})\s*```)?/gi;

	interface MatchRange {
		start: number;
		end: number;
		segment: Segment;
	}

	const ranges: MatchRange[] = [];

	let m: RegExpExecArray | null;
	while ((m = cardPattern.exec(markdown)) !== null) {
		const rawImgAlt = m[1] || m[4] || "";
		const rawImgUrl = m[2] || m[5] || "";
		const headerTitle = m[3] || "";
		const isTreatment = /treatment|tindakan|prosedur|protokol/i.test(headerTitle);
		const bulletsText = m[6] || "";

		const items = parseBulletLines(bulletsText);
		const cleanImgUrl = isValidImageUrl(rawImgUrl) ? resolveImageUrl(rawImgUrl) : undefined;

		ranges.push({
			start: m.index,
			end: cardPattern.lastIndex,
			segment: {
				type: isTreatment ? "treatment-card" : "product-card",
				content: m[0],
				data: {
					imageUrl: cleanImgUrl,
					imageAlt: rawImgAlt,
					items,
				},
			},
		});
	}

	while ((m = regimenPattern.exec(markdown)) !== null) {
		const bulletsText = m[1] || "";
		const items = parseBulletLines(bulletsText);
		ranges.push({
			start: m.index,
			end: regimenPattern.lastIndex,
			segment: {
				type: "regimen-card",
				content: m[0],
				data: { items },
			},
		});
	}

	while ((m = dosDontsPattern.exec(markdown)) !== null) {
		const bulletsText = m[1] || "";
		const items = parseBulletLines(bulletsText);
		ranges.push({
			start: m.index,
			end: dosDontsPattern.lastIndex,
			segment: {
				type: "dos-donts-card",
				content: m[0],
				data: { items },
			},
		});
	}

	let mBA: RegExpExecArray | null;
	while ((mBA = beforeAfterPattern.exec(markdown)) !== null) {
		const rawImg1Alt = mBA[1] || "";
		const rawImg1Url = mBA[2] || "";
		const rawImg2Alt = mBA[3] || "";
		const rawImg2Url = mBA[4] || "";

		if (isValidImageUrl(rawImg1Url) && isValidImageUrl(rawImg2Url)) {
			const cleanImg1Url = resolveImageUrl(rawImg1Url);
			const cleanImg2Url = resolveImageUrl(rawImg2Url);

			const isImg1After = /sesudah|setelah|after/i.test(rawImg1Alt);
			const isImg2Before = /sebelum|before/i.test(rawImg2Alt);

			const beforeUrl = isImg1After && isImg2Before ? cleanImg2Url : cleanImg1Url;
			const beforeAlt = isImg1After && isImg2Before ? rawImg2Alt : rawImg1Alt;
			const afterUrl = isImg1After && isImg2Before ? cleanImg1Url : cleanImg2Url;
			const afterAlt = isImg1After && isImg2Before ? rawImg1Alt : rawImg2Alt;

			ranges.push({
				start: mBA.index,
				end: beforeAfterPattern.lastIndex,
				segment: {
					type: "before-after-card",
					content: mBA[0],
					beforeAfterData: {
						beforeImage: {
							url: beforeUrl,
							alt: beforeAlt || "Sebelum Perawatan",
						},
						afterImage: {
							url: afterUrl,
							alt: afterAlt || "Sesudah Perawatan",
						},
					},
				},
			});
		}
	}

	// Pattern 5 Parsing: SOP & Stepper
	while ((m = sopPattern.exec(markdown)) !== null) {
		const bodyText = m[1] || "";
		const lines = bodyText.split("\n");
		const preCare: string[] = [];
		const aftercare: string[] = [];
		const steps: ProcedureStep[] = [];

		let currentPhase: "pre" | "step" | "after" = "step";
		let stepCounter = 1;

		for (const rawLine of lines) {
			const line = rawLine.trim();
			if (!line) continue;

			if (
				/^(?:[-*]\s*)?\*\*(?:persiapan|pre-care|sebelum\s+tindakan)[^*]*\*\*/i.test(line) ||
				/^(?:persiapan|pre-care):/i.test(line)
			) {
				currentPhase = "pre";
				const stripped = line
					.replace(/^(?:[-*]\s*)?\*\*[^*]+\*\*\s*[:–-]?\s*/i, "")
					.replace(/^[-*]\s*/, "")
					.trim();
				if (stripped) preCare.push(stripped);
			} else if (
				/^(?:[-*]\s*)?\*\*(?:aftercare|pasca|setelah\s+tindakan)[^*]*\*\*/i.test(line) ||
				/^(?:aftercare|pasca):/i.test(line)
			) {
				currentPhase = "after";
				const stripped = line
					.replace(/^(?:[-*]\s*)?\*\*[^*]+\*\*\s*[:–-]?\s*/i, "")
					.replace(/^[-*]\s*/, "")
					.trim();
				if (stripped) aftercare.push(stripped);
			} else if (currentPhase === "pre" && (line.startsWith("-") || line.startsWith("*"))) {
				preCare.push(line.replace(/^[-*]\s*/, "").trim());
			} else if (currentPhase === "after" && (line.startsWith("-") || line.startsWith("*"))) {
				aftercare.push(line.replace(/^[-*]\s*/, "").trim());
			} else {
				currentPhase = "step";
				let num = stepCounter;
				let rem = line;

				// 1. Extract numeric or "Tahap X" prefix if present
				const numMatch = rem.match(/^(?:(\d+)[\.\)]\s*|(?:Langkah|Tahap|Step)\s*(\d+)[:\.]?\s*)/i);
				if (numMatch) {
					num = parseInt(numMatch[1] || numMatch[2] || String(stepCounter), 10);
					rem = rem.slice(numMatch[0].length).trim();
				} else {
					rem = rem.replace(/^[-*]\s*/, "").trim();
				}

				let stepTitle = "";
				let stepDesc = "";

				// 2. Check if rem starts with bold text
				const boldMatch = rem.match(/^\*\*([^*]+)\*\*\s*[:–-]?\s*(.*)$/);
				if (boldMatch) {
					stepTitle = boldMatch[1].trim();
					stepDesc = boldMatch[2].trim();
				} else {
					const colonMatch = rem.match(/^([^:–-]+)[:–-]\s*(.+)$/);
					if (colonMatch && colonMatch[1].length < 35 && !colonMatch[1].includes(".")) {
						stepTitle = colonMatch[1].trim();
						stepDesc = colonMatch[2].trim();
					} else {
						stepDesc = rem;
					}
				}

				// 3. Clean up title: strip redundant "Tahap X" or "Langkah X"
				stepTitle = stepTitle.replace(/^(?:Tahap|Langkah|Step)\s*\d+\s*[:–-]?\s*/i, "").trim();
				stepTitle = stepTitle.replace(/\*\*/g, "").trim();
				stepDesc = stepDesc.replace(/\*\*/g, "").trim();

				if (stepTitle || stepDesc) {
					steps.push({
						stepNumber: num,
						title: stepTitle,
						description: stepDesc,
					});
					stepCounter = num + 1;
				}
			}
		}

		if (steps.length > 0 || preCare.length > 0 || aftercare.length > 0) {
			ranges.push({
				start: m.index,
				end: sopPattern.lastIndex,
				segment: {
					type: "sop-card",
					content: m[0],
					sopData: {
						title: "Protokol & Tahapan Tindakan Klinis",
						preCare,
						steps,
						aftercare,
					},
				},
			});
		}
	}

	// Pattern 6 Parsing: Promo Card
	while ((m = promoPattern.exec(markdown)) !== null) {
		const bulletsText = m[1] || "";
		const items = parseBulletLines(bulletsText);
		let title = "Program Promo Spesial";
		let discount: string | undefined;
		let originalPrice: string | undefined;
		let promoPrice: string | undefined;
		let period: string | undefined;
		const terms: string[] = [];
		let notes: string | undefined;

		for (const item of items) {
			const k = item.key.toLowerCase();
			if (k.includes("judul") || k.includes("nama promo") || k.includes("program")) {
				title = item.value;
			} else if (k.includes("diskon") || k.includes("potongan") || k.includes("cashback") || k.includes("benefit")) {
				discount = item.value;
			} else if (k.includes("harga normal") || k.includes("harga awal") || k.includes("harga reguler")) {
				originalPrice = item.value;
			} else if (k.includes("harga promo") || k.includes("harga spesial") || k.includes("harga akhir")) {
				promoPrice = item.value;
			} else if (k.includes("periode") || k.includes("masa berlaku") || k.includes("validitas")) {
				period = item.value;
			} else if (k.includes("syarat") || k.includes("ketentuan") || k.includes("t&c")) {
				terms.push(...item.value.split(/[,;•]\s*/).filter(Boolean));
			} else if (k.includes("catatan") || k.includes("keterangan")) {
				notes = item.value;
			} else {
				terms.push(`${item.key}: ${item.value}`);
			}
		}

		ranges.push({
			start: m.index,
			end: promoPattern.lastIndex,
			segment: {
				type: "promo-card",
				content: m[0],
				promoData: {
					title,
					discount,
					originalPrice,
					promoPrice,
					period,
					terms,
					notes,
				},
			},
		});
	}

	// Pattern 7 Parsing: Diagnosis Card
	while ((m = diagnosisPattern.exec(markdown)) !== null) {
		const bulletsText = m[1] || "";
		const items = parseBulletLines(bulletsText);
		let primaryDiagnosis = "";
		let severity: string | undefined;
		let patientCondition: string | undefined;
		let treatment: string | undefined;
		let product: string | undefined;
		const notes: string[] = [];
		const contraindications: string[] = [];

		for (const item of items) {
			const k = item.key.toLowerCase();
			if (k.includes("diagnosis utama") || k.includes("diagnosis")) {
				primaryDiagnosis = item.value;
			} else if (k.includes("tingkat") || k.includes("severity") || k.includes("grade") || k.includes("stadium")) {
				severity = item.value;
			} else if (k.includes("kondisi") || k.includes("keluhan") || k.includes("gejala")) {
				patientCondition = item.value;
			} else if (k.includes("perawatan") || k.includes("treatment") || k.includes("tindakan")) {
				treatment = item.value;
			} else if (k.includes("produk") || k.includes("skincare") || k.includes("homecare")) {
				product = item.value;
			} else if (k.includes("kontraindikasi") || k.includes("pantangan") || k.includes("bahaya")) {
				contraindications.push(item.value);
			} else {
				notes.push(`${item.key}: ${item.value}`);
			}
		}

		if (primaryDiagnosis) {
			ranges.push({
				start: m.index,
				end: diagnosisPattern.lastIndex,
				segment: {
					type: "diagnosis-card",
					content: m[0],
					diagnosisData: {
						primaryDiagnosis,
						severity,
						patientCondition,
						treatment,
						product,
						notes,
						contraindications,
					},
				},
			});
		}
	}

	// Pattern 8 Parsing: Tiered Pricing Card
	while ((m = tieredPricingPattern.exec(markdown)) !== null) {
		const bulletsText = m[1] || "";
		const items = parseBulletLines(bulletsText);
		const tiers: PricingTier[] = [];

		for (const item of items) {
			const tierName = item.key;
			const rawVal = item.value;
			const priceMatch = rawVal.match(/^(Rp[\d\.\,]+|[\d\.\,]+)\s*(?:\(([^)]+)\))?/i);
			const price = priceMatch ? priceMatch[1] : rawVal;
			const extraInfo = priceMatch && priceMatch[2] ? priceMatch[2] : "";

			let pricePerSession: string | undefined;
			let badge: string | undefined;
			const features: string[] = [];

			if (extraInfo) {
				const parts = extraInfo.split(/[-–,]\s*/);
				for (const p of parts) {
					if (/sesi|per\s+sesi|\/sesi/i.test(p)) {
						pricePerSession = p.trim();
					} else if (/hemat|populer|best|rekomendasi|diskon/i.test(p)) {
						badge = p.trim();
					} else {
						features.push(p.trim());
					}
				}
			}

			tiers.push({
				name: tierName,
				price,
				pricePerSession,
				badge,
				features,
				isPopular: Boolean(badge) || /paket|3|5/i.test(tierName),
			});
		}

		if (tiers.length > 0) {
			ranges.push({
				start: m.index,
				end: tieredPricingPattern.lastIndex,
				segment: {
					type: "tiered-pricing-card",
					content: m[0],
					pricingData: {
						title: "Pilihan Paket & Estimasi Harga",
						tiers,
					},
				},
			});
		}
	}

	// Pattern 9 Parsing: Action Confirmation Card
	while ((m = actionConfirmationPattern.exec(markdown)) !== null) {
		const bulletsText = m[1] || "";
		const rawJson = m[2] || "";
		const items = parseBulletLines(bulletsText);

		let actionType: "edit_preview" | "delete_preview" = /hapus|delete/i.test(m[0])
			? "delete_preview"
			: "edit_preview";
		let knowledgeId: string | undefined;
		let fieldName: string | undefined;
		let newValue: string | undefined;

		if (rawJson) {
			try {
				const parsed = JSON.parse(rawJson);
				if (parsed.action) actionType = parsed.action;
				if (parsed.knowledge_id) knowledgeId = parsed.knowledge_id;
				if (parsed.field) fieldName = parsed.field;
				if (parsed.new_value) newValue = parsed.new_value;
			} catch {
				// ignore JSON parse error
			}
		}

		for (const item of items) {
			const k = item.key.toLowerCase();
			if (k.includes("knowledge id") || k.includes("id")) {
				knowledgeId = item.value;
			} else if (k.includes("bagian") || k.includes("field") || k.includes("kolom")) {
				fieldName = item.value;
			} else if (k.includes("nilai") || k.includes("value") || k.includes("baru")) {
				newValue = item.value;
			}
		}

		ranges.push({
			start: m.index,
			end: actionConfirmationPattern.lastIndex,
			segment: {
				type: "action-confirmation-card",
				content: m[0],
				actionData: {
					actionType,
					knowledgeId,
					fieldName,
					newValue,
					confirmationPrompt: "Awaiting confirmation: Click the action button below to confirm or cancel this operation.",
				},
			},
		});
	}

	// Sort ranges by start index and filter out overlapping ranges
	ranges.sort((a, b) => a.start - b.start);

	const segments: Segment[] = [];
	let lastIndex = 0;

	for (const range of ranges) {
		if (range.start < lastIndex) continue; // Skip overlaps

		if (range.start > lastIndex) {
			const beforeText = markdown.slice(lastIndex, range.start);
			if (beforeText.trim()) {
				segments.push({ type: "markdown", content: beforeText });
			}
		}

		segments.push(range.segment);
		lastIndex = range.end;
	}

	if (lastIndex < markdown.length) {
		const remainingText = markdown.slice(lastIndex);
		if (remainingText.trim()) {
			segments.push({ type: "markdown", content: remainingText });
		}
	}

	return segments.length > 0 ? segments : [{ type: "markdown", content: markdown }];
}
