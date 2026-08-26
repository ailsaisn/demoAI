"use client";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { RiCheckLine, RiInformationLine, RiLoader4Line } from "@remixicon/react";
import { useState } from "react";
import { UserResponse } from "../api/types";
import { useUpdateDoctorAccess } from "../hooks/use-users";

export function DoctorAdjustLimitDialog({
	isOpen,
	onOpenChange,
	doctor,
}: {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
	doctor: UserResponse | null;
}) {
	const tokenLimit = doctor?.token_limit ?? 0;
	const tokensUsed = doctor?.tokens_used ?? 0;
	const tokensLeft = Math.max(0, tokenLimit - tokensUsed);

	// Determine branch token limit bounds
	const branches = doctor?.branches || [];
	const maxBranchLimit =
		branches.length > 0
			? Math.max(...branches.map((b) => b.token_limit ?? 0))
			: 0;

	const isBranchLimitUnset = maxBranchLimit === 0;

	const [newLimit, setNewLimit] = useState<number>(tokenLimit);
	const updateDoctorAccess = useUpdateDoctorAccess();

	const isExceedingBranch = newLimit > maxBranchLimit && !isBranchLimitUnset;

	const handleSave = () => {
		if (!doctor?.id || isBranchLimitUnset || isExceedingBranch) return;

		updateDoctorAccess.mutate(
			{ userId: doctor.id, data: { token_limit: newLimit } },
			{
				onSuccess: () => {
					onOpenChange(false);
				},
			},
		);
	};

	return (
		<Dialog
			open={isOpen}
			onOpenChange={(open) => {
				if (!open && !updateDoctorAccess.isPending) {
					setNewLimit(tokenLimit);
					onOpenChange(open);
				} else if (open) {
					setNewLimit(tokenLimit);
					onOpenChange(open);
				}
			}}
		>
			<DialogContent className="sm:max-w-md p-0 flex flex-col gap-0 rounded-md overflow-hidden bg-white border-0">
				<DialogHeader className="p-4 border-b border-gray-100 flex flex-row items-center justify-between">
					<DialogTitle className="text-base font-medium text-gray-900">
						Adjust Token Limit
					</DialogTitle>
				</DialogHeader>

				<div className="p-4 flex flex-col gap-4">
					{/* Branch Context Info */}
					<div className="flex flex-col gap-1 text-sm bg-gray-50 p-3 rounded-md border border-gray-100">
						<span className="font-medium text-gray-700">Assigned Branch Limit:</span>
						{branches.length > 0 ? (
							branches.map((b) => (
								<span key={b.id} className="text-gray-600 text-xs">
									• {b.name}: {b.token_limit ? `${b.token_limit.toLocaleString()} tokens` : "Not set (0)"}
								</span>
							))
						) : (
							<span className="text-xs text-amber-600">No branch assigned yet</span>
						)}
					</div>

					<div className="flex flex-col gap-1 text-sm text-gray-900">
						<span>Current doctor limit: {tokenLimit.toLocaleString()}</span>
						<span>Remaining: {tokensLeft.toLocaleString()}</span>
						<span>Used: {tokensUsed.toLocaleString()}</span>
					</div>

					{isBranchLimitUnset ? (
						<div className="bg-amber-50 border border-amber-500 rounded-md p-4 text-sm text-amber-800 flex gap-2">
							<RiInformationLine className="h-5 w-5 shrink-0 text-amber-600" />
							<span>
								Branch token limit must be set on the <strong>Branches</strong> menu first before adjusting doctor token limits.
							</span>
						</div>
					) : (
						<>
							<div className="flex flex-col gap-2">
								<span className="text-sm font-medium text-gray-900">New Token Limit</span>
								<div className="relative flex items-center">
									<Input
										type="number"
										value={newLimit}
										max={maxBranchLimit}
										onChange={(e) => setNewLimit(Number(e.target.value))}
										className="h-10 border-gray-200 focus-visible:ring-blue-500 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
									/>
									<span className="absolute right-3 text-sm text-gray-400">tokens</span>
								</div>
								{isExceedingBranch && (
									<span className="text-xs text-red-600">
										Doctor limit cannot exceed branch limit ({maxBranchLimit.toLocaleString()} tokens).
									</span>
								)}
							</div>

							<div className="bg-blue-50 border border-blue-600 rounded-md p-4 text-sm text-blue-600 flex gap-2">
								<RiInformationLine className="h-5 w-5 shrink-0" />
								<span>
									We recommend not setting the token limit below the used token amount ({tokensUsed.toLocaleString()}).
								</span>
							</div>
						</>
					)}
				</div>

				<div className="p-4 border-t border-gray-100 flex justify-end">
					<Button
						className="bg-blue-600 text-white hover:bg-blue-700 px-6 rounded-md disabled:opacity-50"
						onClick={handleSave}
						disabled={updateDoctorAccess.isPending || isBranchLimitUnset || isExceedingBranch}
					>
						{updateDoctorAccess.isPending ? (
							<RiLoader4Line className="mr-2 h-4 w-4 animate-spin" />
						) : (
							<RiCheckLine className="mr-2 h-4 w-4" />
						)}
						Save Changes
					</Button>
				</div>
			</DialogContent>
		</Dialog>
	);
}
