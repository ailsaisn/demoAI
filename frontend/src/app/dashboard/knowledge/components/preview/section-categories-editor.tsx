"use client";

import { useCategories } from "@/app/dashboard/category/hooks/use-categories";
import type { KnowledgeChunkItem } from "@/app/dashboard/knowledge/api/types";
import { MarkdownContent } from "@/components/shared/markdown-content";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
	RiArrowDownSLine,
	RiArrowUpSLine,
	RiCloseLine,
	RiEdit2Line,
	RiSparklingLine,
} from "@remixicon/react";
import { useRef, useState } from "react";

interface SectionCategoriesEditorProps {
	chunks: KnowledgeChunkItem[];
	onChangeChunks?: (newChunks: KnowledgeChunkItem[]) => void;
	categories?: string[];
	onChangeCategories?: (newCategories: string[]) => void;
	isEditMode?: boolean;
	showSaveActions?: boolean;
}

export function SectionCategoriesEditor({
	chunks,
	onChangeChunks,
	categories = [],
	onChangeCategories,
	isEditMode = false,
	showSaveActions = true,
}: SectionCategoriesEditorProps) {
	const { data: allCategories = [] } = useCategories();
	const [isEditing, setIsEditing] = useState(isEditMode);
	const [prevIsEditMode, setPrevIsEditMode] = useState(isEditMode);

	// Local staging state for section chunks and categories
	const [localChunks, setLocalChunks] = useState<KnowledgeChunkItem[]>(chunks);
	const [backupChunks, setBackupChunks] = useState<KnowledgeChunkItem[]>(chunks);
	const [prevChunks, setPrevChunks] = useState<KnowledgeChunkItem[]>(chunks);

	// Sync local chunks when parent prop updates (e.g. background chunking finishes or switching doc)
	if (chunks !== prevChunks) {
		setPrevChunks(chunks);
		setLocalChunks(chunks);
		setBackupChunks(chunks);
	}

	// Sync local edit state with parent when prop changes
	if (isEditMode !== prevIsEditMode) {
		setPrevIsEditMode(isEditMode);
		setIsEditing(isEditMode);
		if (isEditMode) {
			setBackupChunks(localChunks);
		} else {
			setLocalChunks(chunks);
			setBackupChunks(chunks);
		}
	}

	const [expandedSections, setExpandedSections] = useState<Record<number, boolean>>({
		0: true, // Expand first section by default
	});
	const [activeInputs, setActiveInputs] = useState<Record<number, string>>({});
	const [openDropdowns, setOpenDropdowns] = useState<Record<number, boolean>>({});
	const inputRefs = useRef<Record<number, HTMLInputElement | null>>({});

	const toggleSection = (idx: number) => {
		setExpandedSections((prev) => ({
			...prev,
			[idx]: !prev[idx],
		}));
	};

	// Calculate bottom-up aggregated categories from a chunks list and top-level categories
	const deriveAggregatedCategories = (
		chunkList: KnowledgeChunkItem[],
		fallbackCats: string[] = categories,
	) => {
		const allCats = new Set<string>();
		if (Array.isArray(chunkList)) {
			for (const ch of chunkList) {
				const cList =
					ch.metadata?.categories ||
					(ch.metadata?.category ? [ch.metadata.category] : []);
				if (Array.isArray(cList)) {
					for (const c of cList) {
						if (c && typeof c === "string" && c.trim()) {
							allCats.add(c.trim());
						}
					}
				}
			}
		}
		if (Array.isArray(fallbackCats)) {
			for (const c of fallbackCats) {
				if (c && typeof c === "string" && c.trim()) {
					allCats.add(c.trim());
				}
			}
		}
		return Array.from(allCats);
	};

	const displayCategories = deriveAggregatedCategories(localChunks, categories);

	const handleAddCategory = (chunkIdx: number, catName: string) => {
		const targetChunk = localChunks[chunkIdx];
		if (!targetChunk) return;

		const currentCats =
			targetChunk.metadata?.categories ||
			(targetChunk.metadata?.category ? [targetChunk.metadata.category] : []);

		if (currentCats.includes(catName)) return;

		const nextCats = [...currentCats, catName];
		const updatedChunks = [...localChunks];
		updatedChunks[chunkIdx] = {
			...targetChunk,
			metadata: {
				...(targetChunk.metadata || {}),
				categories: nextCats,
				category: nextCats[0],
				is_custom: true,
			},
		};

		setLocalChunks(updatedChunks);
		setActiveInputs((prev) => ({ ...prev, [chunkIdx]: "" }));
		setOpenDropdowns((prev) => ({ ...prev, [chunkIdx]: false }));

		// Real-time synchronization to parent state
		const nextAggregated = deriveAggregatedCategories(updatedChunks, categories);
		onChangeChunks?.(updatedChunks);
		onChangeCategories?.(nextAggregated);
	};

	const handleRemoveCategory = (chunkIdx: number, catName: string) => {
		const targetChunk = localChunks[chunkIdx];
		if (!targetChunk) return;

		const currentCats =
			targetChunk.metadata?.categories ||
			(targetChunk.metadata?.category ? [targetChunk.metadata.category] : []);

		const nextCats = currentCats.filter((c) => c !== catName);
		const updatedChunks = [...localChunks];
		updatedChunks[chunkIdx] = {
			...targetChunk,
			metadata: {
				...(targetChunk.metadata || {}),
				categories: nextCats,
				category: nextCats.length > 0 ? nextCats[0] : undefined,
				is_custom: true,
			},
		};

		setLocalChunks(updatedChunks);

		// Real-time synchronization to parent state
		const nextAggregated = deriveAggregatedCategories(updatedChunks, categories);
		onChangeChunks?.(updatedChunks);
		onChangeCategories?.(nextAggregated);
	};

	const handleCancelCard = () => {
		setLocalChunks(backupChunks);
		const backupAggregated = deriveAggregatedCategories(backupChunks, categories);
		onChangeChunks?.(backupChunks);
		onChangeCategories?.(backupAggregated);
		setIsEditing(false);
	};

	const handleSaveCard = () => {
		const finalAggregated = deriveAggregatedCategories(localChunks, categories);
		onChangeChunks?.(localChunks);
		onChangeCategories?.(finalAggregated);
		setBackupChunks(localChunks);
		setIsEditing(false);
	};

	return (
		<div className="bg-zinc-100/50 rounded-lg p-4 w-full text-zinc-950">
			{/* Top Header: High Contrast & Original Style */}
			<div className="flex items-center justify-between gap-2 mb-2">
				<div className="flex items-center gap-2 text-blue-700">
					<RiSparklingLine className="size-5 shrink-0 text-blue-600" />
					<h3 className="font-bold text-sm text-zinc-950">Suggested Categories</h3>
				</div>
				<span className="text-xs font-mono font-semibold px-2.5 py-0.5 rounded-md bg-blue-100 border border-blue-200 text-blue-800">
					{displayCategories.length} Total
				</span>
			</div>
			<p className="text-xs text-zinc-600 font-medium mb-4">
				The AI suggests the following tags for document indexing and chatbot routing.
			</p>

			{/* 1. Overall Aggregated Document Categories Summary */}
			<div className="mb-4">
				<div className="text-[11px] font-bold text-zinc-700 uppercase tracking-wider mb-2">
					<span>Overall Categories</span>
				</div>
				<div className="flex flex-wrap gap-2 items-center min-h-8">
					{displayCategories.length > 0 ? (
						displayCategories.map((c) => (
							<div
								key={c}
								className="flex items-center bg-white border border-zinc-300 px-3 py-1.5 rounded-lg text-sm font-semibold text-zinc-900 shadow-none"
							>
								<span>{c}</span>
							</div>
						))
					) : (
						<div className="text-xs text-zinc-500 font-medium italic py-1">
							No categories assigned yet. Assign tags in the sections below.
						</div>
					)}
				</div>
			</div>

			{/* Divider */}
			<div className="h-px bg-zinc-300 my-4" />

			{/* 2. Per-Section Categorization */}
			<div className="flex flex-col gap-3">
				<div className="flex items-center justify-between">
					<h4 className="text-[11px] font-bold text-zinc-700 uppercase tracking-wider">
						Section Categories ({localChunks.length} Sections)
					</h4>
					<span className="text-[11px] text-zinc-600 font-medium">
						Edit categories per document topic
					</span>
				</div>

				{localChunks.map((chunk, idx) => {
					const isExpanded = !!expandedSections[idx];
					const chunkMeta = chunk.metadata || {};
					const sectionTitle =
						chunkMeta.section_name ||
						chunkMeta.heading ||
						(Array.isArray(chunkMeta.heading_path) && chunkMeta.heading_path.length > 0
							? chunkMeta.heading_path[chunkMeta.heading_path.length - 1]
							: typeof chunkMeta.heading_path === "string" && chunkMeta.heading_path
								? chunkMeta.heading_path
								: `Section #${idx + 1}`);

					const chunkCats =
						chunkMeta.categories || (chunkMeta.category ? [chunkMeta.category] : []);
					const availableForChunk = allCategories.filter(
						(c) => !chunkCats.includes(c.name),
					);
					const currentInput = activeInputs[idx] || "";
					const isDropdownOpen = !!openDropdowns[idx];
					const filteredCategories = availableForChunk.filter((c) =>
						c.name.toLowerCase().includes(currentInput.toLowerCase()),
					);

					const textSnippet = chunk.text;

					return (
						<div
							key={idx}
							className={`border border-zinc-300 bg-white rounded-lg transition-all shadow-none ${
								isExpanded ? "overflow-visible" : "overflow-hidden"
							}`}
						>
							{/* Section Header Toggle */}
							<div
								role="button"
								tabIndex={0}
								onClick={() => toggleSection(idx)}
								onKeyDown={(e) => {
									if (e.key === "Enter" || e.key === " ") {
										e.preventDefault();
										toggleSection(idx);
									}
								}}
								className={`w-full flex items-center justify-between p-3.5 text-left hover:bg-zinc-50 cursor-pointer transition-colors select-none focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-zinc-400 ${
									isExpanded ? "rounded-t-lg" : "rounded-lg"
								}`}
							>
								<div className="flex items-center gap-2.5 min-w-0 flex-1 mr-2">
									<span className="text-xs font-mono font-bold px-2 py-0.5 rounded bg-zinc-200 text-zinc-800 shrink-0">
										#{idx + 1}
									</span>
									<span className="text-sm font-bold text-zinc-950 truncate">
										{sectionTitle}
									</span>
								</div>

								<div className="flex items-center gap-2 shrink-0">
									<span className="text-xs text-zinc-600 font-mono font-semibold">
										{chunkCats.length} {chunkCats.length === 1 ? "tag" : "tags"}
									</span>
									{isExpanded ? (
										<RiArrowUpSLine className="size-4 text-zinc-700" />
									) : (
										<RiArrowDownSLine className="size-4 text-zinc-700" />
									)}
								</div>
							</div>

							{/* Section Content: Context Excerpt & Tags */}
							{isExpanded && (
								<div className="border-t border-zinc-200 p-4 bg-zinc-50/60 flex flex-col gap-3 rounded-b-lg">
									{/* Formatted Context Snippet with comfortable height */}
									<div className="bg-white border border-zinc-200 rounded-md p-3.5 text-xs sm:text-sm text-zinc-800 leading-relaxed max-h-80 overflow-y-auto">
										<MarkdownContent content={textSnippet} />
									</div>

									{/* Tag Chips & Searchable Input */}
									<div className="flex flex-wrap gap-2 items-center">
										{chunkCats.map((c) => (
											<div
												key={c}
												className="flex items-center gap-1.5 bg-white border border-zinc-300 px-3 py-1.5 rounded-lg text-sm font-semibold text-zinc-900 shadow-none"
											>
												<span>{c}</span>
												{isEditing && (
													<button
														type="button"
														onClick={() => handleRemoveCategory(idx, c)}
														className="text-zinc-500 hover:text-red-600 hover:bg-red-50 p-0.5 rounded transition-colors cursor-pointer"
														title="Remove category"
													>
														<RiCloseLine className="size-4" />
													</button>
												)}
											</div>
										))}

										{isEditing && (
											<div className="relative flex-1 min-w-52 max-w-80">
												<Input
													id={`chunk-cat-input-${idx}`}
													ref={(el) => {
														inputRefs.current[idx] = el;
													}}
													value={currentInput}
													onChange={(e) => {
														const val = e.target.value;
														setActiveInputs((prev) => ({ ...prev, [idx]: val }));
														setOpenDropdowns((prev) => ({ ...prev, [idx]: true }));
													}}
													onFocus={() => {
														setOpenDropdowns((prev) => ({ ...prev, [idx]: true }));
													}}
													onClick={() => {
														setOpenDropdowns((prev) => ({ ...prev, [idx]: true }));
													}}
													onBlur={() => {
														setTimeout(() => {
															setOpenDropdowns((prev) => ({
																...prev,
																[idx]: false,
															}));
														}, 200);
													}}
													placeholder="Type or select category..."
													className="border-zinc-300 bg-white focus-visible:border-zinc-400 focus-visible:ring-0 focus-visible:outline-none shadow-none h-9 text-sm font-medium text-zinc-900 rounded-lg placeholder:text-zinc-500"
												/>
												{isDropdownOpen && (
													<div className="absolute top-full left-0 mt-1.5 w-full bg-white border border-zinc-300 rounded-lg shadow-none p-1.5 max-h-56 overflow-y-auto z-50">
														{filteredCategories.length > 0 ? (
															<div className="flex flex-col gap-0.5">
																{filteredCategories.map((cat) => (
																	<div
																		key={cat.id}
																		role="button"
																		tabIndex={0}
																		onMouseDown={(e) => {
																			e.preventDefault();
																			handleAddCategory(idx, cat.name);
																		}}
																		className="px-3 py-2 text-sm font-medium text-zinc-900 hover:bg-zinc-100 hover:text-zinc-950 cursor-pointer rounded-md transition-colors"
																	>
																		{cat.name}
																	</div>
																))}
															</div>
														) : (
															<div className="px-3 py-2 text-xs font-medium text-zinc-500 text-center">
																No matching categories found in DB
															</div>
														)}
													</div>
												)}
											</div>
										)}
									</div>
								</div>
							)}
						</div>
					);
				})}
			</div>

			{/* Edit Categories Action Button */}
			{!isEditing && isEditMode && (
				<Button
					variant="outline"
					className="w-fit mt-4 border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-100 font-semibold rounded-lg px-4 h-9 text-sm transition-colors cursor-pointer shadow-none gap-2"
					onClick={() => setIsEditing(true)}
				>
					<RiEdit2Line className="size-4 text-zinc-700" />
					Edit Categories
				</Button>
			)}

			{isEditing && showSaveActions && (
				<div className="mt-6 flex flex-col gap-3">
					<p className="text-sm text-zinc-800 font-semibold">Are these categories accurate?</p>
					<div className="flex items-center gap-2">
						<Button
							type="button"
							variant="outline"
							onClick={handleCancelCard}
							className="border-zinc-300 bg-white text-zinc-800 hover:bg-zinc-100 font-semibold rounded-lg px-4 h-10 text-sm transition-colors cursor-pointer shadow-none"
						>
							Cancel
						</Button>
						<Button
							type="button"
							className="bg-blue-600 hover:bg-blue-700 text-white font-semibold rounded-lg px-4 h-10 text-sm transition-colors cursor-pointer shadow-none"
							onClick={handleSaveCard}
						>
							Save Categories
						</Button>
					</div>
				</div>
			)}
		</div>
	);
}
