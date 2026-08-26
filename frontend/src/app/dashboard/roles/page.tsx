"use client";

import { useState, useMemo } from "react";
import { RiAddLine, RiEdit2Line } from "@remixicon/react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { SearchBar } from "@/components/shared/search-bar";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";

import { RoleDialog } from "./components/role-dialog";
import { useRoles } from "./hooks/use-roles";
import { RoleDetailResponse } from "./api/types";

export default function RolesPage() {
	const [searchQuery, setSearchQuery] = useState("");
	const [selectedRole, setSelectedRole] = useState<RoleDetailResponse | null>(null);
	const [roleDialogMode, setRoleDialogMode] = useState<"add" | "edit">("add");
	const [isRoleDialogOpen, setIsRoleDialogOpen] = useState(false);

	const { data: rolesData = [], isLoading } = useRoles();

	const handleAddRole = () => {
		setSelectedRole(null);
		setRoleDialogMode("add");
		setIsRoleDialogOpen(true);
	};

	const handleEditRole = (role: RoleDetailResponse) => {
		setSelectedRole(role);
		setRoleDialogMode("edit");
		setIsRoleDialogOpen(true);
	};

	const selectedRoleLive = rolesData.find((r) => r.id === selectedRole?.id) || selectedRole;

	// Filtered roles based on search query
	const filteredRoles = useMemo(() => {
		if (!searchQuery.trim()) return rolesData;
		const q = searchQuery.toLowerCase();
		return rolesData.filter(
			(r) =>
				r.name.toLowerCase().includes(q) ||
				r.accesses?.some((a) => a.toLowerCase().includes(q)),
		);
	}, [rolesData, searchQuery]);

	return (
		<div className="flex flex-col h-full gap-6 p-6">
			{/* Header */}
			<div className="flex flex-col gap-1">
				<h1 className="text-xl font-semibold text-foreground">Roles & Permissions</h1>
				<p className="text-sm text-muted-foreground">
					Configure user roles and granular access permissions across modules.
				</p>
			</div>

			<div className="flex flex-col">
				{/* Actions */}
				<div className="flex items-center justify-between mb-4">
					<SearchBar
						containerClassName="max-w-md"
						placeholder="Search for roles or permissions..."
						value={searchQuery}
						onChange={(e) => setSearchQuery(e.target.value)}
					/>
					<Button className="bg-blue-600 hover:bg-blue-700" onClick={handleAddRole}>
						<RiAddLine className="mr-2 h-4 w-4" />
						Add New Role
					</Button>
				</div>

				{/* Table */}
				<div className="border border-gray-200 rounded-md bg-white overflow-hidden">
					<Table className="[&_tr]:border-gray-100">
						<TableHeader className="bg-gray-50/50">
							<TableRow>
								<TableHead className="w-[30%]">Role Name</TableHead>
								<TableHead className="w-[55%]">Permissions & Access</TableHead>
								<TableHead className="w-[15%] text-right">Actions</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{isLoading ? (
								<TableRow>
									<TableCell colSpan={3} className="text-center py-8 text-gray-500">
										Loading roles...
									</TableCell>
								</TableRow>
							) : filteredRoles.length === 0 ? (
								<TableRow>
									<TableCell colSpan={3} className="text-center py-8 text-gray-500">
										No roles found. Click &quot;Add New Role&quot; to create one.
									</TableCell>
								</TableRow>
							) : (
								filteredRoles.map((role: RoleDetailResponse) => (
									<TableRow key={role.id}>
										<TableCell>
											<div className="flex items-center gap-2">
												<span className="font-medium text-sm text-gray-900">
													{role.name}
												</span>
												{role.name.toUpperCase() === "ADMIN" && (
													<Badge
														variant="secondary"
														className="bg-purple-50 text-purple-700 border-purple-200 text-[10px] font-semibold"
													>
														System
													</Badge>
												)}
											</div>
										</TableCell>
										<TableCell>
											<div className="flex flex-wrap gap-1.5 max-w-xl">
												{role.accesses && role.accesses.length > 0 ? (
													role.accesses.slice(0, 4).map((acc) => (
														<Badge
															key={acc}
															variant="secondary"
															className="bg-gray-100 text-gray-700 text-xs px-2 py-0.5 border border-gray-200"
														>
															{acc}
														</Badge>
													))
												) : (
													<span className="text-xs text-gray-400 italic">
														No permissions assigned
													</span>
												)}
												{role.accesses && role.accesses.length > 4 && (
													<Badge
														variant="secondary"
														className="bg-blue-50 text-blue-700 border-blue-200 text-xs font-semibold"
													>
														+{role.accesses.length - 4} more
													</Badge>
												)}
											</div>
										</TableCell>
										<TableCell className="text-right">
											<div className="flex justify-end gap-2">
												<Button
													variant="outline"
													size="md"
													className="border-gray-200 font-medium"
													onClick={() => handleEditRole(role)}
												>
													<RiEdit2Line className="mr-1.5 h-4 w-4" />
													Edit
												</Button>
											</div>
										</TableCell>
									</TableRow>
								))
							)}
						</TableBody>
					</Table>
				</div>
			</div>

			<RoleDialog
				isOpen={isRoleDialogOpen}
				onOpenChange={setIsRoleDialogOpen}
				role={selectedRoleLive}
				mode={roleDialogMode}
			/>
		</div>
	);
}
