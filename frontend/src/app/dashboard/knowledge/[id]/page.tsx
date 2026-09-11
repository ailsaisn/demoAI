"use client";

import { ChatPreview } from "@/app/dashboard/knowledge/components/preview/chat-preview";
import { ConfirmationModal } from "@/components/shared/confirmation-modal";
import { Button } from "@/components/ui/button";
import { RiArrowLeftLine, RiDeleteBin7Line, RiEdit2Line, RiCheckLine, RiStopCircleLine } from "@remixicon/react";

import { use, useState, useEffect } from "react";
import { useDeleteKnowledge, useKnowledgeDetail, useEditKnowledge } from "../hooks/use-knowledge";
import { useSession } from "@/hooks/use-session";
import { useSafeBack } from "@/hooks/use-safe-back";
import { VisibilitySettings, KnowledgeChunkItem, extractKnowledgeCategories } from "../api/types";

export default function KnowledgeDetailPage({ params }: { params: Promise<{ id: string }> }) {
	const unwrappedParams = use(params);
	const id = unwrappedParams.id;
	const { data, isLoading, error } = useKnowledgeDetail(id);
	const deleteMutation = useDeleteKnowledge();
	const { user } = useSession();
	const hasWriteAccess = user?.accesses?.includes("knowledge:write");
	const hasDeleteAccess = user?.accesses?.includes("knowledge:delete");
	const [isEditMode, setIsEditMode] = useState(false);
	const [isDeleteModalOpen, setIsDeleteModalOpen] = useState(false);
	const [isCancelModalOpen, setIsCancelModalOpen] = useState(false);
	const [isSaveModalOpen, setIsSaveModalOpen] = useState(false);
	const editKnowledge = useEditKnowledge();

	const fallbackPath = data?.project_id
		? `/dashboard/knowledge/project/${data.project_id}`
		: "/dashboard/knowledge";
	const handleBack = useSafeBack(fallbackPath);

	const initialCategories = extractKnowledgeCategories(data);
	const initialVisibility = (data?.metadata?.visibility_settings as VisibilitySettings) || { clinics: ["all"], doctor_types: ["all"], doctors: ["all"] };
	const initialChunks = (data?.metadata?.chunks as KnowledgeChunkItem[]) || [];
	
	const [pendingCategories, setPendingCategories] = useState<string[]>(initialCategories);
	const [pendingVisibilitySettings, setPendingVisibilitySettings] = useState<VisibilitySettings>(initialVisibility);
	const [pendingTitle, setPendingTitle] = useState(data?.title || "");
	const [pendingSummary, setPendingSummary] = useState(data?.ai_summary || "");
	const [pendingChunks, setPendingChunks] = useState<KnowledgeChunkItem[]>(initialChunks);

	useEffect(() => {
		if (!isEditMode && data) {
			const timer = setTimeout(() => {
				const cats = extractKnowledgeCategories(data);
				const vis = (data.metadata?.visibility_settings as VisibilitySettings) || { clinics: ["all"], doctor_types: ["all"], doctors: ["all"] };
				const chunks = (data.metadata?.chunks as KnowledgeChunkItem[]) || [];
				setPendingCategories(cats);
				setPendingVisibilitySettings(vis);
				setPendingTitle(data.title || "");
				setPendingSummary(data.ai_summary || "");
				setPendingChunks(chunks);
			}, 0);
			return () => clearTimeout(timer);
		}
	}, [data, isEditMode]);

	const handleDelete = async () => {
		await deleteMutation.mutateAsync(id);
		handleBack();
	};

	const formatDisplayTitle = (raw: string | undefined) => {
		if (!raw) return "Knowledge Document";
		return raw
			.replace(/\.[^/.]+$/, "") // strip extension
			.replace(/[_-]/g, " ") // replace underscores/dashes with spaces
			.replace(/\b\w/g, (c) => c.toUpperCase()); // title case
	};

	const handleSave = async (newTitle?: string) => {
		await editKnowledge.mutateAsync({
			id,
			data: {
				summary: pendingSummary || data?.ai_summary || "",
				categories: pendingCategories,
				visibility_settings: pendingVisibilitySettings,
				title: typeof newTitle === "string" ? newTitle : pendingTitle,
				chunks: pendingChunks.length > 0 ? pendingChunks : undefined,
			},
		});
		setIsEditMode(false);
	};

	const handleCancel = () => {
		setPendingCategories(initialCategories);
		setPendingVisibilitySettings(initialVisibility);
		setPendingTitle(data?.title || "");
		setPendingSummary(data?.ai_summary || "");
		setPendingChunks(initialChunks);
		setIsEditMode(false);
	};

	if (error) {
		return (
			<div className="flex items-center justify-center h-full text-red-500">
				Error loading document details
			</div>
		);
	}

	return (
		<div className="flex flex-col absolute inset-0">
			{/* Title Header with Actions */}
			<div className="flex items-center gap-3 px-4 py-3 border-b border-gray-200 shrink-0 bg-white justify-between">
				<div className="flex items-center gap-3 flex-1 min-w-0 mr-4">
					<Button
						variant="ghost"
						size="icon"
						onClick={handleBack}
						className="size-9 rounded-lg text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 shrink-0"
						title="Back"
						aria-label="Back"
					>
						<RiArrowLeftLine className="size-5" />
					</Button>
					<div className="flex-1 min-w-0 max-w-xl">
						<h1 className="text-base font-semibold text-zinc-900 truncate" title={formatDisplayTitle(isEditMode ? (pendingTitle || data?.title) : data?.title)}>
							{formatDisplayTitle(isEditMode ? (pendingTitle || data?.title) : data?.title)}
						</h1>
					</div>
				</div>

				<div className="flex items-center gap-2">
					{data?.status === "PROCESSING" && (
						<Button
							onClick={() => setIsCancelModalOpen(true)}
							disabled={deleteMutation.isPending || isLoading}
							variant="outline"
							className="gap-2 border-red-200 text-red-600 hover:text-red-700 hover:bg-red-50 hover:border-red-300 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
						>
							<RiStopCircleLine className="size-4" />
							Cancel Ingestion
						</Button>
					)}
					{(hasDeleteAccess || data?.status === "REJECTED" || data?.status === "PENDING" || data?.status === "PROCESSING") && (
						<Button
							onClick={() => setIsDeleteModalOpen(true)}
							disabled={deleteMutation.isPending || isLoading}
							variant="outline"
							className="gap-2 border-red-200 text-red-600 hover:text-red-700 hover:bg-red-50 hover:border-red-300 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
						>
							<RiDeleteBin7Line className="size-4" />
							{data?.status === "REJECTED" ? "Delete Record" : "Delete Knowledge"}
						</Button>
					)}
					{hasWriteAccess && data?.status === "APPROVED" && (
						<div className="flex items-center gap-2">
							{isEditMode && (
								<Button
									variant="outline"
									className="border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg shadow-none h-10 px-4 font-medium text-sm transition-colors cursor-pointer"
									disabled={isLoading || editKnowledge.isPending}
									onClick={handleCancel}
								>
									Cancel
								</Button>
							)}
							<Button
								variant={isEditMode ? "default" : "outline"}
								className={`gap-2 ${isEditMode ? "bg-blue-600 hover:bg-blue-700 text-white" : "border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50"} rounded-lg shadow-none h-10 px-4 font-medium text-sm transition-colors cursor-pointer`}
								disabled={isLoading || editKnowledge.isPending}
								onClick={() => {
									if (isEditMode) {
										setIsSaveModalOpen(true);
									} else {
										setPendingSummary(data?.ai_summary || "");
										setIsEditMode(true);
									}
								}}
							>
								{isEditMode ? <RiCheckLine className="size-4" /> : <RiEdit2Line className="size-4" />}
								{isEditMode ? "Save Knowledge" : "Edit Knowledge"}
							</Button>
						</div>
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
					aiSummary={pendingSummary || data?.ai_summary}
					summaryValue={pendingSummary}
					onChangeSummary={setPendingSummary}
					fileName={data?.file_name}
					initialPrompt={(data?.metadata?.initial_prompt as string) || undefined}
					files={(data?.metadata?.files as { file_name: string; summary: string }[]) || []}
					isDetailLoading={isLoading}
					isEditMode={isEditMode}
					categories={pendingCategories}
					onChangeCategories={setPendingCategories}
					chunks={pendingChunks}
					onChangeChunks={setPendingChunks}
					visibilitySettings={pendingVisibilitySettings}
					onChangeVisibilitySettings={setPendingVisibilitySettings}
					title={pendingTitle}
					onChangeTitle={setPendingTitle}
					onSave={() => setIsSaveModalOpen(true)}
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

			{/* Cancel Ingestion Confirmation Modal */}
			<ConfirmationModal
				isOpen={isCancelModalOpen}
				onOpenChange={setIsCancelModalOpen}
				title="Cancel Ingestion?"
				description="Are you sure you want to cancel the ingestion process for this document? The pending draft and temporary files will be discarded."
				confirmText="Cancel Ingestion"
				cancelText="Keep Processing"
				isLoading={deleteMutation.isPending}
				onConfirm={handleDelete}
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
