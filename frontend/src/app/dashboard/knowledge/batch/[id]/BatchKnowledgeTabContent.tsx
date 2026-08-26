"use client";

import { ChatPreview } from "@/components/shared/knowledge/ChatPreview";
import { ConfirmationModal } from "@/components/shared/knowledge/ConfirmationModal";
import { useState, forwardRef, useImperativeHandle } from "react";
import { useKnowledgeDetail, useEditKnowledge, useDeleteKnowledge } from "../../hooks/use-knowledge";
import { VisibilitySettings } from "../../api/types";
import { toast } from "sonner";
import { useRouter } from "next/navigation";

export interface BatchTabHandle {
	handleSave: (newTitle?: string) => Promise<void>;
	handleDelete: () => Promise<void>;
}

interface BatchKnowledgeTabContentProps {
	knowledgeId: string;
	isEditMode: boolean;
	setIsEditMode: (v: boolean) => void;
	headerNode?: React.ReactNode;
	preHeaderNode?: React.ReactNode;
	onDeleteSuccess?: (deletedId: string) => void;
}

export const BatchKnowledgeTabContent = forwardRef<BatchTabHandle, BatchKnowledgeTabContentProps>(
	({ knowledgeId, isEditMode, setIsEditMode, headerNode, preHeaderNode, onDeleteSuccess }, ref) => {
		const { data, isLoading, error } = useKnowledgeDetail(knowledgeId);
		const editKnowledge = useEditKnowledge();
		const deleteMutation = useDeleteKnowledge();
		const router = useRouter();

		const initialCategories = (data?.metadata?.categories as string[]) || (data?.metadata?.suggested_categories as Array<{ name: string }>)?.map((c) => c.name) || [];
		const initialVisibility = (data?.metadata?.visibility_settings as VisibilitySettings) || { clinics: ["all"], doctor_types: ["all"], doctors: ["all"] };
		
		const [pendingCategories, setPendingCategories] = useState<string[]>(initialCategories);
		const [pendingVisibilitySettings, setPendingVisibilitySettings] = useState<VisibilitySettings>(initialVisibility);
		const [pendingTitle, setPendingTitle] = useState(data?.title || "");
		const [prevMetadataStr, setPrevMetadataStr] = useState(JSON.stringify(data?.metadata || {}));
		const [prevTitle, setPrevTitle] = useState(data?.title);
		const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);

		if (JSON.stringify(data?.metadata || {}) !== prevMetadataStr) {
			setPrevMetadataStr(JSON.stringify(data?.metadata || {}));
			setPendingCategories(initialCategories);
			setPendingVisibilitySettings(initialVisibility);
		}
		
		if (data?.title !== prevTitle && !isEditMode) {
			setPrevTitle(data?.title);
			setPendingTitle(data?.title || "");
		}

		const handleSave = async (newTitle?: string) => {
			await editKnowledge.mutateAsync({ id: knowledgeId, data: { summary: data?.ai_summary || "", categories: pendingCategories, visibility_settings: pendingVisibilitySettings, title: typeof newTitle === 'string' ? newTitle : pendingTitle } });
			setIsEditMode(false);
		};

		const handleDelete = async () => {
			await deleteMutation.mutateAsync(knowledgeId);
			toast.success("Knowledge deleted successfully");
			if (onDeleteSuccess) {
				onDeleteSuccess(knowledgeId);
			} else {
				router.push("/dashboard/knowledge");
			}
		};

		useImperativeHandle(ref, () => ({
			handleSave,
			handleDelete: async () => {
				setIsDeleteModalOpen(true);
			}
		}));

		if (error) {
			return (
				<div className="flex items-center justify-center h-full text-red-500">
					Error loading document details
				</div>
			);
		}

		const handleCancel = () => {
			setPendingCategories(initialCategories);
			setPendingVisibilitySettings(initialVisibility);
			setPendingTitle(data?.title || "");
			setIsEditMode(false);
		};

		return (
			<div className="flex flex-col h-full bg-white relative">
				{/* Main Content Area */}
				<div className="flex flex-1 overflow-hidden">
					{/* Left Column (Chat / Preview) */}
					<ChatPreview
						knowledgeId={knowledgeId}
						knowledge={data}
						knowledgeStatus={data?.status}
						aiSummary={data?.ai_summary}
						fileName={undefined}
						files={(data?.metadata?.files as { file_name: string; summary: string }[]) || []}
						isDetailLoading={isLoading}
						isEditMode={isEditMode}
						categories={pendingCategories}
						onChangeCategories={setPendingCategories}
						visibilitySettings={pendingVisibilitySettings}
						onChangeVisibilitySettings={setPendingVisibilitySettings}
						title={pendingTitle}
						onChangeTitle={setPendingTitle}
						onSave={handleSave}
						onCancel={handleCancel}
						headerNode={headerNode}
						preHeaderNode={preHeaderNode}
					/>
				</div>

				{/* Delete Confirmation Modal */}
				<ConfirmationModal
					isOpen={isDeleteModalOpen}
					onOpenChange={setIsDeleteModalOpen}
					title="Delete Knowledge?"
					description="Are you certain you want to delete this knowledge? If you proceed, it will be removed from the chatbot."
					confirmText="Delete Knowledge"
					cancelText="Cancel"
					isLoading={deleteMutation.isPending}
					onConfirm={handleDelete}
				/>
			</div>
		);
	}
);
BatchKnowledgeTabContent.displayName = "BatchKnowledgeTabContent";

