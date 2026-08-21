import React, { useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel, FieldContent, FieldGroup } from "@/components/ui/field";
import { RiEyeLine, RiEdit2Line, RiArrowDownSLine, RiCheckLine } from "@remixicon/react";
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

	const [isModalOpen, setIsModalOpen] = useState(false);
	const [tempSettings, setTempSettings] = useState<IVisibilitySettings>(settings);

	const handleOpenModal = () => {
		setTempSettings(settings);
		setIsModalOpen(true);
	};

	const handleSaveModal = () => {
		onChange(tempSettings);
		setIsModalOpen(false);
		onSave?.();
	};

	const handleCancelModal = () => {
		setTempSettings(settings);
		setIsModalOpen(false);
		onCancel?.();
	};

	// Multi-select helper handlers for modal
	const toggleSelection = (key: keyof IVisibilitySettings, value: string) => {
		const current = tempSettings[key] || [];
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

		setTempSettings({ ...tempSettings, [key]: updated });
	};

	const formatDisplay = (
		key: keyof IVisibilitySettings,
		typeName: string,
		sourceSettings: IVisibilitySettings = settings,
	) => {
		const current = sourceSettings[key] || ["all"];
		if (current.includes("all")) return `All ${typeName}`;
		if (current.length === 0) return `None selected`;
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
		const current = tempSettings[key] || ["all"];

		return (
			<Popover>
				<PopoverTrigger
					render={
						<Button
							type="button"
							variant="outline"
							className="w-full justify-between font-normal text-sm bg-white border-gray-200 focus-visible:ring-blue-500"
						>
							<span className="truncate">{formatDisplay(key, title, tempSettings)}</span>
							<RiArrowDownSLine className="size-4 text-zinc-400 shrink-0" />
						</Button>
					}
				/>
				<PopoverContent align="start" className="w-72 p-2 max-h-60 overflow-y-auto z-60 bg-white border border-gray-200 shadow-lg">
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
		);
	};

	return (
		<>
			<div className="bg-zinc-100/50 rounded-lg p-4 w-full text-zinc-950">
				<div className="flex items-center gap-2 text-blue-600 mb-2">
					<RiEyeLine className="size-5" />
					<h3 className="font-semibold text-sm">Visibility Settings</h3>
				</div>
				<p className="text-xs text-zinc-500 mb-4">
					Limit access to your medical insights so only authorized doctors can view this knowledge.
				</p>

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
							type="button"
							variant="outline"
							className="w-fit mt-2 bg-white gap-2 font-medium"
							onClick={handleOpenModal}
						>
							<RiEdit2Line className="size-4" />
							Edit Visibility
						</Button>
					)}
				</div>
			</div>

			<Dialog open={isModalOpen} onOpenChange={setIsModalOpen}>
				<DialogContent className="sm:max-w-md p-0 flex flex-col gap-0 rounded-xl overflow-hidden bg-white border-0 shadow-xl">
					<DialogHeader className="p-4 border-b border-gray-100 flex flex-col gap-0.5">
						<DialogTitle className="text-base font-semibold text-gray-900">
							Edit Visibility Settings
						</DialogTitle>
						<DialogDescription className="text-xs text-zinc-500">
							Configure access limits for this knowledge document.
						</DialogDescription>
					</DialogHeader>

					<div className="p-4 flex flex-col gap-4 max-h-[60vh] overflow-y-auto">
						<FieldGroup className="gap-4">
							<Field>
								<FieldLabel className="text-xs font-medium text-zinc-700">Clinic</FieldLabel>
								<FieldContent>
									{renderDropdown(
										"Clinic",
										"clinics",
										branches.map((b) => ({ label: b.name, value: b.id })),
									)}
								</FieldContent>
							</Field>

							<Field>
								<FieldLabel className="text-xs font-medium text-zinc-700">Doctor Type</FieldLabel>
								<FieldContent>
									{renderDropdown(
										"Doctor Type",
										"doctor_types",
										doctorTypes.map((t) => ({ label: t, value: t })),
									)}
								</FieldContent>
							</Field>

							<Field>
								<FieldLabel className="text-xs font-medium text-zinc-700">Doctor</FieldLabel>
								<FieldContent>
									{renderDropdown(
										"Doctor",
										"doctors",
										doctors.map((d) => ({ label: d.name, value: d.id })),
									)}
								</FieldContent>
							</Field>
						</FieldGroup>
					</div>

					<DialogFooter className="p-4 border-t border-gray-100 flex items-center justify-end gap-2 bg-zinc-50/50">
						<Button
							type="button"
							variant="outline"
							className="border-gray-200 bg-white"
							onClick={handleCancelModal}
						>
							Cancel
						</Button>
						<Button
							type="button"
							className="bg-blue-600 hover:bg-blue-700 text-white font-medium gap-1.5"
							disabled={
								(tempSettings.clinics && tempSettings.clinics.length === 0) ||
								(tempSettings.doctor_types && tempSettings.doctor_types.length === 0) ||
								(tempSettings.doctors && tempSettings.doctors.length === 0)
							}
							onClick={handleSaveModal}
						>
							<RiCheckLine className="size-4" />
							Save Changes
						</Button>
					</DialogFooter>
				</DialogContent>
			</Dialog>
		</>
	);
}
