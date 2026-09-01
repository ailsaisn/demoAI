"use client";

import { useState, useMemo } from "react";
import { SearchBar } from "@/components/shared/search-bar";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { useBranches } from "../hooks/use-branches";
import { useConfigs } from "../../configuration/hooks/use-config";
import { ViewBranchSheet } from "./view-branch-sheet";

export function BranchTokenTable() {
	const [searchQuery, setSearchQuery] = useState("");
	const { data: branches, isLoading } = useBranches();
	const { data: configs } = useConfigs();

	const isGlobalLimitActive =
		configs?.find((c) => c.key === "GLOBAL_TOKEN_LIMIT_ACTIVE")?.value === "true";
	const globalBranchLimit = configs?.find((c) => c.key === "GLOBAL_TOKEN_LIMIT")?.value || "3000000";

	const filteredBranches = useMemo(() => {
		if (!branches) return [];
		if (!searchQuery.trim()) return branches;
		const q = searchQuery.toLowerCase();
		return branches.filter(
			(branch) =>
				branch.name?.toLowerCase().includes(q) ||
				branch.code?.toLowerCase().includes(q) ||
				branch.ecosystem?.toLowerCase().includes(q),
		);
	}, [branches, searchQuery]);

	return (
		<div className="flex flex-col gap-4 w-full">
			<div className="flex items-center justify-between gap-4">
				{/* Search */}
				<SearchBar
					containerClassName="max-w-md flex-1"
					iconClassName="left-3 top-1/2 -translate-y-1/2 size-4 text-black-200"
					placeholder="Search for branch..."
					className="pl-9 border-black-50 text-sm h-10 rounded-lg"
					value={searchQuery}
					onChange={(e) => setSearchQuery(e.target.value)}
				/>

				{/* Actions */}
				<div className="flex items-center gap-3">
					{/* Add Branch functionality has been moved to CIS Dashboard sync */}
				</div>
			</div>

			<div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
				<Table className="[&_tr]:border-gray-100">
					<TableHeader className="bg-gray-50/50">
						<TableRow className="hover:bg-gray-50/50 border-b-gray-100">
							<TableHead className="w-[15%]">Branch Code</TableHead>
							<TableHead className="w-[15%]">Ecosystem</TableHead>
							<TableHead className="w-[25%]">Branch</TableHead>
							<TableHead>Tokens/Month</TableHead>
							<TableHead>Used</TableHead>
							<TableHead>Remaining</TableHead>
							<TableHead className="text-right">Actions</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{isLoading ? (
							<TableRow>
								<TableCell colSpan={7} className="text-center py-8 text-zinc-600">
									Loading branches...
								</TableCell>
							</TableRow>
						) : filteredBranches.length === 0 ? (
							<TableRow>
								<TableCell colSpan={7} className="text-center py-8 text-zinc-600">
									No branches found.
								</TableCell>
							</TableRow>
						) : (
							filteredBranches.map((branch) => {
								const limit = isGlobalLimitActive
									? Number(globalBranchLimit)
									: (branch.token_limit ?? branch.tokensMonth ?? 0);
								const used = branch.used ?? 0;
								const remaining = Math.max(0, limit - used);

								return (
									<TableRow key={branch.id} className="border-b-black-50">
										<TableCell className="font-medium text-black-500">
											{branch.code || "-"}
										</TableCell>
										<TableCell className="text-zinc-600">
											{branch.ecosystem || "-"}
										</TableCell>
										<TableCell className="font-medium text-black-500">
											{branch.name}
										</TableCell>
										<TableCell className="text-blue-600 font-medium">
											{limit.toLocaleString()}
										</TableCell>
										<TableCell className="text-blue-600 font-medium">
											{used.toLocaleString()}
										</TableCell>
										<TableCell className="text-blue-600 font-medium">
											{remaining.toLocaleString()}
										</TableCell>
										<TableCell className="text-right">
											<div className="flex justify-end">
												<ViewBranchSheet branch={branch} />
											</div>
										</TableCell>
									</TableRow>
								);
							})
						)}
					</TableBody>
				</Table>
			</div>
		</div>
	);
}
