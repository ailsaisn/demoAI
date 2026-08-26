"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import {
	DropdownMenu,
	DropdownMenuTrigger,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuRadioGroup,
	DropdownMenuRadioItem,
} from "@/components/ui/dropdown-menu";
import {
	RiBookOpenLine,
	RiBookletLine,
	RiDatabase2Line,
	RiEyeLine,
	RiFilterOffLine,
	RiLoader4Line,
	RiMoneyDollarCircleLine,
	RiCloseLine,
	RiMore2Line,
	RiDeleteBinLine,
} from "@remixicon/react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { toast } from "sonner";
import { useKnowledgeBaseList, useDeleteKnowledge } from "../../../app/dashboard/knowledge/hooks/use-knowledge";
import { useCategories } from "../../../app/dashboard/category/hooks/use-categories";
import { KnowledgeResponse } from "@/app/dashboard/knowledge/api/types";
import { AttachProjectDialog } from "@/app/dashboard/knowledge/components/attach-project-dialog";
import { ConfirmationModal } from "@/components/shared/knowledge/ConfirmationModal";

interface DisplayRowItem {
	id: string;
	isBatch: boolean;
	batchId?: string;
	title: string;
	status: string;
	created_at?: string;
	description: string;
	documentCount?: number;
	rawItem: KnowledgeResponse;
	allFileNames: string[];
	categories: string[];
	projectId?: string | null;
	allDocIds?: string[];
}

interface KnowledgeTableProps {
	searchQuery?: string;
	selectedProjectId?: string | null;
	onClearProjectFilter?: () => void;
}

export function KnowledgeTable({
	searchQuery = "",
	selectedProjectId,
	onClearProjectFilter,
}: KnowledgeTableProps) {
	const router = useRouter();
	const [statusFilter, setStatusFilter] = useState("ALL");
	const [categoryFilter, setCategoryFilter] = useState("ALL");
	const { data: knowledgeList, isLoading, isError } = useKnowledgeBaseList();
	const { data: availableCategories = [] } = useCategories();
	const deleteMutation = useDeleteKnowledge();

	// Delete Confirmation Modal State
	const [deleteModalOpen, setDeleteModalOpen] = useState(false);
	const [itemToDelete, setItemToDelete] = useState<DisplayRowItem | null>(null);

	// Attach Project Modal State
	const [isAttachModalOpen, setIsAttachModalOpen] = useState(false);
	const [attachKnowledgeId, setAttachKnowledgeId] = useState<string | null>(null);
	const [attachKnowledgeIds, setAttachKnowledgeIds] = useState<string[] | undefined>(undefined);
	const [attachKnowledgeTitle, setAttachKnowledgeTitle] = useState("");
	const [attachCurrentProjectId, setAttachCurrentProjectId] = useState<string | null>(null);

	const basePath = "/dashboard/knowledge";

	const handleDeleteClick = (row: DisplayRowItem, e: React.MouseEvent) => {
		e.stopPropagation();
		setItemToDelete(row);
		setDeleteModalOpen(true);
	};

	const handleConfirmDelete = async () => {
		if (itemToDelete) {
			const idsToDelete =
				itemToDelete.allDocIds && itemToDelete.allDocIds.length > 0
					? itemToDelete.allDocIds
					: [itemToDelete.id];

			try {
				if (idsToDelete.length > 1) {
					await Promise.all(
						idsToDelete.map((id) => deleteMutation.mutateAsync({ id, hideToast: true })),
					);
					toast.success(`All ${idsToDelete.length} documents deleted successfully!`);
				} else {
					await deleteMutation.mutateAsync(idsToDelete[0]);
				}
			} catch {
				// handled by mutation
			}
			setDeleteModalOpen(false);
			setItemToDelete(null);
		}
	};

	const handleRowClick = (row: DisplayRowItem) => {
		if (row.isBatch && row.batchId) {
			router.push(`${basePath}/batch/${row.batchId}`);
		} else {
			router.push(`${basePath}/${row.id}`);
		}
	};

	const isCategoryMatch = (itemCategories: string[], filterCat: string) => {
		if (!filterCat || filterCat === "ALL") return true;
		const target = filterCat.toLowerCase();
		return itemCategories.some(
			(c) => c.toLowerCase() === target || c.toLowerCase().includes(target),
		);
	};

	// Group knowledgeList by batch_id if present and collect categories
	const displayRows = useMemo<DisplayRowItem[]>(() => {
		if (!knowledgeList) return [];

		const batchMap = new Map<string, KnowledgeResponse[]>();
		const singleItems: KnowledgeResponse[] = [];

		for (const item of knowledgeList) {
			const bId = (item.metadata?.batch_id || item.metadata?.upload_batch_id) as string | undefined;
			if (bId) {
				const existing = batchMap.get(bId) || [];
				existing.push(item);
				batchMap.set(bId, existing);
			} else {
				singleItems.push(item);
			}
		}

		const rows: DisplayRowItem[] = [];

		const extractCategories = (doc: KnowledgeResponse): string[] => {
			const catSet = new Set<string>();
			const rawList = (doc.metadata?.categories as string[]) || [];
			const suggested =
				(doc.metadata?.suggested_categories as Array<{ name: string } | string>) || [];
			for (const c of rawList) {
				if (typeof c === "string" && c.trim()) catSet.add(c.trim());
			}
			for (const s of suggested) {
				if (typeof s === "string" && s.trim()) {
					catSet.add(s.trim());
				} else if (
					s &&
					typeof s === "object" &&
					"name" in s &&
					typeof (s as { name: unknown }).name === "string" &&
					(s as { name: string }).name.trim()
				) {
					catSet.add((s as { name: string }).name.trim());
				}
			}
			return Array.from(catSet);
		};

		// 1. Process Batch Groups
		for (const [batchId, docs] of batchMap.entries()) {
			const combinedCategories = Array.from(
				new Set(docs.flatMap((d) => extractCategories(d))),
			);

			if (docs.length === 1) {
				const doc = docs[0];
				rows.push({
					id: doc.id,
					isBatch: true,
					batchId,
					title: doc.title || doc.file_name,
					status: doc.status,
					created_at: doc.created_at,
					description: doc.ai_summary || doc.content || "No description available.",
					documentCount: 1,
					rawItem: doc,
					allFileNames: [doc.file_name],
					categories: combinedCategories,
					projectId: doc.project_id,
					allDocIds: [doc.id],
				});
			} else {
				let aggStatus = "APPROVED";
				const hasProcessing = docs.some((d) => d.status === "PROCESSING");
				const hasPending = docs.some((d) => d.status === "PENDING");
				const hasRejected = docs.some((d) => d.status === "REJECTED");

				if (hasProcessing) {
					aggStatus = "PROCESSING";
				} else if (hasPending) {
					aggStatus = "PENDING";
				} else if (docs.every((d) => d.status === "APPROVED")) {
					aggStatus = "APPROVED";
				} else if (hasRejected) {
					aggStatus = "REJECTED";
				} else {
					aggStatus = docs[0].status;
				}

				const batchSummary =
					(docs[0].metadata?.batch_summary as string) || docs[0].ai_summary || "";
				const allNames = docs.map((d) => d.file_name || d.title);
				const firstDocTitle = docs[0].title || docs[0].file_name;
				const displayTitle = `${firstDocTitle} + ${docs.length - 1} more`;

				const mostRecentDate = docs.reduce((latest, d) => {
					if (!latest) return d.created_at;
					if (!d.created_at) return latest;
					return new Date(d.created_at) > new Date(latest) ? d.created_at : latest;
				}, docs[0].created_at);

				rows.push({
					id: docs[0].id,
					isBatch: true,
					batchId,
					title: displayTitle,
					status: aggStatus,
					created_at: mostRecentDate,
					description: batchSummary || `Batch upload containing ${docs.length} documents.`,
					documentCount: docs.length,
					rawItem: docs[0],
					allFileNames: allNames,
					categories: combinedCategories,
					projectId: docs[0].project_id,
					allDocIds: docs.map((d) => d.id),
				});
			}
		}

		// 2. Process Standalone Items
		for (const doc of singleItems) {
			rows.push({
				id: doc.id,
				isBatch: false,
				title: doc.title || doc.file_name,
				status: doc.status,
				created_at: doc.created_at,
				description: doc.ai_summary || doc.content || "No description available.",
				documentCount: 1,
				rawItem: doc,
				allFileNames: [doc.file_name],
				categories: extractCategories(doc),
				projectId: doc.project_id,
				allDocIds: [doc.id],
			});
		}

		return rows;
	}, [knowledgeList]);

	const hasActiveFilters = statusFilter !== "ALL" || categoryFilter !== "ALL" || !!selectedProjectId;

	const handleResetFilters = () => {
		setStatusFilter("ALL");
		setCategoryFilter("ALL");
		if (onClearProjectFilter) onClearProjectFilter();
	};

	const filteredList = displayRows
		?.filter((item) => (selectedProjectId ? item.projectId === selectedProjectId : true))
		?.filter((item) => (statusFilter !== "ALL" ? item.status === statusFilter : true))
		?.filter((item) => isCategoryMatch(item.categories, categoryFilter))
		?.filter(
			(item) =>
				item.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
				item.allFileNames.some((f) => f.toLowerCase().includes(searchQuery.toLowerCase())) ||
				item.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
				item.categories.some((c) => c.toLowerCase().includes(searchQuery.toLowerCase())),
		)
		.sort((a, b) => {
			const timeA = a.created_at ? new Date(a.created_at).getTime() : 0;
			const timeB = b.created_at ? new Date(b.created_at).getTime() : 0;
			return timeB - timeA;
		});

	const getStatusBadge = (status: string) => {
		switch (status) {
			case "APPROVED":
				return (
					<Badge className="bg-emerald-50 text-emerald-700 border-emerald-200 hover:bg-emerald-50">
						APPROVED
					</Badge>
				);
			case "PENDING":
				return (
					<Badge className="bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-50">
						PENDING
					</Badge>
				);
			case "PROCESSING":
				return (
					<Badge className="bg-blue-50 text-blue-700 border-blue-200 animate-pulse hover:bg-blue-50">
						PROCESSING
					</Badge>
				);
			case "REJECTED":
				return (
					<Badge className="bg-red-50 text-red-700 border-red-200 hover:bg-red-50">REJECTED</Badge>
				);
			default:
				return <Badge variant="secondary">{status}</Badge>;
		}
	};

	return (
		<div className="w-full">
			{/* Header / Filters Bar */}
			<div className="flex flex-wrap items-center justify-between gap-3 mb-3">
				<h3 className="text-base font-semibold text-gray-900">Knowledge List</h3>

				<div className="flex flex-wrap items-center gap-2.5">
					{/* Active Project Filter Badge */}
					{selectedProjectId && (
						<div className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-blue-50 border border-blue-200 text-xs font-medium text-blue-700">
							<span>Project Filter Active</span>
							<button
								type="button"
								onClick={onClearProjectFilter}
								className="hover:text-blue-900 cursor-pointer"
							>
								<RiCloseLine className="size-3.5" />
							</button>
						</div>
					)}

					{/* Reset Filters button */}
					{hasActiveFilters && (
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={handleResetFilters}
							className="text-xs text-red-600 hover:text-red-700 bg-white hover:bg-red-50 border-red-200 hover:border-red-300 rounded-lg cursor-pointer h-9 px-3 gap-1.5 shadow-none transition-colors"
						>
							<RiFilterOffLine className="size-3.5 text-red-500" />
							Reset
						</Button>
					)}

					{/* Category Filter */}
					<DropdownMenu>
						<DropdownMenuTrigger
							render={
								<Button
									variant="outline"
									className="min-w-44 justify-start gap-2 bg-white font-normal text-gray-700 hover:bg-gray-50 border-gray-200 shadow-none cursor-pointer"
								/>
							}
						>
							<RiDatabase2Line className="size-4 shrink-0 text-gray-500" />
							<span className="truncate">
								{categoryFilter === "ALL" ? "All Categories" : categoryFilter}
							</span>
						</DropdownMenuTrigger>
						<DropdownMenuContent className="w-56 max-h-80 overflow-y-auto rounded-lg border border-gray-200 shadow-none p-1 bg-white">
							<DropdownMenuRadioGroup value={categoryFilter} onValueChange={setCategoryFilter}>
								<DropdownMenuRadioItem closeOnClick value="ALL">
									All Categories
								</DropdownMenuRadioItem>
								{availableCategories.map((cat) => (
									<DropdownMenuRadioItem key={cat.id} closeOnClick value={cat.name}>
										{cat.name}
									</DropdownMenuRadioItem>
								))}
							</DropdownMenuRadioGroup>
						</DropdownMenuContent>
					</DropdownMenu>

					{/* Status Filter */}
					<DropdownMenu>
						<DropdownMenuTrigger
							render={
								<Button
									variant="outline"
									className="min-w-36 justify-start gap-2 bg-white font-normal text-gray-700 hover:bg-gray-50 border-gray-200 shadow-none cursor-pointer"
								/>
							}
						>
							<RiMoneyDollarCircleLine className="size-4 shrink-0 text-gray-500" />
							<span className="truncate">
								{statusFilter === "ALL"
									? "All Status"
									: statusFilter.charAt(0) + statusFilter.slice(1).toLowerCase()}
							</span>
						</DropdownMenuTrigger>
						<DropdownMenuContent className="w-44 rounded-lg border border-gray-200 shadow-none p-1 bg-white">
							<DropdownMenuRadioGroup value={statusFilter} onValueChange={setStatusFilter}>
								<DropdownMenuRadioItem closeOnClick value="ALL">
									All Status
								</DropdownMenuRadioItem>
								<DropdownMenuRadioItem closeOnClick value="APPROVED">
									Approved
								</DropdownMenuRadioItem>
								<DropdownMenuRadioItem closeOnClick value="PENDING">
									Pending
								</DropdownMenuRadioItem>
								<DropdownMenuRadioItem closeOnClick value="PROCESSING">
									Processing
								</DropdownMenuRadioItem>
								<DropdownMenuRadioItem closeOnClick value="REJECTED">
									Rejected
								</DropdownMenuRadioItem>
							</DropdownMenuRadioGroup>
						</DropdownMenuContent>
					</DropdownMenu>
				</div>
			</div>

			{/* Table */}
			<div className="border border-gray-200 rounded-lg bg-white overflow-hidden shadow-none">
				<Table className="[&_tr]:border-gray-100">
					<TableHeader className="bg-gray-50/50">
						<TableRow className="bg-gray-50/50 hover:bg-gray-50/50">
							<TableHead className="w-62.5 font-medium text-gray-700">Knowledge Title</TableHead>
							<TableHead className="w-37.5 font-medium text-gray-700">Category</TableHead>
							<TableHead className="w-35 font-medium text-gray-700">Date</TableHead>
							<TableHead className="font-medium text-gray-700">Description</TableHead>
							<TableHead className="w-30 font-medium text-gray-700">Status</TableHead>
							<TableHead className="w-30 font-medium text-gray-700 text-right">Actions</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{isLoading && (
							<TableRow>
								<TableCell colSpan={6} className="text-center py-8 text-gray-500">
									<div className="flex items-center justify-center">
										<RiLoader4Line className="w-5 h-5 animate-spin mr-2" />
										Loading knowledge base...
									</div>
								</TableCell>
							</TableRow>
						)}

						{isError && (
							<TableRow>
								<TableCell colSpan={6} className="text-center py-8 text-red-500">
									Failed to load knowledge base documents.
								</TableCell>
							</TableRow>
						)}

						{!isLoading && !isError && filteredList?.length === 0 && (
							<TableRow>
								<TableCell colSpan={6} className="text-center py-12 text-gray-500">
									<div className="flex flex-col items-center justify-center gap-2">
										<p className="text-sm">No knowledge base documents matching your filters.</p>
										{hasActiveFilters && (
											<Button
												type="button"
												variant="outline"
												size="sm"
												onClick={handleResetFilters}
												className="mt-1 text-xs cursor-pointer"
											>
												Clear all filters
											</Button>
										)}
									</div>
								</TableCell>
							</TableRow>
						)}

						{!isLoading &&
							filteredList?.map((row) => (
								<TableRow
									key={row.isBatch ? `batch-${row.batchId}` : `doc-${row.id}`}
									className="hover:bg-gray-50/60 cursor-pointer"
									onClick={() => handleRowClick(row)}
								>
									<TableCell>
										<div className="flex items-center gap-2 min-w-0 max-w-50 sm:max-w-62.5">
											{row.isBatch && row.documentCount && row.documentCount > 1 ? (
												<RiBookletLine className="size-4 shrink-0 text-gray-600" />
											) : (
												<RiBookOpenLine className="size-4 shrink-0 text-gray-600" />
											)}
											<span
												className="font-medium text-gray-900 truncate"
												title={row.title || undefined}
											>
												{row.title}
											</span>
											{row.isBatch && row.documentCount && row.documentCount > 1 && (
												<Badge
													variant="secondary"
													className="bg-blue-50 text-blue-700 border-blue-200 text-[10px] px-1.5 py-0 shrink-0 font-normal rounded-lg"
												>
													{row.documentCount} files
												</Badge>
											)}
										</div>
									</TableCell>
									<TableCell>
										<div className="flex flex-wrap items-center gap-1">
											{row.categories.length > 0 ? (
												<>
													{row.categories.slice(0, 2).map((cat, idx) => (
														<Badge
															key={idx}
															variant="secondary"
															className="bg-gray-100 text-gray-700 hover:bg-gray-100 rounded-lg"
														>
															{cat}
														</Badge>
													))}
													{row.categories.length > 2 && (
														<Badge
															variant="secondary"
															className="bg-gray-100 text-gray-500 hover:bg-gray-200 text-[11px] px-1.5 py-0 rounded-lg cursor-default"
															title={row.categories.slice(2).join(", ")}
														>
															+{row.categories.length - 2}
														</Badge>
													)}
												</>
											) : (
												<span className="text-xs text-gray-400">-</span>
											)}
										</div>
									</TableCell>
									<TableCell className="whitespace-nowrap text-sm text-gray-500">
										{row.created_at
											? new Date(row.created_at).toLocaleDateString("en-GB", {
													day: "2-digit",
													month: "short",
													year: "numeric",
												})
											: "-"}
									</TableCell>
									<TableCell className="max-w-xl">
										<p
											className="text-sm text-gray-600 truncate"
											title={row.description || undefined}
										>
											{row.description}
										</p>
									</TableCell>
									<TableCell>{getStatusBadge(row.status)}</TableCell>
									<TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
										<div className="flex justify-end items-center">
											<DropdownMenu>
												<DropdownMenuTrigger
													render={
														<Button
															variant="ghost"
															size="icon"
															className="size-8 text-gray-500 hover:text-gray-900"
														>
															<RiMore2Line className="size-4" />
														</Button>
													}
												/>
												<DropdownMenuContent align="end" className="w-40 bg-white border-gray-200">
													<DropdownMenuItem
														onClick={() => handleRowClick(row)}
														className="text-xs text-gray-700 cursor-pointer"
													>
														<RiEyeLine className="size-3.5 mr-2" />
														<span>View Details</span>
													</DropdownMenuItem>
													<DropdownMenuItem
														onClick={() => {
															setAttachKnowledgeId(row.id);
															setAttachKnowledgeIds(row.allDocIds || [row.id]);
															setAttachKnowledgeTitle(row.title);
															setAttachCurrentProjectId(row.projectId || row.rawItem?.project_id || null);
															setIsAttachModalOpen(true);
														}}
														className="text-xs text-gray-700 cursor-pointer"
													>
														<RiBookOpenLine className="size-3.5 mr-2" />
														<span>Attach to Project</span>
													</DropdownMenuItem>
													<DropdownMenuItem
														onClick={(e) => handleDeleteClick(row, e)}
														className="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 cursor-pointer"
													>
														<RiDeleteBinLine className="size-3.5 mr-2" />
														<span>Delete</span>
													</DropdownMenuItem>
												</DropdownMenuContent>
											</DropdownMenu>
										</div>
									</TableCell>
								</TableRow>
							))}
					</TableBody>
				</Table>
			</div>

			<AttachProjectDialog
				isOpen={isAttachModalOpen}
				onClose={() => setIsAttachModalOpen(false)}
				knowledgeId={attachKnowledgeId}
				knowledgeIds={attachKnowledgeIds}
				knowledgeTitle={attachKnowledgeTitle}
				currentProjectId={attachCurrentProjectId}
			/>

			<ConfirmationModal
				isOpen={deleteModalOpen}
				onOpenChange={setDeleteModalOpen}
				title="Delete Knowledge"
				description={`Are you sure you want to delete "${itemToDelete?.title}"? This action cannot be undone.`}
				confirmText="Delete Knowledge"
				cancelText="Cancel"
				variant="destructive"
				isLoading={deleteMutation.isPending}
				onConfirm={handleConfirmDelete}
			/>
		</div>
	);
}
