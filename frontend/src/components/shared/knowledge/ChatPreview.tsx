import { knowledgeKeys } from "@/app/dashboard/knowledge/api/keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
	MessageScroller,
	MessageScrollerSmartButton,
	MessageScrollerContent,
	MessageScrollerItem,
	MessageScrollerProvider,
	MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import {
	Attachment,
	AttachmentMedia,
	AttachmentContent,
	AttachmentTitle,
	AttachmentDescription,
	AttachmentActions,
	AttachmentAction,
} from "@/components/ui/attachment";
import { api } from "@/lib/axios";
import {
	RiAttachment2,
	RiCheckLine,
	RiCloseLine,
	RiCornerDownLeftLine,
	RiFilePdf2Line,
	RiFileWord2Line,
	RiFileExcel2Line,
	RiImage2Line,
	RiFileTextLine,
	RiLoader4Line,
	RiRobot2Line,
	RiUser3Line,
	RiUploadCloud2Line,
} from "@remixicon/react";
import { useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useRef, useMemo } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { VisibilitySettings as VisibilitySettingsUI } from "./VisibilitySettings";
import {
	VisibilitySettings as IVisibilitySettings,
	KnowledgeResponse,
} from "@/app/dashboard/knowledge/api/types";
import {
	useGeneralChatSession,
	useSendGeneralChatMessage,
} from "@/app/dashboard/knowledge/hooks/use-knowledge";
import { CategorySettings } from "./CategorySettings";
import { ClassificationSidebar } from "./ClassificationSidebar";
import { TitleSettings } from "./TitleSettings";

interface ChatPreviewProps {
	mode?: "knowledge" | "general";
	sessionId?: string | null;
	initialPrompt?: string;
	knowledgeId?: string;
	knowledge?: KnowledgeResponse;
	knowledgeStatus?: string;
	aiSummary?: string | null;
	fileName?: string | null;
	files?: { file_name: string; summary: string; [key: string]: unknown }[];
	isDetailLoading?: boolean;
	isEditMode?: boolean;
	categories?: string[];
	onChangeCategories?: (newCategories: string[]) => void;
	visibilitySettings?: IVisibilitySettings;
	onChangeVisibilitySettings?: (settings: IVisibilitySettings) => void;
	title?: string;
	onChangeTitle?: (title: string) => void;
	onSave?: (newTitle?: string) => void;
	onCancel?: () => void;
	headerNode?: React.ReactNode;
	preHeaderNode?: React.ReactNode;
}

interface Message {
	role: "user" | "assistant";
	content: string;
	attachmentName?: string;
	attachmentNames?: string[];
	action?: string;
	target_knowledge_id?: string | null;
	total_found?: number;
}

export function ChatPreview({
	mode = "knowledge",
	sessionId,
	initialPrompt,
	knowledgeId,
	knowledge,
	knowledgeStatus,
	aiSummary,
	fileName,
	files = [],
	isDetailLoading = false,
	isEditMode = false,
	categories = [],
	onChangeCategories,
	visibilitySettings,
	onChangeVisibilitySettings,
	title,
	onChangeTitle,
	onSave,
	onCancel,
	headerNode,
	preHeaderNode,
}: ChatPreviewProps) {
	const { data: generalSession } = useGeneralChatSession(mode === "general" ? sessionId : null);
	const sendGeneralMsg = useSendGeneralChatMessage(mode === "general" ? sessionId : null);

	const [userChatMessages, setUserChatMessages] = useState<Message[]>(() => {
		// If Knowledge document has saved chat history in DB metadata, load it
		const meta = knowledge?.metadata as Record<string, unknown> | undefined;
		const savedHistory = (meta?.history || meta?.chat_history) as
			| Array<{ role: "user" | "assistant"; content: string }>
			| undefined;
		if (Array.isArray(savedHistory) && savedHistory.length > 0) {
			return savedHistory.map((m) => ({
				role: m.role,
				content: m.content,
			}));
		}
		return [];
	});

	useEffect(() => {
		if (mode === "knowledge") {
			const meta = knowledge?.metadata as Record<string, unknown> | undefined;
			const savedHistory = (meta?.history || meta?.chat_history) as
				| Array<{ role: "user" | "assistant"; content: string }>
				| undefined;
			const timer = setTimeout(() => {
				if (Array.isArray(savedHistory) && savedHistory.length > 0) {
					setUserChatMessages(
						savedHistory.map((m) => ({
							role: m.role,
							content: m.content,
						})),
					);
				} else {
					setUserChatMessages([]);
				}
			}, 0);
			return () => clearTimeout(timer);
		}
	}, [mode, knowledgeId, knowledge?.id, knowledge?.metadata]);

	const sessionMessages = generalSession?.messages;
	const dbMessages: Message[] = useMemo(() => {
		if (mode === "general" && sessionMessages) {
			return sessionMessages.map((m) => ({
				role: m.role as "user" | "assistant",
				content: m.content,
				action: m.action || undefined,
				target_knowledge_id: m.target_knowledge_id || undefined,
				total_found: m.total_found ?? undefined,
			}));
		}
		return [];
	}, [mode, sessionMessages]);

	const [input, setInput] = useState("");
	const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
	const [isLoading, setIsLoading] = useState(false);
	const [optimisticUserMsg, setOptimisticUserMsg] = useState<Message | null>(null);
	const [activeTab, setActiveTab] = useState<string | null>(null);

	const isProcessing = isLoading;

	const currentTab =
		activeTab || (files && files.length > 0 ? (files[0].file_name as string) : null);

	const fileInputRef = useRef<HTMLInputElement>(null);
	const queryClient = useQueryClient();
	const [isDragging, setIsDragging] = useState(false);
	const dragCounter = useRef(0);
	const initialPromptTriggeredRef = useRef<string | null>(null);

	useEffect(() => {
		if (
			mode === "general" &&
			initialPrompt &&
			initialPromptTriggeredRef.current !== initialPrompt
		) {
			initialPromptTriggeredRef.current = initialPrompt;

			// If sessionId exists, use persistent DB endpoint
			if (sessionId) {
				const sendInitialDB = async () => {
					setIsLoading(true);
					setOptimisticUserMsg({ role: "user", content: initialPrompt });
					try {
						await sendGeneralMsg.mutateAsync({ prompt: initialPrompt });
					} catch {
						toast.error("Failed to send message to AI.");
					} finally {
						sendGeneralMsg.reset();
						setIsLoading(false);
						setOptimisticUserMsg(null);
						// Clean URL query parameter so refresh won't re-trigger
						if (typeof window !== "undefined") {
							window.history.replaceState(
								null,
								"",
								`/dashboard/ingest/chat?session_id=${sessionId}`,
							);
						}
					}
				};
				void sendInitialDB();
			} else {
				const sendInitialStateless = async () => {
					const userMsg: Message = { role: "user", content: initialPrompt };
					setUserChatMessages([userMsg]);
					setIsLoading(true);
					try {
						const response = await api.post("/knowledge/query-general", {
							prompt: initialPrompt,
							history: [],
						});
						const data = response.data;
						setUserChatMessages([
							userMsg,
							{
								role: "assistant",
								content: data.answer,
								action: data.action,
								target_knowledge_id: data.target_knowledge_id,
								total_found: data.total_found,
							},
						]);
					} catch {
						toast.error("Failed to send message to AI.");
					} finally {
						setIsLoading(false);
					}
				};
				void sendInitialStateless();
			}
		}
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [mode, initialPrompt, sessionId]);

	const getFileIconAndColor = (filename?: string | null) => {
		if (!filename)
			return { Icon: RiFileTextLine, bgColor: "bg-blue-50", textColor: "text-blue-600" };
		const ext = filename.split(".").pop()?.toLowerCase() || "";
		switch (ext) {
			case "pdf":
				return { Icon: RiFilePdf2Line, bgColor: "bg-red-50", textColor: "text-red-600" };
			case "doc":
			case "docx":
				return { Icon: RiFileWord2Line, bgColor: "bg-blue-50", textColor: "text-blue-600" };
			case "xls":
			case "xlsx":
			case "csv":
				return { Icon: RiFileExcel2Line, bgColor: "bg-emerald-50", textColor: "text-emerald-600" };
			case "png":
			case "jpg":
			case "jpeg":
			case "gif":
				return { Icon: RiImage2Line, bgColor: "bg-purple-50", textColor: "text-purple-600" };
			case "txt":
			default:
				return { Icon: RiFileTextLine, bgColor: "bg-blue-50", textColor: "text-blue-600" };
		}
	};

	const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (isInputDisabled) return;

		if (e.dataTransfer.types && Array.from(e.dataTransfer.types).includes("Files")) {
			dragCounter.current += 1;
			setIsDragging(true);
		}
	};

	const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (isInputDisabled) return;

		dragCounter.current -= 1;
		if (dragCounter.current <= 0) {
			dragCounter.current = 0;
			setIsDragging(false);
		}
	};

	const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (isInputDisabled) return;

		if (e.dataTransfer) {
			e.dataTransfer.dropEffect = "copy";
		}
	};

	const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
		e.preventDefault();
		e.stopPropagation();
		if (isInputDisabled) return;

		dragCounter.current = 0;
		setIsDragging(false);

		if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
			setAttachedFiles((prev) => [...prev, ...Array.from(e.dataTransfer.files)]);
		}
	};

	const handlePaste = (e: React.ClipboardEvent) => {
		if (isInputDisabled) return;
		if (e.clipboardData.files && e.clipboardData.files.length > 0) {
			e.preventDefault();
			setAttachedFiles((prev) => [...prev, ...Array.from(e.clipboardData.files)]);
		}
	};

	const initialSummaryMessage: Message | null =
		aiSummary && knowledgeStatus !== "PROCESSING"
			? { role: "assistant", content: aiSummary }
			: null;

	const messages: Message[] = [];
	if (
		initialSummaryMessage &&
		userChatMessages.length === 0 &&
		(!sessionId || mode !== "general")
	) {
		messages.push(initialSummaryMessage);
	}
	if (mode === "general" && sessionId) {
		messages.push(...dbMessages);
	} else {
		messages.push(...userChatMessages);
	}
	if (optimisticUserMsg) {
		messages.push(optimisticUserMsg);
	}
	const firstAssistantIndex = messages.findIndex((m) => m.role === "assistant");
	let lastAssistantIndex = -1;
	for (let i = messages.length - 1; i >= 0; i--) {
		if (messages[i].role === "assistant") {
			lastAssistantIndex = i;
			break;
		}
	}

	const renderCategoriesBlock = (standalone = false) => {
		if (mode === "general") return null;
		const shouldShow =
			knowledgeStatus !== "PROCESSING" &&
			(categories.length > 0 ||
				(isEditMode && knowledgeStatus === "APPROVED") ||
				knowledgeStatus === "PENDING");

		const content = (
			<div className={`flex flex-col gap-4 w-full mt-4 ${!shouldShow ? "hidden" : ""}`}>
				<CategorySettings
					categories={categories}
					onChangeCategories={(c) => onChangeCategories?.(c)}
					isEditMode={isEditMode || knowledgeStatus === "PENDING"}
					showSaveActions={isEditMode}
					onSave={onSave}
					onCancel={onCancel}
				/>
				{visibilitySettings && onChangeVisibilitySettings && (
					<VisibilitySettingsUI
						settings={visibilitySettings}
						onChange={onChangeVisibilitySettings}
						isEditMode={isEditMode || knowledgeStatus === "PENDING"}
						showSaveActions={isEditMode}
						onSave={onSave}
						onCancel={onCancel}
					/>
				)}

				{knowledge && (
					<ClassificationSidebar
						knowledge={knowledge}
						pendingCategories={categories}
						pendingVisibilitySettings={visibilitySettings}
						pendingTitle={title}
					/>
				)}
				{files && files.length > 0 && (
					<div className="mt-8 border rounded-lg overflow-hidden bg-zinc-50 border-zinc-200">
						<div className="flex border-b border-zinc-200 bg-white overflow-x-auto scrollbar-hide">
							{files.map((f, i) => (
								<button
									key={i}
									onClick={() => setActiveTab(f.file_name as string)}
									className={`px-4 py-3 text-sm font-medium whitespace-nowrap transition-colors ${
										currentTab === f.file_name
											? "border-b-2 border-blue-600 text-blue-700 bg-blue-50/50"
											: "text-zinc-500 hover:text-zinc-700 hover:bg-zinc-50"
									}`}
								>
									<RiFileTextLine className="inline-block w-4 h-4 mr-2 align-text-bottom" />
									{f.file_name as string}
								</button>
							))}
						</div>
						<div className="p-5 max-h-100 overflow-y-auto prose prose-sm max-w-none text-zinc-700">
							{files.find((f) => f.file_name === currentTab) ? (
								<div>
									<h4 className="text-zinc-900 font-semibold mb-3">Individual Summary</h4>
									<ReactMarkdown remarkPlugins={[remarkGfm]}>
										{(files.find((f) => f.file_name === currentTab)?.summary as string) ||
											"No summary available."}
									</ReactMarkdown>
								</div>
							) : (
								<p className="text-zinc-500 italic">Select a document to view its details.</p>
							)}
						</div>
					</div>
				)}
			</div>
		);

		return standalone ? (
			<MessageScrollerItem key="categories-block">{content}</MessageScrollerItem>
		) : (
			content
		);
	};

	const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
		const files = e.target.files;
		if (files && files.length > 0) {
			setAttachedFiles((prev) => [...prev, ...Array.from(files)]);
		}
	};

	const removeAttachedFile = (indexToRemove: number) => {
		setAttachedFiles((prev) => prev.filter((_, idx) => idx !== indexToRemove));
	};

	const handleSend = async () => {
		if ((!input.trim() && attachedFiles.length === 0) || isProcessing) return;

		const filesToSend = [...attachedFiles];
		const fileNames = filesToSend.map((f) => f.name);
		const userMsg: Message = {
			role: "user",
			content:
				input.trim() || (fileNames.length > 0 ? `Attached files: ${fileNames.join(", ")}` : ""),
			attachmentNames: fileNames.length > 0 ? fileNames : undefined,
			attachmentName: fileNames.length > 0 ? fileNames[0] : undefined,
		};

		if (!sessionId) {
			setUserChatMessages((prev) => [...prev, userMsg]);
		} else if (mode === "general") {
			setOptimisticUserMsg(userMsg);
		}
		setInput("");
		setAttachedFiles([]);
		setIsLoading(true);

		try {
			if (mode === "general") {
				if (sessionId) {
					await sendGeneralMsg.mutateAsync({
						prompt: userMsg.content,
						attachments: userMsg.attachmentNames ? { names: userMsg.attachmentNames } : undefined,
					});
				} else {
					const response = await api.post("/knowledge/query-general", {
						prompt: userMsg.content,
						history: messages.map((m) => ({ role: m.role, content: m.content })),
					});
					const data = response.data;
					setUserChatMessages((prev) => [
						...prev,
						{
							role: "assistant",
							content: data.answer,
							action: data.action,
							target_knowledge_id: data.target_knowledge_id,
							total_found: data.total_found,
						},
					]);
					if (data.action === "edit_applied" || data.action === "delete_applied") {
						queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
						queryClient.invalidateQueries({ queryKey: ["projects"] });
						queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
						if (data.target_knowledge_id) {
							queryClient.invalidateQueries({
								queryKey: knowledgeKeys.detail(data.target_knowledge_id),
							});
						}
					}
				}
			} else if (
				(knowledgeStatus === "PENDING" || (knowledgeStatus === "APPROVED" && isEditMode)) &&
				knowledgeId
			) {
				const endpoint = `/knowledge/${knowledgeId}/refine`;

				let response;
				if (filesToSend.length > 0) {
					const formData = new FormData();
					formData.append("prompt", userMsg.content);
					formData.append("history", JSON.stringify([...messages, userMsg]));
					formData.append("file", filesToSend[0]);

					response = await api.post(endpoint, formData);
				} else {
					response = await api.post(endpoint, {
						prompt: userMsg.content,
						history: [...messages, userMsg],
					});
				}
				const chatResponse = response.data.summary
					? `Here is the updated summary:\n\n${response.data.summary}`
					: response.data.feedback
						? response.data.feedback
						: "I've updated the document summary based on your instructions.";
				setUserChatMessages((prev) => [...prev, { role: "assistant", content: chatResponse }]);

				if (knowledgeId) {
					queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(knowledgeId) });
					queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
					queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
					queryClient.invalidateQueries({ queryKey: ["projects"] });
				}
			} else {
				const response = await api.post("/knowledge/chat", {
					query: userMsg.content,
					knowledge_id: knowledgeId,
					history: messages,
				});

				setUserChatMessages((prev) => [
					...prev,
					{ role: "assistant", content: response.data.answer },
				]);
			}
		} catch (err: unknown) {
			const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
			toast.error(detail || "Failed to send message to AI.");
		} finally {
			sendGeneralMsg.reset();
			setIsLoading(false);
			setOptimisticUserMsg(null);
		}
	};

	const isInputDisabled =
		mode === "general"
			? isProcessing
			: knowledgeStatus === "PROCESSING" ||
				isProcessing ||
				isDetailLoading ||
				(knowledgeStatus === "APPROVED" && !isEditMode);

	return (
		<div className="flex flex-col flex-1 bg-white overflow-hidden min-h-0 h-full">
			<MessageScrollerProvider>
				<MessageScroller className="flex-1 min-h-0">
					<MessageScrollerViewport className="px-6 sm:px-8">
						<MessageScrollerContent className="py-8 gap-6 w-full max-w-5xl mx-auto min-w-0">
							{isDetailLoading && (
								<MessageScrollerItem>
									<div className="flex items-start gap-3 w-full min-w-0 max-w-full">
										<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
											<RiRobot2Line className="size-4 animate-pulse text-blue-500" />
										</div>
										<div className="bg-blue-50/70 text-zinc-950 p-3 rounded-md text-sm w-full min-w-0 max-w-full flex items-center gap-2 border border-blue-100/50">
											<RiLoader4Line className="size-4 animate-spin text-blue-600" />
											<span className="text-zinc-700 font-medium">
												Fetching document details and session...
											</span>
										</div>
									</div>
								</MessageScrollerItem>
							)}

							{!isDetailLoading && messages.length === 0 && knowledgeStatus !== "PROCESSING" && (
								<MessageScrollerItem>
									{mode === "general" ? (
										<div className="flex flex-col items-center justify-center text-center py-16 px-4 max-w-lg mx-auto space-y-3">
											<div className="size-12 rounded-xl bg-blue-50 text-blue-500 flex items-center justify-center">
												<RiRobot2Line className="size-6" />
											</div>
											<h2 className="text-base font-semibold text-zinc-950">
												Knowledge Base Assistant
											</h2>
											<p className="text-xs text-zinc-500 leading-relaxed">
												Ask questions about clinic products and treatments, instruct updates, or
												clean expired records. The assistant maintains context across your
												conversation.
											</p>
										</div>
									) : (
										<div className="flex items-start gap-3 w-full min-w-0 max-w-full">
											<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
												<RiRobot2Line className="size-4" />
											</div>
											<div className="bg-blue-50/80 text-zinc-950 p-4 rounded-md text-sm w-full min-w-0 max-w-full border border-blue-100 flex flex-col gap-3">
												{headerNode}
												<p className="text-zinc-500 italic">No summary available.</p>
											</div>
										</div>
									)}
								</MessageScrollerItem>
							)}

							{!isDetailLoading && knowledgeStatus === "PROCESSING" && messages.length === 0 && (
								<MessageScrollerItem>
									<div className="flex flex-col w-full min-w-0 max-w-full items-start">
										{/* Attached Document Badge OUTSIDE & ABOVE bubble */}
										{fileName &&
											(() => {
												const { Icon, bgColor, textColor } = getFileIconAndColor(fileName);
												return (
													<div className="flex flex-col gap-2 mb-4 self-end">
														<Attachment className="bg-white border border-zinc-200 shadow-none p-1.5 w-fit min-w-40 max-w-sm rounded-lg">
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
													</div>
												);
											})()}

										<div className="flex items-start gap-3 w-full min-w-0 max-w-full">
											<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
												<RiRobot2Line className="size-4" />
											</div>
											<div className="bg-blue-50/80 text-zinc-950 p-4 rounded-md text-sm w-full min-w-0 max-w-full border border-blue-100 flex flex-col gap-3 overflow-hidden">
												{headerNode}
												<div className="flex items-center gap-2">
													<span className="relative flex h-3 w-3">
														<span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
														<span className="relative inline-flex rounded-full h-3 w-3 bg-blue-500"></span>
													</span>
													<span className="font-semibold text-blue-700">Processing Document</span>
												</div>
												<p className="text-zinc-600 text-xs leading-relaxed">
													Document processing progress:
												</p>
												<div className="flex flex-col gap-2.5 bg-white/90 rounded border border-blue-100 p-3.5 text-xs text-zinc-700">
													<div className="flex items-center gap-2.5 text-emerald-600 font-medium">
														<RiCheckLine className="size-4 shrink-0" />
														<span>1. Extracting Content</span>
													</div>
													<div className="flex items-center gap-2.5 text-emerald-600 font-medium">
														<RiCheckLine className="size-4 shrink-0" />
														<span>2. Structuring Information</span>
													</div>
													<div className="flex items-center gap-2.5 text-blue-600 font-semibold animate-pulse">
														<RiLoader4Line className="size-4 animate-spin shrink-0" />
														<span>3. Building Search Index...</span>
													</div>
													<div className="flex items-center gap-2.5 text-zinc-400">
														<span className="size-4 flex items-center justify-center text-[10px]">
															○
														</span>
														<span>4. Generating Summary</span>
													</div>
												</div>
												<span className="text-[11px] text-zinc-500 mt-0.5">
													You can navigate away anytime. Processing continues in the background.
												</span>
											</div>
										</div>
									</div>
								</MessageScrollerItem>
							)}

							{messages.length > 0 && (
								<MessageScrollerItem key="msg-0" scrollAnchor={messages.length === 1 && !isLoading}>
									<div
										className={`flex flex-col w-full min-w-0 max-w-full ${messages[0].role === "user" ? "items-end" : "items-start"}`}
									>
										{title !== undefined && onChangeTitle && (
											<div className="flex justify-center w-full mb-4">
												<div className="w-fit max-w-lg">
													<TitleSettings
														title={title}
														onChangeTitle={onChangeTitle}
														onSave={onSave}
													/>
												</div>
											</div>
										)}
										{fileName &&
											(() => {
												const { Icon, bgColor, textColor } = getFileIconAndColor(fileName);
												return (
													<div className="flex flex-col gap-2 mb-4 self-end">
														<Attachment className="bg-white border border-zinc-200 shadow-none p-1.5 w-fit min-w-40 max-w-sm rounded-lg">
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
													</div>
												);
											})()}
										{(() => {
											const names =
												messages[0].attachmentNames ||
												(messages[0].attachmentName ? [messages[0].attachmentName] : []);
											if (names.length === 0) return null;
											return (
												<div className="flex flex-wrap gap-2 mb-2">
													{names.map((name, i) => {
														const { Icon, bgColor, textColor } = getFileIconAndColor(name);
														return (
															<Attachment
																key={i}
																className="bg-white border border-zinc-200 shadow-none p-1.5 min-w-35 max-w-50 shrink-0 rounded-lg"
															>
																<AttachmentMedia
																	className={`${bgColor} ${textColor} rounded-lg p-2 shrink-0`}
																>
																	<Icon className="w-5 h-5" />
																</AttachmentMedia>
																<AttachmentContent className="overflow-hidden min-w-0 pr-2">
																	<AttachmentTitle className="text-[13px] font-medium text-zinc-950 truncate block">
																		{name}
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
										})()}
										{preHeaderNode}
										<div
											className={`flex items-start gap-3 w-full min-w-0 max-w-full ${messages[0].role === "user" ? "flex-row-reverse" : ""}`}
										>
											<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
												{messages[0].role === "user" ? (
													<RiUser3Line className="size-4" />
												) : (
													<RiRobot2Line className="size-4" />
												)}
											</div>
											<div
												className={`${messages[0].role === "user" ? "bg-blue-500 text-white" : "bg-transparent border border-zinc-200 text-zinc-950"} p-3.5 rounded-md text-sm w-full min-w-0 overflow-hidden prose prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-zinc-800 prose-pre:text-zinc-100 prose-p:my-1.5 prose-ul:my-1.5 prose-ul:pl-4 prose-ol:my-1.5 prose-ol:pl-4 prose-li:my-0.5 prose-headings:my-2.5 prose-table:w-full prose-table:border prose-table:border-blue-200/60 prose-table:rounded-md prose-table:overflow-hidden prose-table:my-3 prose-table:bg-white prose-th:bg-blue-100/50 prose-th:px-3 prose-th:py-2.5 prose-th:text-left prose-th:font-semibold prose-th:text-blue-900 prose-th:border-b prose-th:border-blue-200/60 prose-td:px-3 prose-td:py-2.5 prose-td:border-b prose-td:border-blue-100/60 last:prose-td:border-0 whitespace-pre-wrap`}
											>
												{messages[0].role === "assistant" ? (
													<>
														{0 === firstAssistantIndex && headerNode}
														<ReactMarkdown remarkPlugins={[remarkGfm]}>
															{messages[0].content}
														</ReactMarkdown>
													</>
												) : (
													messages[0].content
												)}
												{/* Inject Categories below initial summary if it's the latest assistant message */}
												{0 === lastAssistantIndex && renderCategoriesBlock()}
											</div>
										</div>
									</div>
								</MessageScrollerItem>
							)}

							{/* Categories Section (Fallback: if no messages exist at all but we need to show categories) */}
							{messages.length === 0 && renderCategoriesBlock(true)}

							{/* Render remaining messages */}
							{messages.slice(1).map((msg, sliceIndex) => {
								const actualIndex = sliceIndex + 1;
								return (
									<MessageScrollerItem
										key={`msg-${actualIndex}`}
										scrollAnchor={actualIndex === messages.length - 1 && !isLoading}
									>
										<div
											className={`flex flex-col w-full min-w-0 max-w-full ${msg.role === "user" ? "items-end" : "items-start"}`}
										>
											{(() => {
												const names =
													msg.attachmentNames || (msg.attachmentName ? [msg.attachmentName] : []);
												if (names.length === 0) return null;
												return (
													<div className="flex flex-wrap gap-2 mb-2">
														{names.map((name, i) => {
															const { Icon, bgColor, textColor } = getFileIconAndColor(name);
															return (
																<Attachment
																	key={i}
																	className="bg-white border border-zinc-200 shadow-none p-1.5 min-w-35 max-w-50 shrink-0 rounded-lg"
																>
																	<AttachmentMedia
																		className={`${bgColor} ${textColor} rounded-lg p-2 shrink-0`}
																	>
																		<Icon className="w-5 h-5" />
																	</AttachmentMedia>
																	<AttachmentContent className="overflow-hidden min-w-0 pr-2">
																		<AttachmentTitle className="text-[13px] font-medium text-zinc-950 truncate block">
																			{name}
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
											})()}
											<div
												className={`flex items-start gap-3 w-full min-w-0 max-w-full ${msg.role === "user" ? "flex-row-reverse" : ""}`}
											>
												<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
													{msg.role === "user" ? (
														<RiUser3Line className="size-4" />
													) : (
														<RiRobot2Line className="size-4" />
													)}
												</div>
												<div
													className={`${msg.role === "user" ? "bg-blue-500 text-white" : "bg-transparent border border-zinc-200 text-zinc-950"} p-3.5 rounded-md text-sm w-full min-w-0 overflow-hidden prose prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-zinc-800 prose-pre:text-zinc-100 prose-p:my-1.5 prose-ul:my-1.5 prose-ul:pl-4 prose-ol:my-1.5 prose-ol:pl-4 prose-li:my-0.5 prose-headings:my-2.5 prose-table:w-full prose-table:border prose-table:border-blue-200/60 prose-table:rounded-md prose-table:overflow-hidden prose-table:my-3 prose-table:bg-white prose-th:bg-blue-100/50 prose-th:px-3 prose-th:py-2.5 prose-th:text-left prose-th:font-semibold prose-th:text-blue-900 prose-th:border-b prose-th:border-blue-200/60 prose-td:px-3 prose-td:py-2.5 prose-td:border-b prose-td:border-blue-100/60 last:prose-td:border-0 whitespace-pre-wrap`}
												>
													{msg.role === "assistant" ? (
														<>
															{actualIndex === firstAssistantIndex && headerNode}
															<ReactMarkdown remarkPlugins={[remarkGfm]}>
																{msg.content}
															</ReactMarkdown>
														</>
													) : (
														msg.content
													)}
													{/* Inject Categories below this AI message if it's the latest assistant message */}
													{actualIndex === lastAssistantIndex && renderCategoriesBlock()}
												</div>
											</div>
										</div>
									</MessageScrollerItem>
								);
							})}

							{isLoading && (
								<MessageScrollerItem scrollAnchor>
									<div className="flex items-start gap-3 w-full">
										<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
											<RiRobot2Line className="size-4 animate-bounce text-blue-500" />
										</div>
										<div className="text-sm text-zinc-500 pt-1.5 italic animate-pulse">
											Thinking...
										</div>
									</div>
								</MessageScrollerItem>
							)}
						</MessageScrollerContent>
					</MessageScrollerViewport>
					<MessageScrollerSmartButton />
				</MessageScroller>
			</MessageScrollerProvider>

			{/* Chatbox Input */}
			<div className="px-6 sm:px-8 py-4 shrink-0 w-full">
				<div
					className={`max-w-5xl mx-auto relative rounded-lg p-4 flex flex-col gap-3 transition-colors border shadow-none ${
						isDragging ? "border-blue-500 bg-blue-50/50" : "border-zinc-200 bg-white"
					}`}
					onDragEnter={handleDragEnter}
					onDragLeave={handleDragLeave}
					onDragOver={handleDragOver}
					onDrop={handleDrop}
					onPaste={handlePaste}
				>
					{/* Drag & Drop Visual Overlay (Flat) */}
					{isDragging && (
						<div className="absolute inset-0 z-30 flex flex-col items-center justify-center rounded-md border-2 border-dashed border-blue-500 bg-blue-50/95 pointer-events-none gap-2 p-4 text-center">
							<div className="flex items-center justify-center size-10 rounded-full bg-blue-100 text-blue-600">
								<RiUploadCloud2Line className="size-5" />
							</div>
							<div className="flex flex-col items-center gap-0.5">
								<span className="text-xs font-semibold text-zinc-900">
									Drop file here to attach
								</span>
								<span className="text-[11px] text-zinc-500">
									Release to add file to your message
								</span>
							</div>
							<div className="flex items-center gap-1.5 text-[10px]">
								<span className="px-1.5 py-0.5 rounded bg-white border border-blue-200 font-medium text-zinc-700">
									PDF
								</span>
								<span className="px-1.5 py-0.5 rounded bg-white border border-blue-200 font-medium text-zinc-700">
									DOCX
								</span>
								<span className="px-1.5 py-0.5 rounded bg-white border border-blue-200 font-medium text-zinc-700">
									XLSX
								</span>
								<span className="px-1.5 py-0.5 rounded bg-white border border-blue-200 font-medium text-zinc-700">
									Images
								</span>
							</div>
						</div>
					)}

					{/* File Attachment Cards Preview in Input */}
					{attachedFiles.length > 0 && (
						<div className="flex gap-2 overflow-x-auto pb-1 custom-scrollbar">
							{attachedFiles.map((file, idx) => {
								const { Icon, bgColor, textColor } = getFileIconAndColor(file.name);
								return (
									<Attachment
										key={idx}
										className="bg-white border border-zinc-200 shadow-none p-1.5 min-w-35 max-w-50 shrink-0 rounded-lg"
									>
										<AttachmentMedia className={`${bgColor} ${textColor} rounded-lg p-2 shrink-0`}>
											<Icon className="w-5 h-5" />
										</AttachmentMedia>
										<AttachmentContent className="overflow-hidden min-w-0 pr-1">
											<AttachmentTitle className="text-[13px] font-medium text-zinc-950 truncate block">
												{file.name}
											</AttachmentTitle>
											<AttachmentDescription className="text-[11px] text-zinc-500">
												{(file.size / 1024).toFixed(1)} KB
											</AttachmentDescription>
										</AttachmentContent>
										<AttachmentActions>
											<AttachmentAction
												variant="ghost"
												className="hover:bg-zinc-100 text-zinc-500 hover:text-zinc-950 ml-1"
												onClick={() => removeAttachedFile(idx)}
											>
												<RiCloseLine className="w-4 h-4" />
											</AttachmentAction>
										</AttachmentActions>
									</Attachment>
								);
							})}
						</div>
					)}

					<Input
						value={input}
						onChange={(e) => setInput(e.target.value)}
						onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
						placeholder={
							knowledgeStatus === "PROCESSING"
								? "Waiting for ingestion to complete..."
								: knowledgeStatus === "APPROVED" && !isEditMode && mode !== "general"
									? "Click 'Edit Knowledge' to refine summary..."
									: mode === "general"
										? "Ask about the knowledge..."
										: "Ask questions or request adjustments..."
						}
						disabled={mode === "general" ? false : isInputDisabled}
						className="w-full bg-transparent border-none shadow-none focus-visible:ring-0 px-0 outline-none text-sm text-gray-700 placeholder:text-gray-500"
					/>

					<input
						type="file"
						ref={fileInputRef}
						onChange={handleFileSelect}
						multiple
						className="hidden"
					/>

					<div
						className={`flex items-center ${mode === "general" ? "justify-end" : "justify-between"} pt-1`}
					>
						{mode !== "general" && (
							<Button
								type="button"
								variant="ghost"
								size="icon-sm"
								onClick={() => fileInputRef.current?.click()}
								disabled={isInputDisabled}
								className="text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100"
								title="Attach files"
							>
								<RiAttachment2 className="size-4" />
							</Button>
						)}
						<Button
							onClick={handleSend}
							disabled={isProcessing || (!input.trim() && attachedFiles.length === 0)}
							size="icon"
							className="bg-blue-500 text-white hover:bg-blue-600 shrink-0"
						>
							<RiCornerDownLeftLine className="w-4 h-4" />
						</Button>
					</div>
				</div>
			</div>
		</div>
	);
}
