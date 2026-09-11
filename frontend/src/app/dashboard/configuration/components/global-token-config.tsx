"use client";

import { ConfirmationModal } from "@/components/shared/confirmation-modal";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { RiCheckLine, RiEdit2Line, RiLoader4Line, RiInformationFill } from "@remixicon/react";
import * as React from "react";
import { toast } from "sonner";
import { useConfigs, useUpdateConfig } from "../hooks/use-config";

interface PendingSaveState {
	key: "GLOBAL_TOKEN_THRESHOLD" | "GLOBAL_TOKEN_LIMIT" | "TOKEN_LIMIT_SPKK" | "TOKEN_LIMIT_GP";
	title: string;
	description: string;
	value: string;
	setter: (val: boolean) => void;
}

export function GlobalTokenConfig() {
	const { data: configs, isLoading } = useConfigs();
	const updateConfig = useUpdateConfig();

	const isGlobalLimitActive =
		configs?.find((c) => c.key === "GLOBAL_TOKEN_LIMIT_ACTIVE")?.value === "true";
	const globalThreshold = configs?.find((c) => c.key === "GLOBAL_TOKEN_THRESHOLD")?.value || "1000000";
	const branchTokenLimit = configs?.find((c) => c.key === "GLOBAL_TOKEN_LIMIT")?.value || "3000000";
	const spdveLimit = configs?.find((c) => c.key === "TOKEN_LIMIT_SPKK")?.value || "500000";
	const gpPlusLimit = configs?.find((c) => c.key === "TOKEN_LIMIT_GP")?.value || "250000";

	const [isActive, setIsActive] = React.useState(true);

	// Per-field value states with realistic default production limits
	const [thresholdAmount, setThresholdAmount] = React.useState("1000000");
	const [branchAmount, setBranchAmount] = React.useState("3000000");
	const [spdveAmount, setSpdveAmount] = React.useState("500000");
	const [gpPlusAmount, setGpPlusAmount] = React.useState("250000");

	// Per-field edit states
	const [editingThreshold, setEditingThreshold] = React.useState(false);
	const [editingBranch, setEditingBranch] = React.useState(false);
	const [editingSpdve, setEditingSpdve] = React.useState(false);
	const [editingGpPlus, setEditingGpPlus] = React.useState(false);

	const [savingKey, setSavingKey] = React.useState<string | null>(null);
	const [showWarning, setShowWarning] = React.useState(false);
	const warningTimeoutRef = React.useRef<NodeJS.Timeout | undefined>(undefined);

	// Toggle Confirmation State
	const [toggleModalOpen, setToggleModalOpen] = React.useState(false);
	const [pendingToggleActive, setPendingToggleActive] = React.useState<boolean | null>(null);

	// Save Confirmation State
	const [saveModalOpen, setSaveModalOpen] = React.useState(false);
	const [pendingSave, setPendingSave] = React.useState<PendingSaveState | null>(null);

	// Sync state when configs load
	React.useEffect(() => {
		if (configs) {
			setTimeout(() => {
				setIsActive(isGlobalLimitActive);
				setThresholdAmount(globalThreshold);
				setBranchAmount(branchTokenLimit);
				setSpdveAmount(spdveLimit);
				setGpPlusAmount(gpPlusLimit);
			}, 0);
		}
	}, [configs, isGlobalLimitActive, globalThreshold, branchTokenLimit, spdveLimit, gpPlusLimit]);

	const handleInitiateSave = (
		key: "GLOBAL_TOKEN_THRESHOLD" | "GLOBAL_TOKEN_LIMIT" | "TOKEN_LIMIT_SPKK" | "TOKEN_LIMIT_GP",
		title: string,
		description: string,
		value: string,
		setter: (val: boolean) => void
	) => {
		setPendingSave({ key, title, description, value, setter });
		setSaveModalOpen(true);
	};

	const handleConfirmSave = async () => {
		if (!pendingSave) return;
		const { key, value, setter } = pendingSave;
		try {
			setSavingKey(key);
			await updateConfig.mutateAsync({ key, data: { value } });
			setter(false);
			setShowWarning(true);
			if (warningTimeoutRef.current) clearTimeout(warningTimeoutRef.current);
			warningTimeoutRef.current = setTimeout(() => {
				setShowWarning(false);
			}, 5000);
			toast.success("Token configuration updated successfully!");
		} catch {
			toast.error("Failed to update token configuration.");
		} finally {
			setSavingKey(null);
			setPendingSave(null);
		}
	};

	const handleInitiateToggle = (checked: boolean) => {
		setPendingToggleActive(checked);
		setToggleModalOpen(true);
	};

	const handleConfirmToggle = () => {
		if (pendingToggleActive === null) return;
		const checked = pendingToggleActive;
		setIsActive(checked);

		setShowWarning(true);
		if (warningTimeoutRef.current) clearTimeout(warningTimeoutRef.current);
		warningTimeoutRef.current = setTimeout(() => {
			setShowWarning(false);
		}, 5000);

		updateConfig.mutate(
			{ key: "GLOBAL_TOKEN_LIMIT_ACTIVE", data: { value: checked.toString() } },
			{
				onSuccess: () => {
					setPendingToggleActive(null);
					toast.success(`Global token configuration ${checked ? "activated" : "deactivated"}!`);
				},
				onError: () => {
					setIsActive(!checked);
					setPendingToggleActive(null);
				},
			}
		);
	};

	if (isLoading) {
		return <div className="p-4 text-center text-sm text-zinc-500">Loading configuration...</div>;
	}

	return (
		<div className="flex flex-col w-full">
			<div className="flex flex-col gap-6 border border-white-600 rounded-lg p-4 bg-white">
				{/* Top Part: Title and Toggle */}
				<div className="flex flex-col gap-4">
					<div className="flex flex-col gap-1">
						<h3 className="text-base font-medium text-black-500">Global Token Configuration</h3>
						<p className="text-sm text-black-300">
							Apply the same token limit to all branches at once or one by one by switching the
							toggle.
						</p>
					</div>
					<div className="flex items-center gap-2">
						<Switch
							id="global-token-config-switch"
							checked={isActive}
							onCheckedChange={handleInitiateToggle}
							disabled={updateConfig.isPending}
							className="data-[state=checked]:bg-blue-500 cursor-pointer"
						/>
						<label
							htmlFor="global-token-config-switch"
							className="text-sm text-black-300 cursor-pointer select-none"
						>
							{isActive ? "Deactivate the configuration" : "Activate the configuration"}
						</label>
					</div>
				</div>

				{/* Active Configuration Content */}
				{isActive && (
					<div className="flex flex-col gap-6 border-t border-white-600 pt-6">
						{/* 1. Global Token Threshold */}
						<div className="flex flex-col gap-3">
							<h4 className="text-base font-medium text-black-500">
								Global Token Threshold (per month)
							</h4>
							<div className="flex flex-col gap-1.5">
								<span className="text-sm text-black-300">Global Token Threshold</span>
								<div className="flex items-center gap-4">
									<div className="relative w-64">
										<Input
											type="number"
											disabled={!editingThreshold}
											value={thresholdAmount}
											placeholder="1000000"
											onChange={(e) => setThresholdAmount(e.target.value)}
											className="w-full bg-[#f0f0f0] border-white-600 text-black-500 h-10 rounded-lg pr-20 disabled:opacity-80 focus-visible:ring-blue-500"
										/>
										<span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-black-200 pointer-events-none">
											per month
										</span>
									</div>
									{editingThreshold ? (
										<div className="flex items-center gap-2">
											<Button
												type="button"
												variant="outline"
												className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none"
												onClick={() => {
													setEditingThreshold(false);
													setThresholdAmount(globalThreshold);
												}}
												disabled={savingKey === "GLOBAL_TOKEN_THRESHOLD"}
											>
												Cancel
											</Button>
											<Button
												type="button"
												className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none disabled:opacity-50"
												onClick={() =>
													handleInitiateSave(
														"GLOBAL_TOKEN_THRESHOLD",
														"Save Global Token Threshold",
														`Are you sure you want to update the global token threshold to ${Number(thresholdAmount || 0).toLocaleString()} tokens per month?`,
														thresholdAmount,
														setEditingThreshold
													)
												}
												disabled={savingKey === "GLOBAL_TOKEN_THRESHOLD" || !thresholdAmount}
											>
												{savingKey === "GLOBAL_TOKEN_THRESHOLD" ? (
													<RiLoader4Line className="size-4 animate-spin mr-1" />
												) : (
													<RiCheckLine className="size-4 mr-1" />
												)}
												Save
											</Button>
										</div>
									) : (
										<Button
											type="button"
											variant="outline"
											className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 text-sm font-medium transition-colors cursor-pointer shadow-none gap-1.5"
											onClick={() => setEditingThreshold(true)}
										>
											<RiEdit2Line className="size-4 text-zinc-500" />
											Edit
										</Button>
									)}
								</div>
							</div>
						</div>

						{/* 2. Token Amount (per month) Section */}
						<div className="flex flex-col gap-6 border-t border-white-600 pt-5">
							<div className="flex flex-col gap-1">
								<h4 className="text-base font-medium text-black-500">Token Amount (per month)</h4>
								<p className="text-sm text-black-300">
									The token is represented by the conversations held in the chatbot, and it will be
									calculated on a monthly basis.
								</p>
							</div>

							{/* Token Amount (per Branch) */}
							<div className="flex flex-col gap-1.5">
								<span className="text-sm text-black-300">Token Amount (per Branch)</span>
								<div className="flex items-center gap-4">
									<div className="relative w-64">
										<Input
											type="number"
											disabled={!editingBranch}
											value={branchAmount}
											placeholder="3000000"
											onChange={(e) => setBranchAmount(e.target.value)}
											className="w-full bg-[#f0f0f0] border-white-600 text-black-500 h-10 rounded-lg pr-20 disabled:opacity-80 focus-visible:ring-blue-500"
										/>
										<span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-black-200 pointer-events-none">
											per month
										</span>
									</div>
									{editingBranch ? (
										<div className="flex items-center gap-2">
											<Button
												type="button"
												variant="outline"
												className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none"
												onClick={() => {
													setEditingBranch(false);
													setBranchAmount(branchTokenLimit);
												}}
												disabled={savingKey === "GLOBAL_TOKEN_LIMIT"}
											>
												Cancel
											</Button>
											<Button
												type="button"
												className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none disabled:opacity-50"
												onClick={() =>
													handleInitiateSave(
														"GLOBAL_TOKEN_LIMIT",
														"Save Branch Token Limit",
														`Are you sure you want to update the token amount per branch to ${Number(branchAmount || 0).toLocaleString()} tokens per month?`,
														branchAmount,
														setEditingBranch
													)
												}
												disabled={savingKey === "GLOBAL_TOKEN_LIMIT" || !branchAmount}
											>
												{savingKey === "GLOBAL_TOKEN_LIMIT" ? (
													<RiLoader4Line className="size-4 animate-spin mr-1" />
												) : (
													<RiCheckLine className="size-4 mr-1" />
												)}
												Save
											</Button>
										</div>
									) : (
										<Button
											type="button"
											variant="outline"
											className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 text-sm font-medium transition-colors cursor-pointer shadow-none gap-1.5"
											onClick={() => setEditingBranch(true)}
										>
											<RiEdit2Line className="size-4 text-zinc-500" />
											Edit
										</Button>
									)}
								</div>
							</div>

							{/* Row: Token Amount (SpDVE) & Token Amount (GP Plus) */}
							<div className="flex flex-wrap items-start gap-8">
								{/* Token Amount (SpDVE) */}
								<div className="flex flex-col gap-1.5">
									<span className="text-sm text-black-300">Token Amount (SpDVE)</span>
									<div className="flex items-center gap-4">
										<div className="relative w-64">
											<Input
												type="number"
												disabled={!editingSpdve}
												value={spdveAmount}
												placeholder="500000"
												onChange={(e) => setSpdveAmount(e.target.value)}
												className="w-full bg-[#f0f0f0] border-white-600 text-black-500 h-10 rounded-lg pr-20 disabled:opacity-80 focus-visible:ring-blue-500"
											/>
											<span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-black-200 pointer-events-none">
												per month
											</span>
										</div>
										{editingSpdve ? (
											<div className="flex items-center gap-2">
												<Button
													type="button"
													variant="outline"
													className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none"
													onClick={() => {
														setEditingSpdve(false);
														setSpdveAmount(spdveLimit);
													}}
													disabled={savingKey === "TOKEN_LIMIT_SPKK"}
												>
													Cancel
												</Button>
												<Button
													type="button"
													className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none disabled:opacity-50"
													onClick={() =>
														handleInitiateSave(
															"TOKEN_LIMIT_SPKK",
															"Save SpDVE Token Limit",
															`Are you sure you want to update the token amount for SpDVE to ${Number(spdveAmount || 0).toLocaleString()} tokens per month?`,
															spdveAmount,
															setEditingSpdve
														)
													}
													disabled={savingKey === "TOKEN_LIMIT_SPKK" || !spdveAmount}
												>
													{savingKey === "TOKEN_LIMIT_SPKK" ? (
														<RiLoader4Line className="size-4 animate-spin mr-1" />
													) : (
														<RiCheckLine className="size-4 mr-1" />
													)}
													Save
												</Button>
											</div>
										) : (
											<Button
												type="button"
												variant="outline"
												className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 text-sm font-medium transition-colors cursor-pointer shadow-none gap-1.5"
												onClick={() => setEditingSpdve(true)}
											>
												<RiEdit2Line className="size-4 text-zinc-500" />
												Edit
											</Button>
										)}
									</div>
								</div>

								{/* Token Amount (GP Plus) */}
								<div className="flex flex-col gap-1.5">
									<span className="text-sm text-black-300">Token Amount (GP Plus)</span>
									<div className="flex items-center gap-4">
										<div className="relative w-64">
											<Input
												type="number"
												disabled={!editingGpPlus}
												value={gpPlusAmount}
												placeholder="250000"
												onChange={(e) => setGpPlusAmount(e.target.value)}
												className="w-full bg-[#f0f0f0] border-white-600 text-black-500 h-10 rounded-lg pr-20 disabled:opacity-80 focus-visible:ring-blue-500"
											/>
											<span className="absolute right-3 top-1/2 -translate-y-1/2 text-sm text-black-200 pointer-events-none">
												per month
											</span>
										</div>
										{editingGpPlus ? (
											<div className="flex items-center gap-2">
												<Button
													type="button"
													variant="outline"
													className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none"
													onClick={() => {
														setEditingGpPlus(false);
														setGpPlusAmount(gpPlusLimit);
													}}
													disabled={savingKey === "TOKEN_LIMIT_GP"}
												>
													Cancel
												</Button>
												<Button
													type="button"
													className="bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 font-medium h-10 text-sm transition-colors cursor-pointer shadow-none disabled:opacity-50"
													onClick={() =>
														handleInitiateSave(
															"TOKEN_LIMIT_GP",
															"Save GP Plus Token Limit",
															`Are you sure you want to update the token amount for GP Plus to ${Number(gpPlusAmount || 0).toLocaleString()} tokens per month?`,
															gpPlusAmount,
															setEditingGpPlus
														)
													}
													disabled={savingKey === "TOKEN_LIMIT_GP" || !gpPlusAmount}
												>
													{savingKey === "TOKEN_LIMIT_GP" ? (
														<RiLoader4Line className="size-4 animate-spin mr-1" />
													) : (
														<RiCheckLine className="size-4 mr-1" />
													)}
													Save
												</Button>
											</div>
										) : (
											<Button
												type="button"
												variant="outline"
												className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 text-sm font-medium transition-colors cursor-pointer shadow-none gap-1.5"
												onClick={() => setEditingGpPlus(true)}
											>
												<RiEdit2Line className="size-4 text-zinc-500" />
												Edit
											</Button>
										)}
									</div>
								</div>
							</div>
						</div>
					</div>
				)}
			</div>

			{/* Informational Toast / Banner */}
			<div
				className={`transition-all duration-300 ease-in-out overflow-hidden ${
					showWarning ? "opacity-100 max-h-40 mt-4" : "opacity-0 max-h-0 mt-0"
				}`}
			>
				<div className="flex items-start gap-3 p-4 rounded-xl bg-amber-50 border border-amber-200">
					<RiInformationFill className="size-5 text-amber-500 mt-0.5 shrink-0" />
					<p className="text-sm text-amber-700 mt-0.5">
						<strong className="font-semibold text-amber-900">Note: </strong> Changes apply instantly to <strong className="font-semibold text-amber-900">new sessions</strong>. Any existing, active sessions will retain their original settings until they expire or are closed.
					</p>
				</div>
			</div>

			{/* Toggle Confirmation Modal */}
			<ConfirmationModal
				isOpen={toggleModalOpen}
				onOpenChange={(open) => {
					setToggleModalOpen(open);
					if (!open) setPendingToggleActive(null);
				}}
				title={pendingToggleActive ? "Activate Global Token Configuration" : "Deactivate Global Token Configuration"}
				description={
					pendingToggleActive
						? "Are you sure you want to activate the global token limit configuration for all branches?"
						: "Are you sure you want to deactivate the global token limit configuration?"
				}
				confirmText={pendingToggleActive ? "Activate" : "Deactivate"}
				variant={pendingToggleActive ? "primary" : "destructive"}
				isLoading={updateConfig.isPending}
				onConfirm={handleConfirmToggle}
			/>

			{/* Save Field Confirmation Modal */}
			<ConfirmationModal
				isOpen={saveModalOpen}
				onOpenChange={(open) => {
					setSaveModalOpen(open);
					if (!open) setPendingSave(null);
				}}
				title={pendingSave?.title || "Save Configuration"}
				description={pendingSave?.description || "Are you sure you want to save these changes?"}
				confirmText="Save and Apply"
				isLoading={updateConfig.isPending && savingKey !== null}
				onConfirm={handleConfirmSave}
			/>
		</div>
	);
}
