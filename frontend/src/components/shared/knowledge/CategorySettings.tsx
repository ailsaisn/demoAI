import { useCategories } from "@/app/dashboard/category/hooks/use-categories";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

import { RiCloseLine, RiSparklingLine, RiEdit2Line } from "@remixicon/react";
import { useRef, useState } from "react";

interface CategorySettingsProps {
	categories: string[];
	onChangeCategories: (newCategories: string[]) => void;
	isEditMode?: boolean;
	showSaveActions?: boolean;
	onSave?: () => void;
	onCancel?: () => void;
}

export function CategorySettings({
	categories,
	onChangeCategories,
	isEditMode = false,
	showSaveActions = true,
	onSave,
	onCancel,
}: CategorySettingsProps) {
	const { data: allCategories = [] } = useCategories();
	const [inputValue, setInputValue] = useState("");
	const [open, setOpen] = useState(false);
	const [isEditing, setIsEditing] = useState(isEditMode);
	const inputRef = useRef<HTMLInputElement>(null);

	const [prevIsEditMode, setPrevIsEditMode] = useState(isEditMode);

	// Sync local edit state with parent when prop changes (React recommended pattern instead of useEffect)
	if (isEditMode !== prevIsEditMode) {
		setPrevIsEditMode(isEditMode);
		setIsEditing(isEditMode);
	}

	const availableCategories = allCategories.filter((c) => !categories.includes(c.name));

	const filteredCategories = availableCategories.filter((c) =>
		c.name.toLowerCase().includes(inputValue.toLowerCase()),
	);

	const handleAddCategory = (catName: string) => {
		if (!categories.includes(catName)) {
			onChangeCategories([...categories, catName]);
		}
		setInputValue("");
		setOpen(false);
	};

	const handleRemoveCategory = (catName: string) => {
		onChangeCategories(categories.filter((c) => c !== catName));
	};

	return (
		<div className="bg-zinc-100/50 rounded-lg p-4 w-full text-zinc-950">
			<div className="flex items-center gap-2 text-blue-600 mb-2">
				<RiSparklingLine className="size-5" />
				<h3 className="font-semibold text-sm">Suggested Categories</h3>
			</div>
			<p className="text-xs text-zinc-500 mb-4">
				The AI suggests the following tags for document indexing and chatbot routing.
			</p>

			<div className="flex flex-wrap gap-2 items-center mb-4">
				{categories.map((c) => (
					<div
						key={c}
						className="flex items-center gap-1 bg-white border border-zinc-200 px-3 py-1.5 rounded-md text-sm font-medium text-zinc-800 shadow-sm"
					>
						<span>{c}</span>
						{isEditing && (
							<button
								type="button"
								onClick={() => handleRemoveCategory(c)}
								className="text-zinc-400 hover:text-zinc-700 transition-colors"
							>
								<RiCloseLine className="size-4" />
							</button>
						)}
					</div>
				))}

				{isEditing && (
					<div className="relative flex-1 min-w-50 max-w-75">
						<Input
							ref={inputRef}
							value={inputValue}
							onChange={(e) => {
								setInputValue(e.target.value);
								setOpen(true);
							}}
							onFocus={() => setOpen(true)}
							onClick={() => setOpen(true)}
							onBlur={() => {
								setTimeout(() => setOpen(false), 150);
							}}
							placeholder="Type new category..."
							className="bg-white border-zinc-200 h-9 shadow-sm"
						/>
						{open && (
							<div className="absolute top-full left-0 mt-1 w-full bg-white border border-zinc-200 rounded-md shadow-md p-1 max-h-60 overflow-y-auto z-50">
								{filteredCategories.length > 0 ? (
									<div className="flex flex-col">
										{filteredCategories.map((cat) => (
											<div
												key={cat.id}
												onMouseDown={(e) => {
													e.preventDefault(); // prevent input blur
													handleAddCategory(cat.name);
												}}
												className="px-3 py-2 text-sm text-zinc-800 hover:bg-zinc-100 cursor-pointer rounded-sm"
											>
												{cat.name}
											</div>
										))}
									</div>
								) : (
									<div className="px-3 py-2 text-sm text-zinc-500 text-center">
										No categories found.
									</div>
								)}
							</div>
						)}
					</div>
				)}
			</div>

			{!isEditing && isEditMode && (
				<Button
					variant="outline"
					className="w-fit mt-2 bg-white gap-2 font-medium"
					onClick={() => setIsEditing(true)}
				>
					<RiEdit2Line className="size-4" />
					Edit Categories
				</Button>
			)}

			{isEditing && showSaveActions && (
				<div className="mt-6 flex flex-col gap-3">
					<p className="text-sm text-zinc-600 font-medium">Are these categories accurate?</p>
					<div className="flex items-center gap-2">
						<Button
							variant="outline"
							onClick={() => {
								setIsEditing(false);
								onCancel?.();
							}}
						>
							Cancel
						</Button>
						<Button
							className="bg-blue-600 hover:bg-blue-700 text-white"
							onClick={() => {
								setIsEditing(false);
								onSave?.();
							}}
						>
							Save Changes
						</Button>
					</div>
				</div>
			)}
		</div>
	);
}
