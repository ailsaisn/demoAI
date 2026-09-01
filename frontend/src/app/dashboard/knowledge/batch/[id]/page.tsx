"use client";

import {
	Attachment,
	AttachmentContent,
	AttachmentDescription,
	AttachmentMedia,
	AttachmentTitle,
} from "@/components/ui/attachment";
import { Button } from "@/components/ui/button";
import { useSession } from "@/hooks/use-session";
import {
	RiArrowLeftLine,
	RiCheckLine,
	RiDeleteBin7Line,
	RiEdit2Line,
	RiFileExcel2Line,
	RiFilePdf2Line,
	RiFileTextLine,
	RiFileWord2Line,
	RiImage2Line,
	RiSparklingLine,
} from "@remixicon/react";
import { useRouter } from "next/navigation";
import { use, useRef, useState } from "react";
import { toast } from "sonner";
import { ConfirmationModal } from "@/components/shared/confirmation-modal";
import { IngestSuccessModal } from "@/app/dashboard/knowledge/components/preview/ingest-success-modal";
import { useApproveBatchKnowledge, useDeleteKnowledge, useKnowledgeBatch } from "../../hooks/use-knowledge";
import { BatchKnowledgeTabContent, BatchTabHandle } from "./BatchKnowledgeTabContent";
import { BatchDocumentTabs } from "./BatchDocumentTabs";

export default function BatchKnowledgePage({ params }: { params: Promise<{ id: string }> }) {
	const router = useRouter();
	const unwrappedParams = use(params);
	const batchId = unwrappedParams.id;
	const { data: batchDocuments, isLoading, error } = useKnowledgeBatch(batchId);
	const [activeTab, setActiveTab] = useState<string | undefined>(undefined);
	const { user } = useSession();
	const hasWriteAccess = user?.accesses?.includes("knowledge:write");
	const hasDeleteAccess = user?.accesses?.includes("knowledge:delete");
	const deleteMutation = useDeleteKnowledge();
	const approveBatchMutation = useApproveBatchKnowledge();

	const [isApproveAllOpen, setIsApproveAllOpen] = useState(false);
	const [isSuccessOpen, setIsSuccessOpen] = useState(false);
	const [editModes, setEditModes] = useState<Record<string, boolean>>({});
	const tabRefs = useRef<Record<string, BatchTabHandle | null>>({});

	if (error) {
		return (
			<div className="flex items-center justify-center h-full text-red-500">
				Error loading batch details
			</div>
		);
	}

	if (isLoading || !batchDocuments) {
		return (
			<div className="flex items-center justify-center h-full text-zinc-500">
				Loading batch documents...
			</div>
		);
	}

	if (batchDocuments.length === 0) {
		return (
			<div className="flex items-center justify-center h-full text-zinc-500">
				No documents found for this batch.
			</div>
		);
	}

	const currentTab = activeTab || batchDocuments[0].id;
	const activeDoc = batchDocuments.find((d) => d.id === currentTab) || batchDocuments[0];

	const batchSummary = (
		batchDocuments.find((d) => (d.metadata as Record<string, unknown>)?.batch_summary)?.metadata as Record<string, unknown>
	)?.batch_summary as string | undefined;

	const fallbackFeedbacks = batchDocuments
		.map((d, i) => {
			const feedback = (d.metadata as Record<string, unknown>)?.feedback as string | undefined;
			if (!feedback) return null;
			const title = d.title || `Document ${i + 1}`;
			return `• ${title}:\n  ${feedback}`;
		})
		.filter(Boolean);

	const displayedSummary = batchSummary || (fallbackFeedbacks.length > 0 ? fallbackFeedbacks.join("\n\n") : undefined);

	const isEditMode = editModes[currentTab] || false;
	const hasPendingDocs = batchDocuments.some((d) => d.status !== "APPROVED");

	const handleEditToggle = async () => {
		if (isEditMode) {
			await tabRefs.current[currentTab]?.handleSave();
		} else {
			toast.info("You can now edit the document categories below.");
			setEditModes((prev) => ({ ...prev, [currentTab]: true }));
		}
	};

	const handleDelete = async () => {
		await tabRefs.current[currentTab]?.handleDelete();
	};

	const handleDeleteSuccess = (deletedId: string) => {
		const remaining = batchDocuments.filter((d) => d.id !== deletedId);
		if (remaining.length === 0) {
			router.push("/dashboard/knowledge");
		} else {
			setActiveTab(remaining[0].id);
		}
	};

	const getFileIconAndColor = (filename?: string | null) => {
		if (!filename)
			return { Icon: RiFileTextLine, bgColor: "bg-blue-50", textColor: "text-blue-600" };
		const ext = filename.split(".").pop()?.toLowerCase() || "";
		switch (ext) {
			case "pdf":
				return { Icon: RiFilePdf2Line, bgColor: "bg-red-50", textColor: "text-red-600" };
			case "doc":
			case "docx":
				return {
					Icon: RiFileWord2Line,
					bgColor: "bg-blue-50",
					textColor: "text-blue-600",
				};
			case "xls":
			case "xlsx":
			case "csv":
				return {
					Icon: RiFileExcel2Line,
					bgColor: "bg-emerald-50",
					textColor: "text-emerald-600",
				};
			case "png":
			case "jpg":
			case "jpeg":
			case "gif":
				return {
					Icon: RiImage2Line,
					bgColor: "bg-purple-50",
					textColor: "text-purple-600",
				};
			case "txt":
			default:
				return {
					Icon: RiFileTextLine,
					bgColor: "bg-blue-50",
					textColor: "text-blue-600",
				};
		}
	};

	return (
		<div className="flex flex-col h-full bg-white relative">
			{/* Header */}
			<div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-200 justify-between bg-white/50 backdrop-blur-sm z-10 sticky top-0">
				<div className="flex items-center gap-3">
					<Button
						variant="ghost"
						size="icon"
						onClick={() => router.back()}
						className="size-9 rounded-lg text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100"
					>
						<RiArrowLeftLine className="size-5" />
					</Button>
					<h1 className="text-base font-semibold text-zinc-900">Batch Review Session</h1>
				</div>
				<div className="flex items-center gap-2">
					{hasWriteAccess && hasPendingDocs && (
						<Button
							variant="default"
							className="gap-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
							disabled={isLoading || approveBatchMutation.isPending}
							onClick={() => setIsApproveAllOpen(true)}
						>
							<RiCheckLine className="size-4" />
							Approve All
						</Button>
					)}
					{hasDeleteAccess && activeDoc?.status === "APPROVED" && (
						<Button
							variant="outline"
							className="gap-2 border-red-200 text-red-600 hover:text-red-700 hover:bg-red-50 hover:border-red-300 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
							onClick={handleDelete}
							disabled={deleteMutation.isPending || isLoading}
						>
							<RiDeleteBin7Line className="size-4" />
							Delete Knowledge
						</Button>
					)}
					{hasWriteAccess && activeDoc?.status === "APPROVED" && (
						<Button
							variant={isEditMode ? "default" : "outline"}
							className={`gap-2 ${isEditMode ? "bg-blue-600 hover:bg-blue-700 text-white" : "border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50"} rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none`}
							disabled={isLoading}
							onClick={handleEditToggle}
						>
							{isEditMode ? <RiCheckLine className="size-4" /> : <RiEdit2Line className="size-4" />}
							{isEditMode ? "Save" : "Edit Knowledge"}
						</Button>
					)}
				</div>
			</div>

			{/* Active Tab View */}
			<div className="flex-1 overflow-hidden flex flex-col w-full">
				<div className="flex-1 overflow-hidden relative">
					{batchDocuments.map((doc) => {
						const preHeaderNode = (
							<div className="flex flex-row flex-wrap justify-end gap-2 mb-4 self-end max-h-36 overflow-y-auto w-full min-w-0 max-w-full pr-1">
								{batchDocuments.map((tabDoc) => {
									const fileName = tabDoc.file_name || tabDoc.title || "Document";
									const { Icon, bgColor, textColor } = getFileIconAndColor(fileName);
									return (
										<Attachment
											key={tabDoc.id}
											className="bg-white border border-zinc-200 shadow-none p-1.5 w-fit min-w-40 max-w-xs rounded-lg shrink-0"
										>
											<AttachmentMedia
												className={`${bgColor} ${textColor} shrink-0 rounded-lg p-2`}
											>
												<Icon className="size-5" />
											</AttachmentMedia>
											<AttachmentContent className="overflow-hidden min-w-0 pr-2">
												<AttachmentTitle className="text-[13px] font-medium text-zinc-950 truncate block">
													{fileName}
												</AttachmentTitle>
												<AttachmentDescription className="text-[11px] text-zinc-500 uppercase">
													{fileName.split(".").pop() || "FILE"}
												</AttachmentDescription>
											</AttachmentContent>
										</Attachment>
									);
								})}
							</div>
						);

						const headerNode = (
							<div className="flex flex-col gap-4 mb-4 w-full min-w-0 max-w-full">
								{/* Batch Summary Box if present */}
								{displayedSummary && (
									<div className="bg-zinc-100/50 rounded-lg p-4 w-full min-w-0 max-w-full text-zinc-950">
										<div className="flex items-center gap-2 text-blue-600 mb-2">
											<RiSparklingLine className="size-5 shrink-0" />
											<h3 className="font-semibold text-sm truncate">Executive Summary</h3>
										</div>
										<p className="text-sm leading-relaxed whitespace-pre-wrap wrap-break-word">{displayedSummary}</p>
									</div>
								)}

								{/* Batch Documents Tabs Bar */}
								<BatchDocumentTabs
									documents={batchDocuments}
									activeId={currentTab}
									onSelectDoc={setActiveTab}
								/>
							</div>
						);

						return (
							<div
								key={doc.id}
								className={`absolute inset-0 m-0 flex flex-col bg-white ${currentTab !== doc.id ? "hidden" : ""}`}
							>
								<BatchKnowledgeTabContent
									knowledgeId={doc.id}
									ref={(el) => {
										tabRefs.current[doc.id] = el;
									}}
									isEditMode={editModes[doc.id] || false}
									setIsEditMode={(v) => setEditModes((prev) => ({ ...prev, [doc.id]: v }))}
									headerNode={headerNode}
									preHeaderNode={preHeaderNode}
									onDeleteSuccess={handleDeleteSuccess}
								/>
							</div>
						);
					})}
				</div>
			</div>

			{/* Approve All Confirmation Modal */}
			<ConfirmationModal
				isOpen={isApproveAllOpen}
				onOpenChange={setIsApproveAllOpen}
				title="Approve All Documents"
				description={`Are you sure you want to approve and index all ${batchDocuments.length} document(s) in this batch into the AI Knowledge Base?`}
				confirmText="Approve All"
				isLoading={approveBatchMutation.isPending}
				onConfirm={async () => {
					await approveBatchMutation.mutateAsync(batchId);
					setIsSuccessOpen(true);
				}}
			/>

			{/* Batch Ingest Success Modal */}
			<IngestSuccessModal
				isOpen={isSuccessOpen}
				onOpenChange={setIsSuccessOpen}
				title="Batch Approved Successfully"
				description="All documents in this batch have been approved and indexed into the system."
				buttonText="Back to Knowledge Base"
				onAction={() => router.push("/dashboard/knowledge")}
			/>
		</div>
	);
}
