"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SearchBar } from "@/components/shared/search-bar";
import { ConfirmationModal } from "@/components/shared/confirmation-modal";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { RiAddLine, RiDeleteBinLine, RiEdit2Line } from "@remixicon/react";
import { useState, useMemo } from "react";
import { CategoryResponse } from "./api/types";
import { CategoryDialog } from "./components/category-dialog";
import { useCategories, useDeleteCategory } from "./hooks/use-categories";

export default function CategoriesPage() {
	const [searchQuery, setSearchQuery] = useState("");
	const [isDialogOpen, setIsDialogOpen] = useState(false);
	const [dialogMode, setDialogMode] = useState<"add" | "edit">("add");
	const [selectedCategory, setSelectedCategory] = useState<CategoryResponse | null>(null);

	const [categoryToDelete, setCategoryToDelete] = useState<CategoryResponse | null>(null);
	const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

	const { data: categories = [], isLoading } = useCategories();
	const { mutate: deleteCategory, isPending: isDeleting } = useDeleteCategory();

	const handleAddCategory = () => {
		setDialogMode("add");
		setSelectedCategory(null);
		setIsDialogOpen(true);
	};

	const handleEditCategory = (category: CategoryResponse) => {
		setDialogMode("edit");
		setSelectedCategory(category);
		setIsDialogOpen(true);
	};

	const handleDeleteClick = (category: CategoryResponse) => {
		setCategoryToDelete(category);
		setIsDeleteModalOpen(true);
	};

	const handleConfirmDelete = () => {
		if (!categoryToDelete) return;
		deleteCategory(categoryToDelete.id, {
			onSuccess: () => {
				setIsDeleteModalOpen(false);
				setCategoryToDelete(null);
			},
		});
	};

	// Filter categories based on search query
	const filteredCategories = useMemo(() => {
		if (!searchQuery.trim()) return categories;
		const q = searchQuery.toLowerCase();
		return categories.filter((c) => c.name.toLowerCase().includes(q));
	}, [categories, searchQuery]);

	return (
		<div className="p-6 flex flex-col gap-6 h-full">
			{/* Header */}
			<div className="flex flex-col gap-1">
				<h1 className="text-xl font-semibold text-foreground">Category</h1>
				<p className="text-sm text-muted-foreground">Explore a wide array of categorized products.</p>
			</div>

			<div className="flex flex-col">
				{/* Actions */}
				<div className="flex items-center justify-between mb-4">
					<SearchBar
						containerClassName="max-w-md"
						placeholder="Search for category..."
						value={searchQuery}
						onChange={(e) => setSearchQuery(e.target.value)}
					/>
					<Button
						className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg h-10 px-4 font-medium text-sm transition-colors cursor-pointer shadow-none gap-2"
						onClick={handleAddCategory}
					>
						<RiAddLine className="size-4 shrink-0" />
						Add Category
					</Button>
				</div>

				{/* Table */}
				<div className="border border-gray-200 rounded-lg bg-white overflow-hidden">
					<Table className="[&_tr]:border-gray-100">
						<TableHeader className="bg-gray-50/50">
							<TableRow>
								<TableHead className="w-[35%]">Category</TableHead>
								<TableHead className="w-50 text-right">Actions</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{isLoading ? (
								<TableRow>
									<TableCell colSpan={2} className="text-center py-8 text-zinc-600">
										Loading categories...
									</TableCell>
								</TableRow>
							) : filteredCategories.length === 0 ? (
								<TableRow>
									<TableCell colSpan={2} className="text-center py-8 text-zinc-600">
										No categories found.
									</TableCell>
								</TableRow>
							) : (
								filteredCategories.map((category) => (
									<TableRow key={category.id}>
										<TableCell>
											<Badge
												variant="secondary"
												className="bg-black-50 text-black-500 hover:bg-black-50/80"
											>
												{category.name}
											</Badge>
										</TableCell>
										<TableCell className="text-right">
											<div className="flex justify-end gap-2">
												<Button
													variant="outline"
													className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-3 h-8 font-medium text-xs transition-colors cursor-pointer shadow-none gap-1.5"
													onClick={() => handleEditCategory(category)}
												>
													<RiEdit2Line className="size-3.5 shrink-0" />
													Edit
												</Button>
												<Button
													variant="outline"
													className="border-red-200 text-red-600 hover:bg-red-50 hover:border-red-300 rounded-lg px-3 h-8 font-medium text-xs transition-colors cursor-pointer shadow-none gap-1.5 disabled:opacity-50"
													onClick={() => handleDeleteClick(category)}
													disabled={isDeleting}
												>
													<RiDeleteBinLine className="size-3.5 shrink-0" />
													Delete
												</Button>
											</div>
										</TableCell>
									</TableRow>
								))
							)}
						</TableBody>
					</Table>
				</div>
			</div>

			<CategoryDialog
				key={selectedCategory?.id || (isDialogOpen ? "open" : "closed")}
				isOpen={isDialogOpen}
				onOpenChange={setIsDialogOpen}
				mode={dialogMode}
				category={selectedCategory}
			/>

			{/* Delete Confirmation Modal */}
			<ConfirmationModal
				isOpen={isDeleteModalOpen}
				onOpenChange={setIsDeleteModalOpen}
				title="Delete Category"
				description={`Are you sure you want to delete the category "${categoryToDelete?.name || ""}"? This action cannot be undone.`}
				confirmText="Delete Category"
				variant="destructive"
				isLoading={isDeleting}
				onConfirm={handleConfirmDelete}
			/>
		</div>
	);
}
