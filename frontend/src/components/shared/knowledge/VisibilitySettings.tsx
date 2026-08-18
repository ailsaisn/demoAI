import React, { useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { RiEyeLine, RiEdit2Line, RiArrowDownSLine } from "@remixicon/react";
import { useBranches } from "@/app/dashboard/branches/hooks/use-branches";
import { useUsers } from "@/app/dashboard/users/hooks/use-users";
import { VisibilitySettings as IVisibilitySettings } from "@/app/dashboard/knowledge/api/types";

interface VisibilitySettingsProps {
	settings: IVisibilitySettings;
	onChange: (settings: IVisibilitySettings) => void;
	isEditMode?: boolean;
	showSaveActions?: boolean;
	onSave?: () => void;
	onCancel?: () => void;
}

export function VisibilitySettings({
	settings,
	onChange,
	isEditMode = false,
	showSaveActions = true,
	onSave,
	onCancel,
}: VisibilitySettingsProps) {
	const { data: branches = [] } = useBranches();
	const { data: doctors = [] } = useUsers("DOCTOR");

	const doctorTypes = useMemo(() => {
		const types = new Set<string>();
		doctors.forEach((doc) => {
			if (doc.dr_type) types.add(doc.dr_type);
		});
		return Array.from(types).sort();
	}, [doctors]);

	const [isEditing, setIsEditing] = useState(isEditMode);
	const [prevIsEditMode, setPrevIsEditMode] = useState(isEditMode);

	if (isEditMode !== prevIsEditMode) {
		setPrevIsEditMode(isEditMode);
		setIsEditing(isEditMode);
	}

	// Multi-select helper handlers
	const toggleSelection = (key: keyof IVisibilitySettings, value: string) => {
		const current = settings[key] || [];
		const isAllSelected = current.includes("all");

		let updated: string[];
		if (value === "all") {
			updated = isAllSelected ? [] : ["all"];
		} else {
			const withoutAll = current.filter((v) => v !== "all");
			if (withoutAll.includes(value)) {
				updated = withoutAll.filter((v) => v !== value);
			} else {
				updated = [...withoutAll, value];
			}
		}

		onChange({ ...settings, [key]: updated });
	};

	const formatDisplay = (key: keyof IVisibilitySettings, typeName: string) => {
		const current = settings[key] || ["all"];
		if (current.includes("all")) return `All ${typeName}`;
		if (current.length === 1) {
			if (key === "clinics") return branches.find((b) => b.id === current[0])?.name || current[0];
			if (key === "doctors") return doctors.find((d) => d.id === current[0])?.name || current[0];
			return current[0];
		}
		return `${current.length} ${typeName} Selected`;
	};

	const renderDropdown = (
		title: string,
		key: keyof IVisibilitySettings,
		options: { label: string; value: string }[],
	) => {
		const current = settings[key] || ["all"];

		return (
			<div className="flex flex-col mb-4 last:mb-0">
				<label className="text-xs text-zinc-500 mb-1 font-medium">{title}</label>
				<Popover>
					<PopoverTrigger
						render={
							<Button
								variant="outline"
								className="w-full justify-between font-normal text-sm bg-white border-zinc-200"
							>
								<span className="truncate">{formatDisplay(key, title)}</span>
								<RiArrowDownSLine className="size-4 text-zinc-400" />
							</Button>
						}
					/>
					<PopoverContent align="start" className="w-64 p-2 max-h-60 overflow-y-auto z-60">
						<div className="flex flex-col gap-1">
							<div
								className="flex items-center gap-2 p-1.5 hover:bg-zinc-100 rounded-sm cursor-pointer"
								onClick={() => toggleSelection(key, "all")}
							>
								<Checkbox checked={current.includes("all")} />
								<span className="text-sm font-medium">All {title}</span>
							</div>
							<div className="h-px bg-zinc-200 my-1" />
							{options.map((opt) => (
								<div
									key={opt.value}
									className="flex items-center gap-2 p-1.5 hover:bg-zinc-100 rounded-sm cursor-pointer"
									onClick={() => toggleSelection(key, opt.value)}
								>
									<Checkbox checked={current.includes("all") || current.includes(opt.value)} />
									<span className="text-sm truncate">{opt.label}</span>
								</div>
							))}
						</div>
					</PopoverContent>
				</Popover>
			</div>
		);
	};

	return (
		<div className="bg-zinc-100/50 rounded-lg p-4 w-full text-zinc-950">
			<div className="flex items-center gap-2 text-blue-600 mb-2">
				<RiEyeLine className="size-5" />
				<h3 className="font-semibold text-sm">Visibility Settings</h3>
			</div>
			<p className="text-xs text-zinc-500 mb-4">
				Limit access to your medical insights so only authorized doctors can view this knowledge.
			</p>

			{isEditMode && isEditing ? (
				<div className="flex flex-col gap-1 mt-2">
					{renderDropdown(
						"Clinic",
						"clinics",
						branches.map((b) => ({ label: b.name, value: b.id })),
					)}
					{renderDropdown(
						"Doctor Type",
						"doctor_types",
						doctorTypes.map((t) => ({ label: t, value: t })),
					)}
					{renderDropdown(
						"Doctor",
						"doctors",
						doctors.map((d) => ({ label: d.name, value: d.id })),
					)}

					{showSaveActions && (
						<div className="mt-6 flex items-center justify-start gap-2">
							<Button variant="outline" onClick={() => {
								setIsEditing(false);
								onCancel?.();
							}}>Cancel</Button>
							<Button 
								className="bg-blue-600 hover:bg-blue-700 text-white" 
								disabled={(settings.clinics && settings.clinics.length === 0) || (settings.doctor_types && settings.doctor_types.length === 0) || (settings.doctors && settings.doctors.length === 0)}
								onClick={() => {
									setIsEditing(false);
									onSave?.();
								}}
							>
								Save Changes
							</Button>
						</div>
					)}
				</div>
			) : (
				<div className="flex flex-col gap-3">
					<div>
						<label className="text-xs text-zinc-400">Clinic</label>
						<p className="text-sm font-medium">{formatDisplay("clinics", "Clinic")}</p>
					</div>
					<div>
						<label className="text-xs text-zinc-400">Doctor Type</label>
						<p className="text-sm font-medium">{formatDisplay("doctor_types", "Doctor Type")}</p>
					</div>
					<div>
						<label className="text-xs text-zinc-400">Doctor</label>
						<p className="text-sm font-medium">{formatDisplay("doctors", "Doctor")}</p>
					</div>

					{isEditMode && (
						<Button
							variant="outline"
							className="w-fit mt-2 bg-white gap-2 font-medium"
							onClick={() => setIsEditing(true)}
						>
							<RiEdit2Line className="size-4" />
							Edit Visibility
						</Button>
					)}
				</div>
			)}
		</div>
	);
}
