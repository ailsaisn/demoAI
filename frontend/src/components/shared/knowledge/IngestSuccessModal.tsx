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
import { RiFileCheckLine } from "@remixicon/react";

interface IngestSuccessModalProps {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
	title?: string;
	description?: string;
	buttonText?: string;
	onAction?: () => void;
}

export function IngestSuccessModal({
	isOpen,
	onOpenChange,
	title = "Knowledge Ingested Successfully",
	description = "Now the knowledge that you uploaded and approved already added to the system",
	buttonText = "View Knowledge",
	onAction,
}: IngestSuccessModalProps) {
	const handleAction = () => {
		onOpenChange(false);
		onAction?.();
	};

	return (
		<Dialog open={isOpen} onOpenChange={onOpenChange}>
			<DialogContent className="sm:max-w-100 w-full p-0 flex flex-col gap-0 rounded-xl overflow-hidden bg-white border-0 shadow-2xl">
				{/* Title Section (Frame 173) */}
				<DialogHeader className="p-4 pb-2 border-none">
					<DialogTitle className="text-base font-medium text-black-500 text-center">
						{title}
					</DialogTitle>
				</DialogHeader>

				{/* Body Content Section (Frame 174) */}
				<div className="p-4 flex flex-col items-center justify-center gap-4 text-center">
					<div className="size-30 rounded-2xl bg-blue-50 flex items-center justify-center text-blue-600 shrink-0">
						<RiFileCheckLine className="size-12" />
					</div>
					<DialogDescription className="text-sm text-black-300 font-normal leading-relaxed text-center max-w-[320px]">
						{description}
					</DialogDescription>
				</div>

				{/* Footer Action (Frame 175) */}
				<DialogFooter className="p-4 pt-2 flex flex-col items-stretch w-full sm:justify-center border-none">
					<Button
						type="button"
						onClick={handleAction}
						className="w-full bg-blue-500 hover:bg-blue-600 text-white rounded-lg h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
					>
						{buttonText}
					</Button>
				</DialogFooter>
			</DialogContent>
		</Dialog>
	);
}
