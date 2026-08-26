"use client";

import { useState, useEffect, useMemo } from "react";
import { toast } from "sonner";
import {
	Dialog,
	DialogContent,
	DialogFooter,
	DialogHeader,
	DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel, FieldContent } from "@/components/ui/field";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import { useProjects } from "../hooks/use-projects";
import { useUpdateKnowledgeProject } from "../hooks/use-knowledge";
import { RiLoader4Line } from "@remixicon/react";

interface AttachProjectDialogProps {
	isOpen: boolean;
	onClose: () => void;
	knowledgeId: string | null;
	knowledgeIds?: string[];
	knowledgeTitle: string;
	currentProjectId?: string | null;
}

export function AttachProjectDialog({
	isOpen,
	onClose,
	knowledgeId,
	knowledgeIds,
	currentProjectId = null,
}: AttachProjectDialogProps) {
	const { data: projects = [], isLoading: isLoadingProjects } = useProjects();
	const updateKnowledgeProjectMutation = useUpdateKnowledgeProject();

	const [selectedProjectId, setSelectedProjectId] = useState<string>("none");

	const selectedProjectName = useMemo(() => {
		if (!selectedProjectId || selectedProjectId === "none") {
			return "No Project";
		}
		const found = projects.find((p) => p.id === selectedProjectId);
		return found ? found.name : "Select Project";
	}, [selectedProjectId, projects]);

	useEffect(() => {
		const timer = setTimeout(() => {
			if (isOpen) {
				if (!currentProjectId || currentProjectId === "none") {
					setSelectedProjectId("none");
				} else if (projects.length > 0) {
					const exists = projects.some((p) => p.id === currentProjectId);
					setSelectedProjectId(exists ? currentProjectId : "none");
				} else {
					setSelectedProjectId(currentProjectId);
				}
			}
		}, 0);
		return () => clearTimeout(timer);
	}, [isOpen, currentProjectId, projects]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		const isValidProject = selectedProjectId !== "none" && projects.some((p) => p.id === selectedProjectId);
		const targetProjectId = isValidProject ? selectedProjectId : null;
		const idsToUpdate = knowledgeIds && knowledgeIds.length > 0 ? knowledgeIds : knowledgeId ? [knowledgeId] : [];
		if (idsToUpdate.length === 0) return;

		try {
			if (idsToUpdate.length > 1) {
				await Promise.all(
					idsToUpdate.map((id) =>
						updateKnowledgeProjectMutation.mutateAsync({
							knowledgeId: id,
							projectId: targetProjectId,
							hideToast: true,
						}),
					),
				);
				toast.success(`All ${idsToUpdate.length} documents attached to project successfully!`);
			} else {
				await updateKnowledgeProjectMutation.mutateAsync({
					knowledgeId: idsToUpdate[0],
					projectId: targetProjectId,
				});
			}
			onClose();
		} catch {
			// handled by mutation
		}
	};

	return (
		<Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
			<DialogContent className="sm:max-w-md w-full bg-white p-6 rounded-xl border border-gray-200 shadow-xl">
				<form onSubmit={handleSubmit} className="space-y-4">
					<DialogHeader className="p-0 pb-1">
						<DialogTitle className="text-base font-medium text-neutral-950">
							Attach Knowledge to Project
						</DialogTitle>
					</DialogHeader>

					<Field className="space-y-2">
						<FieldLabel className="text-sm font-normal text-neutral-950">
							Project
						</FieldLabel>
						<FieldContent>
							<Select
								value={selectedProjectId}
								onValueChange={(val) => setSelectedProjectId(val ?? "none")}
								disabled={isLoadingProjects || updateKnowledgeProjectMutation.isPending}
							>
								<SelectTrigger className="w-full h-10 border-gray-200 bg-white text-gray-700 rounded-lg px-3">
									<SelectValue placeholder="Select Project">
										{selectedProjectName}
									</SelectValue>
								</SelectTrigger>
								<SelectContent alignItemWithTrigger={false} sideOffset={4} className="bg-white">
									<SelectItem value="none">No Project</SelectItem>
									{projects.map((project) => (
										<SelectItem key={project.id} value={project.id}>
											{project.name}
										</SelectItem>
									))}
								</SelectContent>
							</Select>
						</FieldContent>
					</Field>

					<DialogFooter className="flex items-center justify-end gap-3 pt-4 border-t-0 p-0">
						<Button
							type="button"
							variant="outline"
							onClick={onClose}
							disabled={updateKnowledgeProjectMutation.isPending}
							className="h-10 px-5 border-blue-500 text-blue-500 hover:bg-blue-50 hover:text-blue-600 rounded-lg font-medium cursor-pointer shadow-none"
						>
							Cancel
						</Button>
						<Button
							type="submit"
							disabled={updateKnowledgeProjectMutation.isPending || isLoadingProjects}
							className="h-10 px-5 bg-blue-500 hover:bg-blue-600 text-white rounded-lg font-medium cursor-pointer shadow-none gap-2"
						>
							{updateKnowledgeProjectMutation.isPending && (
								<RiLoader4Line className="size-4 animate-spin" />
							)}
							<span>Attach Knowledge</span>
						</Button>
					</DialogFooter>
				</form>
			</DialogContent>
		</Dialog>
	);
}
