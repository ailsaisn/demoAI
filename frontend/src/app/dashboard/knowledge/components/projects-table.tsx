"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import {
	DropdownMenu,
	DropdownMenuContent,
	DropdownMenuItem,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
	RiAddCircleLine,
	RiBookOpenLine,
	RiPencilLine,
	RiEyeLine,
	RiDeleteBinLine,
	RiLoader4Line,
	RiCheckLine,
	RiCloseLine,
	RiMore2Line,
} from "@remixicon/react";
import { useProjects, useUpdateProject, useDeleteProject } from "../hooks/use-projects";
import { ProjectDialog } from "./project-dialog";
import { ConfirmationModal } from "@/components/shared/knowledge/ConfirmationModal";
import type { ProjectResponse } from "../api/types";

interface ProjectsTableProps {
	searchQuery?: string;
}

export function ProjectsTable({ searchQuery = "" }: ProjectsTableProps) {
	const router = useRouter();
	const [isDialogOpen, setIsDialogOpen] = useState(false);
	const [projectToEdit, setProjectToEdit] = useState<ProjectResponse | null>(null);

	// Delete Modal State
	const [deleteModalOpen, setDeleteModalOpen] = useState(false);
	const [projectToDelete, setProjectToDelete] = useState<ProjectResponse | null>(null);

	// Inline editing state
	const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
	const [inlineName, setInlineName] = useState("");

	const { data: projects = [], isLoading, isError } = useProjects(searchQuery);
	const updateMutation = useUpdateProject();
	const deleteMutation = useDeleteProject();

	const handleOpenAdd = () => {
		setProjectToEdit(null);
		setIsDialogOpen(true);
	};

	const handleRowClick = (project: ProjectResponse) => {
		router.push(`/dashboard/knowledge/project/${project.id}`);
	};

	const handleStartInlineEdit = (project: ProjectResponse, e: React.MouseEvent) => {
		e.stopPropagation();
		setEditingProjectId(project.id);
		setInlineName(project.name);
	};

	const handleSaveInlineEdit = (projectId: string, e?: React.MouseEvent | React.FormEvent) => {
		if (e) e.stopPropagation();
		if (!inlineName.trim()) return;

		updateMutation.mutate(
			{
				id: projectId,
				data: { name: inlineName.trim() },
			},
			{
				onSuccess: () => {
					setEditingProjectId(null);
				},
			},
		);
	};

	const handleCancelInlineEdit = (e: React.MouseEvent) => {
		e.stopPropagation();
		setEditingProjectId(null);
	};

	const handleDeleteClick = (project: ProjectResponse, e: React.MouseEvent) => {
		e.stopPropagation();
		setProjectToDelete(project);
		setDeleteModalOpen(true);
	};

	const handleConfirmDelete = async () => {
		if (projectToDelete) {
			await deleteMutation.mutateAsync(projectToDelete.id);
			setDeleteModalOpen(false);
			setProjectToDelete(null);
		}
	};

	const formatDate = (dateStr?: string) => {
		if (!dateStr) return "-";
		try {
			const d = new Date(dateStr);
			return d.toLocaleDateString("id-ID", {
				day: "numeric",
				month: "long",
				year: "numeric",
			});
		} catch {
			return dateStr;
		}
	};

	return (
		<div className="w-full">
			{/* Header Bar */}
			<div className="flex items-center justify-between gap-3 mb-3">
				<h3 className="text-base font-semibold text-gray-900">Project List</h3>

				<Button
					onClick={handleOpenAdd}
					className="bg-blue-500 hover:bg-blue-600 text-white font-medium cursor-pointer rounded-lg shadow-none gap-1.5"
				>
					<RiAddCircleLine className="w-4 h-4" />
					<span>Add Project</span>
				</Button>
			</div>

			{/* Table */}
			<div className="border border-gray-200 rounded-lg bg-white overflow-hidden shadow-none">
				<Table className="[&_tr]:border-gray-100">
					<TableHeader className="bg-gray-50/50">
						<TableRow className="bg-gray-50/50 hover:bg-gray-50/50">
							<TableHead className="w-1/2 font-medium text-gray-700">Project Title</TableHead>
							<TableHead className="font-medium text-gray-700">Date</TableHead>
							<TableHead className="w-32 font-medium text-gray-700 text-right">Actions</TableHead>
						</TableRow>
					</TableHeader>
					<TableBody>
						{isLoading && (
							<TableRow>
								<TableCell colSpan={3} className="text-center py-8 text-gray-500">
									<div className="flex items-center justify-center">
										<RiLoader4Line className="w-5 h-5 animate-spin mr-2" />
										Loading projects...
									</div>
								</TableCell>
							</TableRow>
						)}

						{isError && (
							<TableRow>
								<TableCell colSpan={3} className="text-center py-8 text-red-500">
									Failed to load projects.
								</TableCell>
							</TableRow>
						)}

						{!isLoading && !isError && projects.length === 0 && (
							<TableRow>
								<TableCell colSpan={3} className="text-center py-12 text-gray-500">
									<p className="text-sm">
										{searchQuery
											? "No projects matching your search."
											: "No projects found. Click 'Add Project' to create one."}
									</p>
								</TableCell>
							</TableRow>
						)}

						{!isLoading &&
							projects.map((project) => {
								const isInlineEditing = editingProjectId === project.id;

								return (
									<TableRow
										key={project.id}
										onClick={() => handleRowClick(project)}
										className="hover:bg-gray-50/60 cursor-pointer transition-colors"
									>
										<TableCell>
											<div className="flex items-center gap-2 min-w-0">
												<RiBookOpenLine className="size-4 shrink-0 text-gray-600" />
												{isInlineEditing ? (
													<form
														onSubmit={(e) => {
															e.preventDefault();
															handleSaveInlineEdit(project.id, e);
														}}
														onClick={(e) => e.stopPropagation()}
														className="flex items-center gap-1.5 flex-1 min-w-0 max-w-sm"
													>
														<Input
															autoFocus
															value={inlineName}
															onChange={(e) => setInlineName(e.target.value)}
															className="h-7 text-xs px-2 py-0 border-blue-500 bg-white"
														/>
														<Button
															type="submit"
															size="icon"
															variant="ghost"
															className="size-6 text-emerald-600 hover:bg-emerald-50"
														>
															<RiCheckLine className="size-3.5" />
														</Button>
														<Button
															type="button"
															size="icon"
															variant="ghost"
															onClick={handleCancelInlineEdit}
															className="size-6 text-gray-400 hover:bg-gray-100"
														>
															<RiCloseLine className="size-3.5" />
														</Button>
													</form>
												) : (
													<div className="flex items-center gap-1.5 min-w-0 group">
														<span className="font-medium text-gray-900 truncate">
															{project.name}
														</span>
														<button
															type="button"
															onClick={(e) => handleStartInlineEdit(project, e)}
															className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-gray-200 text-gray-400 hover:text-gray-700 transition-opacity"
															title="Rename project"
														>
															<RiPencilLine className="size-3.5" />
														</button>
													</div>
												)}
											</div>
										</TableCell>

										<TableCell className="whitespace-nowrap text-sm text-gray-500">
											{formatDate(project.created_at)}
										</TableCell>

										<TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
											<div className="flex justify-end items-center gap-2">
												<Button
													onClick={() => handleRowClick(project)}
													variant="outline"
													size="md"
													className="border-gray-200 font-medium cursor-pointer rounded-lg shadow-none"
												>
													<RiEyeLine className="mr-2 h-4 w-4" />
													<span>View</span>
												</Button>

												<DropdownMenu>
													<DropdownMenuTrigger
														render={
															<Button
																variant="ghost"
																size="icon"
																className="size-8 text-gray-500 hover:text-gray-900"
															>
																<RiMore2Line className="size-4" />
															</Button>
														}
													/>
													<DropdownMenuContent align="end" className="w-36 bg-white border-gray-200">
														<DropdownMenuItem
															onClick={() => {
																setProjectToEdit(project);
																setIsDialogOpen(true);
															}}
															className="text-xs text-gray-700 cursor-pointer"
														>
															<RiPencilLine className="size-3.5 mr-2" />
															<span>Edit Details</span>
														</DropdownMenuItem>
														<DropdownMenuItem
															onClick={(e) => handleDeleteClick(project, e)}
															className="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 cursor-pointer"
														>
															<RiDeleteBinLine className="size-3.5 mr-2" />
															<span>Delete</span>
														</DropdownMenuItem>
													</DropdownMenuContent>
												</DropdownMenu>
											</div>
										</TableCell>
									</TableRow>
								);
							})}
					</TableBody>
				</Table>
			</div>

			<ProjectDialog
				isOpen={isDialogOpen}
				onClose={() => setIsDialogOpen(false)}
				projectToEdit={projectToEdit}
			/>

			<ConfirmationModal
				isOpen={deleteModalOpen}
				onOpenChange={setDeleteModalOpen}
				title="Delete Project"
				description={`Are you sure you want to delete project "${projectToDelete?.name}"? All associated knowledge items will remain preserved.`}
				confirmText="Delete Project"
				cancelText="Cancel"
				variant="destructive"
				isLoading={deleteMutation.isPending}
				onConfirm={handleConfirmDelete}
			/>
		</div>
	);
}
