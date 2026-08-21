"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SearchBar } from "@/components/shared/search-bar";
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
} from "@remixicon/react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useKnowledgeBaseList } from "../../../app/dashboard/knowledge/hooks/use-knowledge";
import { useCategories } from "../../../app/dashboard/category/hooks/use-categories";
import { KnowledgeResponse } from "@/app/dashboard/knowledge/api/types";

interface DisplayRowItem {
	id: string;
	isBatch: boolean;
	batchId?: string;
	title: string;
	type: string;
	status: string;
	created_at?: string;
	description: string;
	documentCount?: number;
	rawItem: KnowledgeResponse;
	allFileNames: string[];
	categories: string[];
}

export function KnowledgeTable({ type = "PRODUCT" }: { type?: string }) {
	const router = useRouter();
	const [searchQuery, setSearchQuery] = useState("");
	const [statusFilter, setStatusFilter] = useState("ALL");
	const [categoryFilter, setCategoryFilter] = useState("ALL");
	const { data: knowledgeList, isLoading, isError } = useKnowledgeBaseList();
	const { data: availableCategories = [] } = useCategories();

	const basePath = "/dashboard/knowledge";

	const handleRowClick = (row: DisplayRowItem) => {
		if (row.isBatch && row.batchId) {
			router.push(`${basePath}/batch/${row.batchId}`);
		} else {
			router.push(`${basePath}/${row.id}`);
		}
	};

	const isTypeMatch = (itemType?: string, filterType?: string) => {
		if (!filterType || filterType === "ALL") return true;
		const normItem = itemType?.toUpperCase();
		const normFilter = filterType?.toUpperCase();
		if (normItem === normFilter) return true;
		if (
			(normFilter === "OTHER" || normFilter === "GENERAL") &&
			(normItem === "OTHER" || normItem === "GENERAL")
		) {
			return true;
		}
		return false;
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
			if (doc.type) catSet.add(doc.type);
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
					type: doc.type,
					status: doc.status,
					created_at: doc.created_at,
					description: doc.ai_summary || doc.content || "No description available.",
					documentCount: 1,
					rawItem: doc,
					allFileNames: [doc.file_name],
					categories: combinedCategories,
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
					type: docs[0].type,
					status: aggStatus,
					created_at: mostRecentDate,
					description: batchSummary || `Batch upload containing ${docs.length} documents.`,
					documentCount: docs.length,
					rawItem: docs[0],
					allFileNames: allNames,
					categories: combinedCategories,
				});
			}
		}

		// 2. Process Standalone Items
		for (const doc of singleItems) {
			rows.push({
				id: doc.id,
				isBatch: false,
				title: doc.title || doc.file_name,
				type: doc.type,
				status: doc.status,
				created_at: doc.created_at,
				description: doc.ai_summary || doc.content || "No description available.",
				documentCount: 1,
				rawItem: doc,
				allFileNames: [doc.file_name],
				categories: extractCategories(doc),
			});
		}

		return rows;
	}, [knowledgeList]);

	const hasActiveFilters =
		searchQuery.trim() !== "" || statusFilter !== "ALL" || categoryFilter !== "ALL";

	const handleResetFilters = () => {
		setSearchQuery("");
		setStatusFilter("ALL");
		setCategoryFilter("ALL");
	};

	const filteredList = displayRows
		?.filter((item) => isTypeMatch(item.type, type))
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
						{status}
					</Badge>
				);
			case "PENDING":
				return (
					<Badge className="bg-amber-50 text-amber-700 border-amber-200 hover:bg-amber-50">
						{status}
					</Badge>
				);
			case "PROCESSING":
				return (
					<Badge className="bg-blue-50 text-blue-700 border-blue-200 animate-pulse hover:bg-blue-50">
						{status}
					</Badge>
				);
			case "REJECTED":
				return (
					<Badge className="bg-red-50 text-red-700 border-red-200 hover:bg-red-50">{status}</Badge>
				);
			default:
				return <Badge variant="secondary">{status}</Badge>;
		}
	};

	return (
		<div className="w-full mt-6">
			{/* Filters */}
			<div className="flex flex-wrap items-center justify-between gap-3 mb-4">
				<SearchBar
					containerClassName="max-w-md w-full sm:w-80"
					value={searchQuery}
					onChange={(e) => setSearchQuery(e.target.value)}
					placeholder="Search title, filename, or category..."
				/>
				<div className="flex flex-wrap items-center gap-2.5">
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
						<DropdownMenuContent className="w-56 max-h-80 overflow-y-auto rounded-lg border border-gray-200 shadow-none p-1">
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
						<DropdownMenuContent className="w-44 rounded-lg border border-gray-200 shadow-none p-1">
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
			<div className="border border-gray-100 rounded-lg bg-white overflow-hidden shadow-none">
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
										<Badge
											variant="secondary"
											className="bg-gray-100 text-gray-700 hover:bg-gray-100 rounded-lg"
										>
											{row.type === "GENERAL" ? "OTHER" : row.type}
										</Badge>
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
										<div className="flex justify-end gap-2">
											<Button
												onClick={() => handleRowClick(row)}
												variant="outline"
												size="md"
												className="border-gray-200 font-medium cursor-pointer rounded-lg shadow-none"
											>
												<RiEyeLine className="mr-2 h-4 w-4" />
												View
											</Button>
										</div>
									</TableCell>
								</TableRow>
							))}
					</TableBody>
				</Table>
			</div>
		</div>
	);
}
