"use client";

import { ConfirmationModal } from "@/components/shared/confirmation-modal";
import { Switch } from "@/components/ui/switch";
import * as React from "react";
import { toast } from "sonner";
import { useConfigs, useUpdateConfig } from "../hooks/use-config";
import { RiLoader4Line } from "@remixicon/react";

export function GlobalFileAttachmentConfig() {
	const { data: configs, isLoading } = useConfigs();
	const updateConfig = useUpdateConfig();

	// Find config, default to "false" if not found
	const fileAttachmentConfig = configs?.find((c) => c.key === "AI_PROMPT_FILE_ATTACHMENTS")?.value || "false";
	const isChecked = fileAttachmentConfig === "true";

	const [isUpdating, setIsUpdating] = React.useState(false);
	const [localChecked, setLocalChecked] = React.useState(false);
	const [confirmModalOpen, setConfirmModalOpen] = React.useState(false);
	const [pendingChecked, setPendingChecked] = React.useState<boolean | null>(null);

	React.useEffect(() => {
		if (configs) {
			setTimeout(() => {
				setLocalChecked(isChecked);
			}, 0);
		}
	}, [configs, isChecked]);

	const handleInitiateToggle = (checked: boolean) => {
		setPendingChecked(checked);
		setConfirmModalOpen(true);
	};

	const handleConfirmToggle = () => {
		if (pendingChecked === null) return;
		const targetVal = pendingChecked;
		setIsUpdating(true);
		setLocalChecked(targetVal);

		updateConfig.mutate(
			{ key: "AI_PROMPT_FILE_ATTACHMENTS", data: { value: targetVal.toString() } },
			{
				onSuccess: () => {
					setIsUpdating(false);
					setPendingChecked(null);
					toast.success("AI Prompt File Attachments setting updated successfully!");
				},
				onError: () => {
					// Revert on error
					setLocalChecked(!targetVal);
					setPendingChecked(null);
					setIsUpdating(false);
				},
			},
		);
	};

	if (isLoading) {
		return <div className="p-4 text-center text-sm text-zinc-600">Loading configuration...</div>;
	}

	return (
		<div className="flex flex-col w-full">
			<div className="flex flex-col gap-6 border border-black-50 rounded-lg p-4 bg-white">
				<div className="flex flex-col gap-6.5">
					<div className="flex flex-col gap-1.5">
						<h4 className="text-base font-medium text-black-500 flex items-center gap-2">
							AI Prompt File Attachments
							{isUpdating && <RiLoader4Line className="size-4 animate-spin text-black-400" />}
						</h4>
						<p className="text-sm text-black-300">
							Allow doctors to attach files when asking the AI a question.
						</p>
					</div>

					<div className="flex items-center gap-3">
						<Switch
							id="global-file-attachment-switch"
							checked={localChecked}
							onCheckedChange={handleInitiateToggle}
							disabled={updateConfig.isPending || isUpdating}
						/>
						<label
							htmlFor="global-file-attachment-switch"
							className="text-sm text-black-400 cursor-pointer select-none"
						>
							{localChecked ? "Allow file attachment" : "Don't allow file attachment"}
						</label>
					</div>
				</div>
			</div>

			<ConfirmationModal
				isOpen={confirmModalOpen}
				onOpenChange={(open) => {
					setConfirmModalOpen(open);
					if (!open) setPendingChecked(null);
				}}
				title={pendingChecked ? "Allow File Attachments" : "Disallow File Attachments"}
				description={
					pendingChecked
						? "Are you sure you want to allow doctors to attach files when asking questions to the AI assistant?"
						: "Are you sure you want to disallow doctors from attaching files when asking questions to the AI assistant?"
				}
				confirmText={pendingChecked ? "Allow" : "Disallow"}
				variant={pendingChecked ? "primary" : "destructive"}
				isLoading={isUpdating || updateConfig.isPending}
				onConfirm={handleConfirmToggle}
			/>
		</div>
	);
}
