"use client";

import { ChatPreview } from "@/app/dashboard/knowledge/components/preview/chat-preview";
import { ConfirmationModal } from "@/components/shared/confirmation-modal";
import { Button } from "@/components/ui/button";
import { RiArrowLeftLine, RiDeleteBin7Line, RiEdit2Line, RiCheckLine } from "@remixicon/react";
import { toast } from "sonner";

import { useRouter } from "next/navigation";
import { use, useState } from "react";
import { useDeleteKnowledge, useKnowledgeDetail, useEditKnowledge } from "../hooks/use-knowledge";
import { useSession } from "@/hooks/use-session";
import { VisibilitySettings } from "../api/types";

export default function KnowledgeDetailPage({ params }: { params: Promise<{ id: string }> }) {
	const router = useRouter();
	const unwrappedParams = use(params);
	const id = unwrappedParams.id;
	const { data, isLoading, error } = useKnowledgeDetail(id);
	const deleteMutation = useDeleteKnowledge();
	const { user } = useSession();
	const hasWriteAccess = user?.accesses?.includes("knowledge:write");
	const hasDeleteAccess = user?.accesses?.includes("knowledge:delete");
	const [isEditMode, setIsEditMode] = useState(false);
	const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
	const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
	const editKnowledge = useEditKnowledge();

	const initialCategories = (data?.metadata?.categories as string[]) || (data?.metadata?.suggested_categories as Array<{ name: string }>)?.map((c) => c.name) || [];
	const initialVisibility = (data?.metadata?.visibility_settings as VisibilitySettings) || { clinics: ["all"], doctor_types: ["all"], doctors: ["all"] };
	
	const [pendingCategories, setPendingCategories] = useState<string[]>(initialCategories);
	const [pendingVisibilitySettings, setPendingVisibilitySettings] = useState<VisibilitySettings>(initialVisibility);
	const [pendingTitle, setPendingTitle] = useState(data?.title || "");
	const [prevMetadataStr, setPrevMetadataStr] = useState(JSON.stringify(data?.metadata || {}));
	const [prevTitle, setPrevTitle] = useState(data?.title);

	if (JSON.stringify(data?.metadata || {}) !== prevMetadataStr) {
		setPrevMetadataStr(JSON.stringify(data?.metadata || {}));
		setPendingCategories(initialCategories);
		setPendingVisibilitySettings(initialVisibility);
	}
	
	if (data?.title !== prevTitle && !isEditMode) {
		setPrevTitle(data?.title);
		setPendingTitle(data?.title || "");
	}

	const handleDelete = async () => {
		await deleteMutation.mutateAsync(id);
		router.push("/dashboard/knowledge");
	};

	if (error) {
		return (
			<div className="flex items-center justify-center h-full text-red-500">
				Error loading document details
			</div>
		);
	}

	const formatDisplayTitle = (raw: string | undefined) => {
		if (!raw) return "Knowledge Document";
		return raw
			.replace(/\.[^/.]+$/, "") // strip extension
			.replace(/[_-]/g, " ") // replace underscores/dashes with spaces
			.replace(/\b\w/g, (c) => c.toUpperCase()); // title case
	};

	const handleSave = async (newTitle?: string) => {
		await editKnowledge.mutateAsync({ id, data: { summary: data?.ai_summary || "", categories: pendingCategories, visibility_settings: pendingVisibilitySettings, title: typeof newTitle === 'string' ? newTitle : pendingTitle } });
		setIsEditMode(false);
	};

	const handleCancel = () => {
		setPendingCategories(initialCategories);
		setPendingVisibilitySettings(initialVisibility);
		setPendingTitle(data?.title || "");
		setIsEditMode(false);
	};

	return (
		<div className="flex flex-col absolute inset-0">
			{/* Title Header with Actions */}
			<div className="flex items-center gap-4 p-4 border-b border-gray-200 shrink-0 bg-white justify-between">
				<div className="flex items-center gap-4">
					<Button
						variant="ghost"
						size="icon"
						onClick={() => router.back()}
						className="size-9 rounded-lg text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100"
					>
						<RiArrowLeftLine className="size-5" />
					</Button>
					<div>
						{isEditMode ? (
							<input
								value={pendingTitle}
								onChange={(e) => setPendingTitle(e.target.value)}
								className="text-lg font-semibold text-gray-900 border-b border-blue-500 focus:outline-none bg-transparent"
								placeholder="Knowledge Document Title"
							/>
						) : (
							<h1 className="text-lg font-semibold text-gray-900">{formatDisplayTitle(data?.title)}</h1>
						)}
						<p className="text-sm text-zinc-600">Knowledge Document Details</p>
					</div>
				</div>

				<div className="flex items-center gap-2">
					{hasDeleteAccess && data?.status === "APPROVED" && (
						<Button
							onClick={() => setIsDeleteModalOpen(true)}
							disabled={deleteMutation.isPending || isLoading}
							variant="outline"
							className="gap-2 border-red-200 text-red-600 hover:text-red-700 hover:bg-red-50 hover:border-red-300 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
						>
							<RiDeleteBin7Line className="size-4" />
							Delete Knowledge
						</Button>
					)}
					{hasWriteAccess && data?.status === "APPROVED" && (
						<Button
							variant={isEditMode ? "default" : "outline"}
							className={`gap-2 ${isEditMode ? "bg-blue-600 hover:bg-blue-700 text-white" : "border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50"} rounded-lg shadow-none h-10 px-4 font-medium text-sm transition-colors cursor-pointer`}
							disabled={isLoading || editKnowledge.isPending}
							onClick={() => {
								if (isEditMode) {
									setIsSaveModalOpen(true);
								} else {
									toast.info("You can now edit the document categories below.");
									setIsEditMode(true);
								}
							}}
						>
							{isEditMode ? <RiCheckLine className="size-4" /> : <RiEdit2Line className="size-4" />}
							{isEditMode ? "Save" : "Edit Knowledge"}
						</Button>
					)}

				</div>
			</div>

			{/* Main Content Area */}
			<div className="flex flex-1 overflow-hidden">
				{/* Left Column (Chat / Preview) */}
				<ChatPreview
					knowledgeId={id}
					knowledge={data}
					knowledgeStatus={data?.status}
					aiSummary={data?.ai_summary}
					fileName={data?.file_name}
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
				/>
			</div>

			{/* Save Knowledge Confirmation Modal */}
			<ConfirmationModal
				isOpen={isSaveModalOpen}
				onOpenChange={setIsSaveModalOpen}
				title="Save Knowledge?"
				description="Are you sure you want to save the changes of the  knowledge? If you confirm, it will be implemented into the chatbot."
				confirmText="Save Knowledge"
				cancelText="Cancel"
				isLoading={editKnowledge.isPending}
				onConfirm={handleSave}
			/>

			{/* Delete Knowledge Confirmation Modal */}
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
