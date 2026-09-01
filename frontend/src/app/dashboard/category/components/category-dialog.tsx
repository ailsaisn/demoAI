import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { RiCheckLine } from "@remixicon/react";

import { useState } from "react";
import { CategoryResponse } from "../api/types";
import { useCreateCategory, useUpdateCategory } from "../hooks/use-categories";

interface CategoryDialogProps {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
	mode: "add" | "edit";
	category?: CategoryResponse | null;
}

export function CategoryDialog({ isOpen, onOpenChange, mode, category }: CategoryDialogProps) {
	const isEdit = mode === "edit";
	const title = isEdit ? "Category" : "Add New Category";
	const buttonText = isEdit ? "Save Changes" : "Add Category";

	const [name, setName] = useState(isEdit && category ? category.name : "");

	const { mutate: createCategory, isPending: isCreating } = useCreateCategory();
	const { mutate: updateCategory, isPending: isUpdating } = useUpdateCategory();

	const isPending = isCreating || isUpdating;

	const handleSubmit = (e: React.FormEvent) => {
		e.preventDefault();
		if (!name.trim()) return;

		if (isEdit && category) {
			updateCategory(
				{ id: category.id, data: { name } },
				{
					onSuccess: () => onOpenChange(false),
				},
			);
		} else {
			createCategory(
				{ name },
				{
					onSuccess: () => onOpenChange(false),
				},
			);
		}
	};

	return (
		<Dialog open={isOpen} onOpenChange={onOpenChange}>
			<DialogContent className="max-w-120 p-0 overflow-hidden bg-white rounded-lg border border-gray-200 shadow-none">
				<form onSubmit={handleSubmit}>
					<DialogHeader className="p-4 border-b border-gray-100">
						<DialogTitle className="text-base font-semibold text-foreground">{title}</DialogTitle>
					</DialogHeader>

					<div className="p-4 flex flex-col gap-4">
						{isEdit && category && (
							<div className="flex flex-col gap-1.5">
								<label className="text-xs font-medium text-zinc-700">Display</label>
								<div>
									<Badge variant="secondary" className="bg-gray-100 text-gray-700 rounded-md">
										{category.name}
									</Badge>
								</div>
							</div>
						)}

						<div className="flex flex-col gap-1.5">
							<label className="text-xs font-medium text-zinc-700">Category Name</label>
							<div className="relative">
								<Input
									value={name}
									onChange={(e) => setName(e.target.value)}
									placeholder="Category Name"
									className="w-full bg-white h-10 border-gray-200 rounded-lg focus-visible:ring-blue-500 text-sm"
									disabled={isPending}
									autoFocus
								/>
							</div>
						</div>
					</div>

					<DialogFooter className="p-4 border-t border-gray-100 flex items-center justify-end gap-2 bg-zinc-50/50">
						<Button
							type="button"
							variant="outline"
							onClick={() => onOpenChange(false)}
							disabled={isPending}
							className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
						>
							Cancel
						</Button>
						<Button
							type="submit"
							className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none disabled:opacity-50"
							disabled={isPending || !name.trim()}
						>
							<RiCheckLine className="size-4 mr-1.5" />
							{buttonText}
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
