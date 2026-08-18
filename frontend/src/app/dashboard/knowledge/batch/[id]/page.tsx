"use client";

import {
	Attachment,
	AttachmentContent,
	AttachmentDescription,
	AttachmentMedia,
	AttachmentTitle,
} from "@/components/ui/attachment";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
import { useDeleteKnowledge, useKnowledgeBatch } from "../../hooks/use-knowledge";
import { BatchKnowledgeTabContent, BatchTabHandle } from "./BatchKnowledgeTabContent";

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

	const batchFeedbacks = batchDocuments
		.map((d, i) => {
			const feedback = (d.metadata as Record<string, unknown>)?.feedback as string | undefined;
			if (!feedback) return null;
			const title = d.title || `Document ${i + 1}`;
			return `• ${title}:\n  ${feedback}`;
		})
		.filter(Boolean);

	const batchFeedback = batchFeedbacks.length > 0 ? batchFeedbacks.join("\n\n") : undefined;

	const isEditMode = editModes[currentTab] || false;

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

	return (
		<div className="flex flex-col h-full bg-white relative">
			{/* Header */}
			<div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-200 justify-between bg-white/50 backdrop-blur-sm z-10 sticky top-0">
				<div className="flex items-center gap-3">
					<Button
						variant="ghost"
						size="icon"
						onClick={() => router.back()}
						className="h-8 w-8 text-zinc-500 hover:text-zinc-900"
					>
						<RiArrowLeftLine className="size-4" />
					</Button>
					<h1 className="text-base font-semibold text-zinc-900">Batch Review Session</h1>
				</div>
				<div className="flex items-center gap-3">
					{hasDeleteAccess && activeDoc?.status === "APPROVED" && (
						<Button
							variant="outline"
							className="gap-2 text-red-600 hover:text-red-700 hover:bg-red-50 border-red-200"
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
							className={`gap-2 ${isEditMode ? "bg-blue-600 hover:bg-blue-700 text-white" : "text-zinc-950"}`}
							disabled={isLoading}
							onClick={handleEditToggle}
						>
							{isEditMode ? <RiCheckLine className="size-4" /> : <RiEdit2Line className="size-4" />}
							{isEditMode ? "Save" : "Edit Knowledge"}
						</Button>
					)}
				</div>
			</div>

			{/* Chat Area */}
			<div className="flex-1 overflow-hidden flex flex-col w-full">
				<div className="flex-1 overflow-hidden relative">
					{batchDocuments.map((doc) => {
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

						const preHeaderNode = (
							<div className="flex flex-row flex-wrap justify-end gap-2 mb-4 self-end">
								{batchDocuments.map((tabDoc) => {
									const fileName = tabDoc.file_name || tabDoc.title || "Document";
									const { Icon, bgColor, textColor } = getFileIconAndColor(fileName);
									return (
										<Attachment
											key={tabDoc.id}
											className="bg-white border border-zinc-200 shadow-none p-1.5 w-fit min-w-40 max-w-sm rounded-lg"
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
													DOCUMENT
												</AttachmentDescription>
											</AttachmentContent>
										</Attachment>
									);
								})}
							</div>
						);

						const headerNode = (
							<div className="flex flex-col gap-4 mb-4 pb-4 border-b border-blue-200/50">
								{/* Executive Summary Section */}
								{batchFeedback && (
									<div className="bg-zinc-100/50 rounded-lg p-4 w-full text-zinc-950 mb-4">
										<div className="flex items-center gap-2 text-blue-600 mb-2">
											<RiSparklingLine className="size-5" />
											<h3 className="font-semibold text-sm">Executive Summary</h3>
										</div>
										<p className="text-sm leading-relaxed whitespace-pre-wrap">{batchFeedback}</p>
									</div>
								)}

								{/* Tabs Layout */}
								<div>
									<h4 className="text-xs font-semibold text-blue-900/70 uppercase tracking-wider mb-2">
										Documents in this batch
									</h4>
									<Tabs value={currentTab} onValueChange={setActiveTab} className="w-full">
										<TabsList variant="line" className="mb-2">
											{batchDocuments.map((tabDoc, tabIndex) => (
												<TabsTrigger
													key={tabDoc.id}
													value={tabDoc.id}
													className="font-medium text-xs text-blue-900/60 hover:text-blue-600 data-active:text-blue-600 data-active:after:bg-blue-600"
												>
													<span className="truncate max-w-40">
														{tabDoc.title || `Document ${tabIndex + 1}`}
													</span>
													{tabDoc.status === "PROCESSING" && (
														<span className="ml-2 inline-flex items-center rounded-full bg-blue-100 px-1.5 py-0.5 text-[10px] font-medium text-blue-700 shrink-0">
															Processing
														</span>
													)}
													{tabDoc.status === "PENDING" && (
														<span className="ml-2 inline-flex items-center rounded-full bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 shrink-0">
															Review
														</span>
													)}
												</TabsTrigger>
											))}
										</TabsList>
									</Tabs>
								</div>
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
								/>
							</div>
						);
					})}
				</div>
			</div>
		</div>
	);
}
