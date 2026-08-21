"use client";

import { useEffect, useState, useMemo } from "react";
import {
	Dialog,
	DialogContent,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldContent, FieldLabel, FieldTitle } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
	RiAddLine,
	RiCheckLine,
	RiDeleteBinLine,
	RiLoader4Line,
} from "@remixicon/react";
import { RoleDetailResponse } from "../api/types";
import {
	useCreateRole,
	useDeleteRole,
	useUpdateRole,
} from "../hooks/use-roles";

interface PermissionAction {
	id: "create" | "read" | "update" | "delete";
	label: string;
	key: string;
}

interface ModuleConfig {
	id: string;
	name: string;
	actions: PermissionAction[];
}

const MODULES_CONFIG: ModuleConfig[] = [
	{
		id: "knowledge",
		name: "Knowledge Base",
		actions: [
			{ id: "create", label: "Create", key: "knowledge:create" },
			{ id: "read", label: "Read", key: "knowledge:read" },
			{ id: "update", label: "Update", key: "knowledge:update" },
			{ id: "delete", label: "Delete", key: "knowledge:delete" },
		],
	},
	{
		id: "chats",
		name: "Chat History",
		actions: [
			{ id: "create", label: "Create", key: "chats:create" },
			{ id: "read", label: "Read", key: "chats:read" },
			{ id: "update", label: "Update", key: "chats:update" },
			{ id: "delete", label: "Delete", key: "chats:delete" },
		],
	},
	{
		id: "categories",
		name: "Category",
		actions: [
			{ id: "create", label: "Create", key: "categories:create" },
			{ id: "read", label: "Read", key: "categories:read" },
			{ id: "update", label: "Update", key: "categories:update" },
			{ id: "delete", label: "Delete", key: "categories:delete" },
		],
	},
	{
		id: "branches",
		name: "Branch",
		actions: [
			{ id: "create", label: "Create", key: "branches:create" },
			{ id: "read", label: "Read", key: "branches:read" },
			{ id: "update", label: "Update", key: "branches:update" },
			{ id: "delete", label: "Delete", key: "branches:delete" },
		],
	},
	{
		id: "users",
		name: "User",
		actions: [
			{ id: "create", label: "Create", key: "users:create" },
			{ id: "read", label: "Read", key: "users:read" },
			{ id: "update", label: "Update", key: "users:update" },
			{ id: "delete", label: "Delete", key: "users:delete" },
		],
	},
	{
		id: "roles",
		name: "Role",
		actions: [
			{ id: "create", label: "Create", key: "roles:create" },
			{ id: "read", label: "Read", key: "roles:read" },
			{ id: "update", label: "Update", key: "roles:update" },
			{ id: "delete", label: "Delete", key: "roles:delete" },
		],
	},
	{
		id: "configuration",
		name: "Configuration",
		actions: [
			{ id: "create", label: "Create", key: "configuration:create" },
			{ id: "read", label: "Read", key: "configuration:read" },
			{ id: "update", label: "Update", key: "configuration:update" },
			{ id: "delete", label: "Delete", key: "configuration:delete" },
		],
	},
	{
		id: "notifications",
		name: "Notification",
		actions: [
			{ id: "create", label: "Create", key: "notifications:create" },
			{ id: "read", label: "Read", key: "notifications:read" },
			{ id: "update", label: "Update", key: "notifications:update" },
			{ id: "delete", label: "Delete", key: "notifications:delete" },
		],
	},
];

// Helper to normalize raw backend accesses to UI keys
function normalizeAccessesToUi(rawAccesses: string[], roleName?: string): string[] {
	if (roleName?.toUpperCase() === "ADMIN") {
		return MODULES_CONFIG.flatMap((m) => m.actions.map((a) => a.key));
	}

	const result = new Set<string>();
	rawAccesses.forEach((acc) => {
		result.add(acc);
		// If backend returns umbrella 'write' access, expand to UI actions
		if (acc === "knowledge:write") {
			result.add("knowledge:create");
			result.add("knowledge:update");
		}
		if (acc === "chats:read") {
			result.add("chats:create");
			result.add("chats:read");
			result.add("chats:update");
			result.add("chats:delete");
		}
		if (acc === "users:write") {
			result.add("users:create");
			result.add("users:update");
			result.add("users:delete");
			result.add("roles:create");
			result.add("roles:update");
			result.add("roles:delete");
		}
		if (acc === "users:read") {
			result.add("roles:read");
		}
		if (acc === "branches:write") {
			result.add("branches:create");
			result.add("branches:update");
			result.add("branches:delete");
		}
		if (acc === "categories:write") {
			result.add("categories:create");
			result.add("categories:update");
			result.add("categories:delete");
		}
		if (acc === "configuration:write") {
			result.add("configuration:create");
			result.add("configuration:update");
			result.add("configuration:delete");
		}
		if (acc === "notifications:write") {
			result.add("notifications:create");
			result.add("notifications:update");
			result.add("notifications:delete");
		}
	});
	return Array.from(result);
}

// Helper to expand UI keys to backend accesses (including legacy umbrella keys)
function expandUiAccessesToBackend(uiAccesses: string[]): string[] {
	const result = new Set<string>(uiAccesses);

	// Add umbrella 'write' keys if any write-like action is selected
	if (uiAccesses.some((k) => k === "knowledge:create" || k === "knowledge:update")) {
		result.add("knowledge:write");
	}
	if (uiAccesses.some((k) => (k.startsWith("users:") || k.startsWith("roles:")) && k !== "users:read" && k !== "roles:read")) {
		result.add("users:write");
	}
	if (uiAccesses.some((k) => k === "roles:read" || k === "users:read")) {
		result.add("users:read");
	}
	if (uiAccesses.some((k) => k.startsWith("branches:") && k !== "branches:read")) {
		result.add("branches:write");
	}
	if (uiAccesses.some((k) => k.startsWith("categories:") && k !== "categories:read")) {
		result.add("categories:write");
	}
	if (uiAccesses.some((k) => k.startsWith("configuration:") && k !== "configuration:read")) {
		result.add("configuration:write");
	}
	if (uiAccesses.some((k) => k.startsWith("notifications:") && k !== "notifications:read")) {
		result.add("notifications:write");
	}

	return Array.from(result);
}

interface RoleDialogProps {
	isOpen: boolean;
	onOpenChange: (open: boolean) => void;
	role: RoleDetailResponse | null;
	mode: "add" | "edit";
}

export function RoleDialog({ isOpen, onOpenChange, role, mode }: RoleDialogProps) {
	const [name, setName] = useState("");
	const [selectedUiKeys, setSelectedUiKeys] = useState<string[]>([]);

	const createRole = useCreateRole();
	const updateRole = useUpdateRole();
	const deleteRole = useDeleteRole();

	useEffect(() => {
		if (isOpen) {
			setTimeout(() => {
				if (mode === "edit" && role) {
					setName(role.name || "");
					setSelectedUiKeys(normalizeAccessesToUi(role.accesses || [], role.name));
				} else {
					setName("");
					setSelectedUiKeys([]);
				}
			}, 0);
		}
	}, [isOpen, role, mode]);

	const totalModules = MODULES_CONFIG.length;
	const selectedModulesCount = useMemo(() => {
		return MODULES_CONFIG.filter((m) =>
			m.actions.some((a) => selectedUiKeys.includes(a.key)),
		).length;
	}, [selectedUiKeys]);

	const isAllSelected = selectedModulesCount === totalModules;

	const toggleGlobalSelectAll = () => {
		if (isAllSelected) {
			setSelectedUiKeys([]);
		} else {
			const allKeys = MODULES_CONFIG.flatMap((m) => m.actions.map((a) => a.key));
			setSelectedUiKeys(allKeys);
		}
	};

	const toggleModule = (module: ModuleConfig) => {
		const moduleKeys = module.actions.map((a) => a.key);
		const allSelected = moduleKeys.every((k) => selectedUiKeys.includes(k));

		if (allSelected) {
			setSelectedUiKeys((prev) => prev.filter((k) => !moduleKeys.includes(k)));
		} else {
			setSelectedUiKeys((prev) => Array.from(new Set([...prev, ...moduleKeys])));
		}
	};

	const toggleAction = (module: ModuleConfig, actionId: "create" | "read" | "update" | "delete", actionKey: string) => {
		setSelectedUiKeys((prev) => {
			const isCurrentlyChecked = prev.includes(actionKey);
			const readActionKey = module.actions.find((a) => a.id === "read")?.key;
			const moduleActionKeys = module.actions.map((a) => a.key);

			if (isCurrentlyChecked) {
				// UNCHECKING: If unchecking READ, uncheck all actions in this module
				if (actionId === "read") {
					return prev.filter((k) => !moduleActionKeys.includes(k));
				} else {
					return prev.filter((k) => k !== actionKey);
				}
			} else {
				// CHECKING: If checking Create, Update, or Delete, automatically ensure Read is also checked
				const newKeys = new Set(prev);
				newKeys.add(actionKey);
				if (readActionKey) {
					newKeys.add(readActionKey);
				}
				return Array.from(newKeys);
			}
		});
	};

	const handleSave = () => {
		const cleanName = name.trim().toUpperCase();
		if (!cleanName) return;

		const backendAccesses = expandUiAccessesToBackend(selectedUiKeys);

		if (mode === "add") {
			createRole.mutate(
				{ name: cleanName, accesses: backendAccesses },
				{
					onSuccess: () => onOpenChange(false),
				},
			);
		} else if (mode === "edit" && role) {
			updateRole.mutate(
				{
					roleId: role.id,
					data: { name: cleanName, accesses: backendAccesses },
				},
				{
					onSuccess: () => onOpenChange(false),
				},
			);
		}
	};

	const handleDelete = () => {
		if (!role) return;
		if (role.name.toUpperCase() === "ADMIN") {
			alert("The default ADMIN role cannot be deleted.");
			return;
		}
		if (confirm(`Are you sure you want to delete the role "${role.name}"?`)) {
			deleteRole.mutate(role.id, {
				onSuccess: () => onOpenChange(false),
			});
		}
	};

	const isPending = createRole.isPending || updateRole.isPending || deleteRole.isPending;
	const isSystemAdmin = mode === "edit" && role?.name.toUpperCase() === "ADMIN";

	return (
		<Dialog open={isOpen} onOpenChange={onOpenChange}>
			<DialogContent
				showCloseButton={true}
				className="sm:max-w-3xl max-h-[90vh] p-0 flex flex-col bg-white rounded-xl overflow-hidden shadow-2xl border-0"
			>
				{/* Modal Header */}
				<DialogHeader className="p-4 sm:p-5 border-b border-gray-100 flex flex-row items-center justify-between shrink-0">
					<DialogTitle className="text-base font-medium text-gray-900">
						{mode === "add" ? "Add New Role" : `Edit Role: ${role?.name}`}
					</DialogTitle>
				</DialogHeader>

				{/* Modal Content Body */}
				<div className="flex-1 overflow-y-auto p-4 sm:p-6 space-y-6">
					{/* Role Name */}
					<Field>
						<FieldLabel>
							<FieldTitle className="text-sm font-normal text-gray-900">Role Name</FieldTitle>
						</FieldLabel>
						<FieldContent>
							<div className="relative">
								<Input
									placeholder="Head Department Functional"
									value={name}
									onChange={(e) => setName(e.target.value)}
									disabled={isSystemAdmin}
									className="border-gray-200 bg-white focus-visible:ring-blue-500 font-normal text-sm h-10 rounded-lg uppercase"
								/>
							</div>
							{isSystemAdmin && (
								<p className="text-xs text-amber-600 mt-1">
									The default ADMIN role name is protected and cannot be modified.
								</p>
							)}
						</FieldContent>
					</Field>

					{/* Role Permission Section */}
					<div className="space-y-3">
						<div className="flex items-center justify-between">
							<span className="text-sm font-normal text-gray-900">Role Permission</span>
							<label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer select-none">
								<Checkbox
									checked={isAllSelected}
									onCheckedChange={toggleGlobalSelectAll}
								/>
								<span className="text-sm text-gray-700">
									Select All ({selectedModulesCount} out of {totalModules})
								</span>
							</label>
						</div>

						{/* Module Rows List */}
						<div className="divide-y divide-gray-100 border border-gray-100 rounded-lg overflow-hidden bg-white">
							{MODULES_CONFIG.map((module) => {
								const moduleKeys = module.actions.map((a) => a.key);
								const isModuleActive = moduleKeys.some((k) =>
									selectedUiKeys.includes(k),
								);

								return (
									<div
										key={module.id}
										className="flex flex-col sm:flex-row sm:items-center justify-between p-3.5 gap-3 hover:bg-gray-50/50 transition-colors"
									>
										{/* Module Title Checkbox */}
										<label className="flex items-center gap-2.5 cursor-pointer min-w-44 select-none">
											<Checkbox
												checked={isModuleActive}
												onCheckedChange={() => toggleModule(module)}
											/>
											<span className="text-sm font-normal text-gray-800">
												{module.name}
											</span>
										</label>

										{/* Action Checkboxes (Create, Read, Update, Delete) */}
										<div className="flex items-center flex-wrap gap-4 sm:gap-6">
											{module.actions.map((action) => {
												const isChecked = selectedUiKeys.includes(action.key);
												return (
													<label
														key={`${module.id}-${action.id}`}
														className="flex items-center gap-2 cursor-pointer text-sm text-gray-600 hover:text-gray-900 select-none"
													>
														<Checkbox
															checked={isChecked}
															onCheckedChange={() => toggleAction(module, action.id, action.key)}
														/>
														<span className="text-sm text-gray-700">{action.label}</span>
													</label>
												);
											})}
										</div>
									</div>
								);
							})}
						</div>
					</div>
				</div>

				{/* Modal Footer */}
				<div className="p-4 border-t border-gray-100 bg-white flex items-center justify-between shrink-0">
					{mode === "edit" && !isSystemAdmin ? (
						<Button
							variant="outline"
							className="border-red-500 text-red-600 hover:bg-red-50 hover:text-red-700"
							onClick={handleDelete}
							disabled={isPending}
						>
							<RiDeleteBinLine className="mr-2 h-4 w-4 shrink-0" />
							Delete Role
						</Button>
					) : (
						<div />
					)}

					<div className="flex items-center gap-3">
						<Button
							variant="outline"
							className="border-blue-500 text-blue-600 hover:bg-blue-50 px-5 rounded-lg"
							onClick={() => onOpenChange(false)}
						>
							Cancel
						</Button>
						<Button
							className="bg-blue-600 text-white hover:bg-blue-700 px-5 rounded-lg font-medium"
							onClick={handleSave}
							disabled={isPending || !name.trim()}
						>
							{isPending ? (
								<RiLoader4Line className="mr-2 h-4 w-4 animate-spin shrink-0" />
							) : mode === "add" ? (
								<RiAddLine className="mr-2 h-4 w-4 shrink-0" />
							) : (
								<RiCheckLine className="mr-2 h-4 w-4 shrink-0" />
							)}
							{isPending
								? "Saving..."
								: mode === "add"
								? "Add Role"
								: "Save Changes"}
						</Button>
					</div>
				</div>
			</DialogContent>
		</Dialog>
	);
}
