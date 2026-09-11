import React, { useState } from "react";
import { RiImageLine, RiZoomInLine } from "@remixicon/react";
import type { CardData, KeyValueItem } from "../types";
import { isValidImageUrl, resolveImageUrl } from "../utils";
import { ImagePreviewDialog } from "@/components/shared/image-preview-dialog";

export function ProductCard({ data }: { data: CardData }) {
	const [isPreviewOpen, setIsPreviewOpen] = useState(false);
	const { imageUrl, imageAlt, items } = data;

	let productName = "";
	let brand = "";
	let variant = "";
	let productType = "";
	let skinTypes = "";
	let netContent = "";
	let price = "";
	let sku = "";
	let bpom = "";
	let texture = "";
	let usage = "";
	let ageGroup = "";
	let sideEffects = "";
	const otherItems: KeyValueItem[] = [];

	for (const item of items) {
		const k = item.key.toLowerCase();
		if (k.includes("product name") || k.includes("nama produk")) {
			productName = item.value;
		} else if (k.includes("brand") || k.includes("merek")) {
			brand = item.value;
		} else if (k.includes("variant") || k.includes("varian")) {
			variant = item.value;
		} else if (
			k.includes("product type") ||
			k.includes("tipe produk") ||
			k.includes("jenis produk")
		) {
			productType = item.value;
		} else if (
			k.includes("skin type") ||
			k.includes("jenis kulit") ||
			k.includes("target kondisi")
		) {
			skinTypes = item.value;
		} else if (
			k.includes("net content") ||
			k.includes("berat bersih") ||
			k.includes("volume") ||
			k.includes("isi bersih")
		) {
			netContent = item.value;
		} else if (k.includes("harga") || k.includes("price")) {
			price = item.value;
		} else if (k.includes("sku") || k.includes("kode sku")) {
			sku = item.value;
		} else if (k.includes("bpom") || k.includes("registrasi")) {
			bpom = item.value;
		} else if (k.includes("tekstur") || k.includes("texture") || k.includes("sediaan")) {
			texture = item.value;
		} else if (k.includes("aturan pakai") || k.includes("cara pakai") || k.includes("dosis")) {
			usage = item.value;
		} else if (k.includes("target usia") || k.includes("usia") || k.includes("age")) {
			ageGroup = item.value;
		} else if (k.includes("efek samping") || k.includes("side effect")) {
			sideEffects = item.value;
		} else {
			otherItems.push(item);
		}
	}

	const cleanImgUrl = imageUrl && isValidImageUrl(imageUrl) ? resolveImageUrl(imageUrl) : undefined;

	return (
		<div className="not-prose my-2.5 rounded-lg border border-zinc-200/80 bg-white p-3.5 flex flex-col sm:flex-row gap-3.5 items-start shadow-none">
			{cleanImgUrl && (
				<>
					<div
						className="size-28 sm:size-32 shrink-0 bg-zinc-50 rounded-lg border border-zinc-200/80 p-2 flex items-center justify-center overflow-hidden relative group cursor-pointer"
						onClick={() => setIsPreviewOpen(true)}
					>
						{/* eslint-disable-next-line @next/next/no-img-element */}
						<img
							src={cleanImgUrl}
							alt={imageAlt || productName || "Product"}
							className="size-full object-contain"
							loading="lazy"
							onError={(e) => {
								e.currentTarget.style.display = "none";
								const fallback = e.currentTarget.nextElementSibling as HTMLElement;
								if (fallback) fallback.style.display = "flex";
							}}
						/>
						<span
							style={{ display: "none" }}
							className="size-full bg-zinc-100 items-center justify-center text-zinc-400 text-xs flex-col p-1 text-center select-none"
						>
							<RiImageLine className="size-5 text-zinc-400 mb-0.5" />
							<span className="text-xs text-zinc-400 font-medium">N/A</span>
						</span>
						<button
							type="button"
							onClick={(e) => {
								e.stopPropagation();
								setIsPreviewOpen(true);
							}}
							className="absolute bottom-1.5 right-1.5 p-1 rounded-md bg-white/95 text-zinc-600 border border-zinc-200/80 opacity-0 group-hover:opacity-100 transition-opacity shadow-xs cursor-pointer"
							title="View image"
						>
							<RiZoomInLine className="size-3.5" />
						</button>
					</div>

					<ImagePreviewDialog
						src={cleanImgUrl}
						alt={productName || imageAlt || "Product"}
						isOpen={isPreviewOpen}
						onOpenChange={setIsPreviewOpen}
					/>
				</>
			)}

			<div className="flex-1 min-w-0 flex flex-col justify-between self-stretch">
				<div className="flex flex-col gap-1 text-xs sm:text-sm text-zinc-900 leading-normal">
					{/* 1. Product Title */}
					{productName && (
						<h4 className="text-sm font-semibold text-zinc-950 leading-snug tracking-tight">
							{productName}
						</h4>
					)}

					{/* 2. Brand / Product Type / Variant Badges */}
					{(brand || productType || variant) && (
						<div className="flex items-center gap-1.5 flex-wrap my-0.5">
							{brand && (
								<span className="text-xs font-medium text-zinc-800 bg-zinc-100 px-2 py-0.5 rounded border border-zinc-200">
									{brand}
								</span>
							)}
							{productType && (
								<span className="text-xs font-normal text-zinc-700 bg-zinc-100 px-2 py-0.5 rounded border border-zinc-200/80">
									{productType}
								</span>
							)}
							{variant && (
								<span className="text-xs font-normal text-zinc-700 bg-zinc-100 px-2 py-0.5 rounded border border-zinc-200/80">
									{variant}
								</span>
							)}
						</div>
					)}

					{/* 3. Net Content */}
					{netContent && (
						<div>
							<span className="text-zinc-500 font-medium">Net Content:</span>{" "}
							<span className="text-zinc-900 font-normal">{netContent}</span>
						</div>
					)}

					{/* 4. Skin Types */}
					{skinTypes && (
						<div>
							<span className="text-zinc-500 font-medium">Skin Types:</span>{" "}
							<span className="text-zinc-900 font-normal">{skinTypes}</span>
						</div>
					)}

					{/* 5. Tekstur / Sediaan */}
					{texture && (
						<div>
							<span className="text-zinc-500 font-medium">Tekstur:</span>{" "}
							<span className="text-zinc-900 font-normal">{texture}</span>
						</div>
					)}

					{/* 6. Aturan Pakai */}
					{usage && (
						<div>
							<span className="text-zinc-500 font-medium">Aturan Pakai:</span>{" "}
							<span className="text-zinc-900 font-normal">{usage}</span>
						</div>
					)}

					{/* 7. Target Usia */}
					{ageGroup && (
						<div>
							<span className="text-zinc-500 font-medium">Target Usia:</span>{" "}
							<span className="text-zinc-900 font-normal">{ageGroup}</span>
						</div>
					)}

					{/* 8. No BPOM */}
					{bpom && (
						<div>
							<span className="text-zinc-500 font-medium">No BPOM:</span>{" "}
							<span className="font-mono text-zinc-800 text-xs bg-zinc-100 px-1.5 py-0.5 rounded border border-zinc-200">
								{bpom}
							</span>
						</div>
					)}

					{/* 9. Efek Samping */}
					{sideEffects && (
						<div>
							<span className="text-zinc-500 font-medium">Efek Samping:</span>{" "}
							<span className="text-zinc-900 font-normal">{sideEffects}</span>
						</div>
					)}

					{/* 10. Other custom items */}
					{otherItems.map((item, idx) => (
						<div key={idx}>
							<span className="text-zinc-500 font-medium">{item.key}:</span>{" "}
							<span className="text-zinc-900 font-normal">{item.value}</span>
						</div>
					))}
				</div>

				{/* Price & SKU footer */}
				{(price || sku) && (
					<div className="mt-2 pt-1 border-t border-zinc-100 flex items-center justify-between flex-wrap gap-2">
						{price && <span className="text-sm font-bold text-zinc-950">{price}</span>}
						{sku && <span className="text-xs font-mono font-normal text-zinc-500">SKU: {sku}</span>}
					</div>
				)}
			</div>
		</div>
	);
}
