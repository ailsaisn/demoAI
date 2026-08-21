"use client";

import { Button } from "@/components/ui/button";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { RiLoader4Line } from "@remixicon/react";

interface ConfirmationModalProps {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
	title: string;
	description: string;
	confirmText?: string;
	cancelText?: string;
	variant?: "primary" | "destructive";
	isLoading?: boolean;
	onConfirm: () => void | Promise<void>;
	onCancel?: () => void;
}

export function ConfirmationModal({
	isOpen,
	onOpenChange,
	title,
	description,
	confirmText = "Confirm",
	cancelText = "Cancel",
	variant = "primary",
	isLoading = false,
	onConfirm,
	onCancel,
}: ConfirmationModalProps) {
	const handleCancel = () => {
		onOpenChange(false);
		onCancel?.();
	};

	const handleConfirm = async () => {
		await onConfirm();
		onOpenChange(false);
	};

	return (
		<Dialog open={isOpen} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-100 w-full p-0 flex flex-col gap-0 rounded-xl overflow-hidden bg-white border-0 shadow-2xl">
				{/* Title Section (Frame 173) */}
				<DialogHeader className="p-4 pb-2 border-none">
					<DialogTitle className="text-base font-medium text-black-500 text-left">
						{title}
					</DialogTitle>
				</DialogHeader>

				{/* Body Content Section (Frame 174) */}
				<div className="px-4 py-2">
					<DialogDescription className="text-sm text-black-500 font-normal leading-relaxed text-left">
						{description}
					</DialogDescription>
				</div>

				{/* Footer Actions (Frame 175) */}
				<DialogFooter className="p-4 pt-4 flex flex-row items-center justify-end gap-2.5 sm:justify-end border-none">
					<Button
						type="button"
						variant="outline"
						onClick={handleCancel}
						disabled={isLoading}
						className="border-blue-500 text-blue-500 hover:bg-blue-50 hover:text-blue-600 rounded-lg px-5 py-2.5 h-10 font-medium text-sm transition-colors cursor-pointer"
					>
						{cancelText}
					</Button>
					<Button
						type="button"
						onClick={handleConfirm}
						disabled={isLoading}
						className={`rounded-lg px-5 py-2.5 h-10 font-medium text-sm text-white shadow-none transition-colors cursor-pointer ${
							variant === "destructive"
								? "bg-blue-500 hover:bg-blue-600"
								: "bg-blue-500 hover:bg-blue-600"
						}`}
					>
						{isLoading && <RiLoader4Line className="size-4 animate-spin mr-1.5" />}
						{confirmText}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
