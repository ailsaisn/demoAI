"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { RiEdit2Line, RiSettings3Line } from "@remixicon/react";
import { useState } from "react";
import { UserResponse } from "../api/types";
import { DoctorAdjustLimitDialog } from "./doctor-adjust-limit-dialog";
import { DoctorManageKnowledgeDialog } from "./doctor-manage-knowledge-dialog";
import { useConfigs } from "../../configuration/hooks/use-config";

export function DoctorDetailsSheet({
	isOpen,
	onOpenChange,
	doctor,
}: {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
	doctor: UserResponse | null;
}) {
	const [isManageKnowledgeOpen, setIsManageKnowledgeOpen] = useState(false);
	const [isAdjustLimitOpen, setIsAdjustLimitOpen] = useState(false);

	const { data: configs } = useConfigs();
	const isGlobalLimitActive =
		configs?.find((c) => c.key === "GLOBAL_TOKEN_LIMIT_ACTIVE")?.value === "true";
	const spdveLimit = configs?.find((c) => c.key === "TOKEN_LIMIT_SPKK")?.value || "500000";
	const gpPlusLimit = configs?.find((c) => c.key === "TOKEN_LIMIT_GP")?.value || "250000";

	// Determine doctor type quota label if global mode is active
	const drTypeUpper = (doctor?.dr_type || "").toUpperCase();
	const isSpDVE = drTypeUpper.includes("SPKK") || drTypeUpper.includes("SPDVE") || drTypeUpper.includes("SPDV");
	const isGP = drTypeUpper.includes("GP") || drTypeUpper.includes("UMUM");
	const effectiveGlobalLimit = isSpDVE ? Number(spdveLimit) : isGP ? Number(gpPlusLimit) : 0;
	
	const hasCustomLimit = doctor?.token_limit !== null && doctor?.token_limit !== undefined && doctor.token_limit > 0;
	const effectiveLimit = hasCustomLimit
		? doctor.token_limit!
		: (isGlobalLimitActive ? effectiveGlobalLimit : (doctor?.token_limit ?? 0));
	const tokensUsed = doctor?.tokens_used ?? 0;
	const tokensRemaining = Math.max(0, effectiveLimit - tokensUsed);

	return (
		<Sheet open={isOpen} onOpenChange={onOpenChange}>
			<SheetContent className="sm:max-w-100 p-0 flex flex-col h-full bg-white gap-0">
				<SheetHeader className="p-4 border-b flex flex-row items-center">
					<SheetTitle className="text-base font-medium">Doctor Information</SheetTitle>
				</SheetHeader>

				{doctor && (
					<>
						<div className="flex-1 overflow-y-auto pb-6">
							<div className="flex flex-col pb-4">
								{/* Details Section */}
								<div className="flex flex-col gap-4 px-6 py-4">
									<div className="flex flex-col gap-2">
										<span className="text-sm text-gray-500">Name</span>
										<span className="text-sm text-gray-900">{doctor.name}</span>
									</div>

									<div className="flex flex-col gap-2">
										<span className="text-sm text-gray-500">Role</span>
										<span className="text-sm text-gray-900">Doctor</span>
									</div>

									<div className="flex flex-col gap-2">
										<span className="text-sm text-gray-500">Email</span>
										<span className="text-sm text-gray-900">{doctor.email || "-"}</span>
									</div>

									<div className="flex flex-col gap-2">
										<span className="text-sm text-gray-500">Employee ID</span>
										<span className="text-sm text-gray-900">{doctor.employee_id || "-"}</span>
									</div>

									<div className="flex flex-col gap-2">
										<span className="text-sm text-gray-500">Dr Type</span>
										<div className="flex items-center gap-2">
											<span className="text-sm text-gray-900">{doctor.dr_type || "-"}</span>
											{isGlobalLimitActive && !hasCustomLimit && (
												<span className="text-xs bg-blue-50 text-blue-600 px-2 py-0.5 rounded-full font-medium border border-blue-100">
													{isSpDVE ? "SpDVE Global Quota" : isGP ? "GP Plus Global Quota" : "Global Quota"}
												</span>
											)}
											{isGlobalLimitActive && hasCustomLimit && (
												<span className="text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded-full font-medium border border-emerald-200">
													Custom Override
												</span>
											)}
										</div>
									</div>

									<div className="flex flex-col gap-2">
										<span className="text-sm text-gray-500">Ecosystem</span>
										<span className="text-sm text-gray-900">{doctor.ecosystem || "ERHA"}</span>
									</div>

									<div className="flex flex-col gap-2">
										<div className="flex justify-between items-center">
											<div className="flex flex-col gap-1">
												<span className="text-sm text-gray-500">Tokens Remaining</span>
												<span className="text-sm font-medium text-gray-900">
													{tokensRemaining.toLocaleString()} / {effectiveLimit.toLocaleString()} tokens
												</span>
												{isGlobalLimitActive && (
													<span className="text-xs text-blue-600 font-normal">
														{hasCustomLimit
															? "Custom Override (Individual Doctor Limit)"
															: "Managed by Global Doctor Type Quota"}
													</span>
												)}
											</div>
											<Button
												variant="outline"
												className=""
												onClick={() => setIsAdjustLimitOpen(true)}
											>
												<RiEdit2Line className="mr-2 h-4 w-4" />
												Adjust Limit
											</Button>
										</div>
									</div>

									<div className="flex flex-col gap-2 pt-2">
										<span className="text-sm text-gray-500">Branches</span>
										{doctor.branches && doctor.branches.length > 0 ? (
											<div className="flex flex-col gap-3">
												{doctor.branches.map((branch) => (
													<div
														key={branch.id}
														className="border border-gray-200 rounded-md p-3 flex flex-col gap-1"
													>
														<span className="text-sm font-medium text-gray-900">
															{branch.name}
														</span>
														<span className="text-xs text-gray-500">
															Branch Token Pool: {branch.token_limit ? `${branch.token_limit.toLocaleString()} tokens/mo` : "Default"}
														</span>
													</div>
												))}
											</div>
										) : (
											<div className="border border-gray-200 rounded-md p-3">
												<span className="text-sm text-gray-500">No Branch</span>
											</div>
										)}
									</div>

									<div className="flex flex-col gap-2 pt-2">
										<span className="text-sm text-gray-500">Knowledge Base</span>
										<div className="flex flex-wrap gap-2">
											{doctor.categories && doctor.categories.length > 0 ? (
												doctor.categories.map((cat) => (
													<Badge
														key={cat.id}
														variant="secondary"
														className="bg-gray-100 text-gray-900"
													>
														{cat.name}
													</Badge>
												))
											) : (
												<span className="text-sm text-gray-400">No categories assigned</span>
											)}
										</div>
										<Button
											variant="outline"
											className="w-full mt-2 rounded-md"
											onClick={() => setIsManageKnowledgeOpen(true)}
										>
											<RiSettings3Line className="mr-2 h-4 w-4" />
											Manage Knowledge Base
										</Button>
									</div>
								</div>
							</div>
						</div>

						<div className="p-4 border-t border-gray-200 bg-white flex justify-start gap-3">
							<Button
								variant="outline"
								className="bg-white border-gray-200 text-gray-700 hover:bg-gray-50 hover:text-gray-900"
								onClick={() => onOpenChange(false)}
							>
								Close
							</Button>
						</div>

						<DoctorManageKnowledgeDialog
							isOpen={isManageKnowledgeOpen}
							onOpenChange={setIsManageKnowledgeOpen}
							doctor={doctor}
						/>

						<DoctorAdjustLimitDialog
							isOpen={isAdjustLimitOpen}
							onOpenChange={setIsAdjustLimitOpen}
							doctor={doctor}
						/>
					</>
				)}
			</SheetContent>
		</Sheet>
	);
}
