"use client";

import { useState, useEffect } from "react";
import {
	Dialog,
	DialogContent,
	DialogDescription,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field, FieldLabel, FieldContent } from "@/components/ui/field";
import { useCreateProject, useUpdateProject } from "../hooks/use-projects";
import type { ProjectResponse } from "../api/types";
import { RiLoader4Line } from "@remixicon/react";

interface ProjectDialogProps {
	isOpen: boolean;
	onClose: () => void;
	projectToEdit?: ProjectResponse | null;
}

export function ProjectDialog({ isOpen, onClose, projectToEdit }: ProjectDialogProps) {
	const [name, setName] = useState("");
	const [error, setError] = useState<string | null>(null);

	const createMutation = useCreateProject();
	const updateMutation = useUpdateProject();

	const isEditing = !!projectToEdit;
	const isPending = createMutation.isPending || updateMutation.isPending;

	useEffect(() => {
		const timer = setTimeout(() => {
			if (isOpen) {
				if (projectToEdit) {
					setName(projectToEdit.name || "");
				} else {
					setName("");
				}
				setError(null);
			}
		}, 0);
		return () => clearTimeout(timer);
	}, [isOpen, projectToEdit]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		if (!name.trim()) {
			setError("Project name is required.");
			return;
		}

		setError(null);

		if (isEditing && projectToEdit) {
			updateMutation.mutate(
				{
					id: projectToEdit.id,
					data: {
						name: name.trim(),
					},
				},
				{
					onSuccess: () => {
						onClose();
					},
				},
			);
		} else {
			createMutation.mutate(
				{
					name: name.trim(),
				},
				{
					onSuccess: () => {
						onClose();
					},
				},
			);
		}
	};

	return (
		<Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
			<DialogContent className="sm:max-w-md p-6 bg-white rounded-xl border border-gray-200 shadow-xl">
				<DialogHeader className="space-y-1">
					<DialogTitle className="text-base font-semibold text-zinc-950">
						{isEditing ? "Edit Project" : "Add Project"}
					</DialogTitle>
					<DialogDescription className="text-xs text-zinc-500">
						{isEditing
							? "Update the project workspace name."
							: "Create a new project workspace to group and organize knowledge documents."}
					</DialogDescription>
				</DialogHeader>

				<form onSubmit={handleSubmit} className="space-y-4 py-2">
					<Field className="space-y-2">
						<FieldLabel className="text-xs font-medium text-zinc-700">Project Title *</FieldLabel>
						<FieldContent>
							<Input
								autoComplete="off"
								placeholder="e.g. ERHA Acne Treatment 2026"
								value={name}
								onChange={(e) => setName(e.target.value)}
								className="border-gray-200 bg-white focus-visible:ring-blue-500 text-sm h-9"
							/>
						</FieldContent>
					</Field>

					{error && <p className="text-xs font-medium text-red-600">{error}</p>}

					<DialogFooter className="pt-2 gap-2">
						<Button
							type="button"
							variant="outline"
							size="sm"
							onClick={onClose}
							disabled={isPending}
							className="h-9 px-4 text-xs font-medium text-gray-700 hover:bg-gray-50 border-gray-200 rounded-lg cursor-pointer"
						>
							Cancel
						</Button>
						<Button
							type="submit"
							size="sm"
							disabled={isPending}
							className="h-9 px-4 text-xs font-medium bg-blue-500 hover:bg-blue-600 text-white rounded-lg cursor-pointer shadow-none gap-1.5"
						>
							{isPending && <RiLoader4Line className="w-3.5 h-3.5 animate-spin" />}
							<span>{isEditing ? "Save Changes" : "Create Project"}</span>
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
