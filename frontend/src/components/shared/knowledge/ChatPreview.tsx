import { knowledgeKeys } from "@/app/dashboard/knowledge/api/keys";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
	MessageScroller,
	MessageScrollerButton,
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
} from "@remixicon/react";
import { useQueryClient } from "@tanstack/react-query";
import { useState, useEffect, useRef } from "react";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { toast } from "sonner";
import { VisibilitySettings as VisibilitySettingsUI } from "./VisibilitySettings";
import {
	VisibilitySettings as IVisibilitySettings,
	KnowledgeResponse,
} from "@/app/dashboard/knowledge/api/types";
import { CategorySettings } from "./CategorySettings";
import { ClassificationSidebar } from "./ClassificationSidebar";
import { TitleSettings } from "./TitleSettings";

interface ChatPreviewProps {
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
}

export function ChatPreview({
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
	const STORAGE_KEY = `chat_preview_${knowledgeId || "default"}`;

	const [userChatMessages, setUserChatMessages] = useState<Message[]>(() => {
		if (typeof window !== "undefined") {
			const saved = localStorage.getItem(STORAGE_KEY);
			if (saved) {
				try {
					return JSON.parse(saved);
				} catch (e) {
					console.error("Failed to parse chat messages", e);
				}
			}
		}
		return [];
	});

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

	const [input, setInput] = useState("");
	const [attachedFile, setAttachedFile] = useState<File | null>(null);
	const [isLoading, setIsLoading] = useState(false);
	const [activeTab, setActiveTab] = useState<string | null>(null);

	const currentTab =
		activeTab || (files && files.length > 0 ? (files[0].file_name as string) : null);

	const fileInputRef = useRef<HTMLInputElement>(null);
	const queryClient = useQueryClient();

	useEffect(() => {
		if (typeof window !== "undefined") {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(userChatMessages));
		}
	}, [userChatMessages, STORAGE_KEY]);

	const initialSummaryMessage: Message | null =
		aiSummary && knowledgeStatus !== "PROCESSING"
			? { role: "assistant", content: aiSummary }
			: null;

	const messages: Message[] = [];
	if (initialSummaryMessage) messages.push(initialSummaryMessage);
	messages.push(...userChatMessages);

	// Find the index of the latest assistant message so we know where to attach the Categories
	let lastAssistantIndex = -1;
	for (let i = messages.length - 1; i >= 0; i--) {
		if (messages[i].role === "assistant") {
			lastAssistantIndex = i;
			break;
		}
	}

	const renderCategoriesBlock = (standalone = false) => {
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

	// handleAddCategory and availableCategories are now handled in CategorySettings,
	// but we keep them here if anything else uses them (though they are not used).
	// We can safely remove them since CategorySettings manages its own local state.

	const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
		if (e.target.files && e.target.files[0]) {
			setAttachedFile(e.target.files[0]);
		}
	};

	const handleSend = async () => {
		if ((!input.trim() && !attachedFile) || isLoading) return;

		const userMsg: Message = {
			role: "user",
			content: input.trim() || (attachedFile ? `Attached file: ${attachedFile.name}` : ""),
			attachmentName: attachedFile ? attachedFile.name : undefined,
		};

		setUserChatMessages((prev) => [...prev, userMsg]);
		setInput("");
		setAttachedFile(null);
		setIsLoading(true);

		try {
			if (
				(knowledgeStatus === "PENDING" || (knowledgeStatus === "APPROVED" && isEditMode)) &&
				knowledgeId
			) {
				const endpoint = `/knowledge/${knowledgeId}/refine`;

				const response = await api.post(endpoint, {
					prompt: userMsg.content,
					history: [...messages, userMsg],
				});
				const chatResponse = response.data.summary
					? `Here is the updated summary:\n\n${response.data.summary}`
					: "I've updated the document summary based on your instructions.";
				setUserChatMessages((prev) => [...prev, { role: "assistant", content: chatResponse }]);

				if (knowledgeId) {
					queryClient.invalidateQueries({ queryKey: knowledgeKeys.detail(knowledgeId) });
					queryClient.invalidateQueries({ queryKey: ["knowledge-batch"] });
					queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
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
		} catch {
			toast.error("Failed to send message to AI.");
		} finally {
			setIsLoading(false);
		}
	};

	const isInputDisabled =
		knowledgeStatus === "PROCESSING" ||
		isLoading ||
		isDetailLoading ||
		(knowledgeStatus === "APPROVED" && !isEditMode);

	return (
		<div className="flex flex-col flex-1 bg-white overflow-hidden min-h-0 h-full">
			<MessageScrollerProvider>
				<MessageScroller className="flex-1 min-h-0">
					<MessageScrollerViewport className="px-8">
						<MessageScrollerContent className="py-10 gap-6 w-full max-w-4xl mx-auto">
							{isDetailLoading && (
								<MessageScrollerItem>
									<div className="flex items-start gap-3 w-full">
										<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
											<RiRobot2Line className="size-4 animate-pulse text-blue-500" />
										</div>
										<div className="bg-blue-50/70 text-zinc-950 p-3 rounded-md text-sm w-full flex items-center gap-2 border border-blue-100/50">
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
									<div className="flex items-start gap-3 w-full">
										<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
											<RiRobot2Line className="size-4" />
										</div>
										<div className="bg-blue-50/80 text-zinc-950 p-4 rounded-md text-sm w-full border border-blue-100 flex flex-col gap-3">
											{headerNode}
											<p className="text-zinc-500 italic">No summary available.</p>
										</div>
									</div>
								</MessageScrollerItem>
							)}

							{!isDetailLoading && knowledgeStatus === "PROCESSING" && messages.length === 0 && (
								<MessageScrollerItem>
									<div className="flex flex-col w-full items-start">
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

										<div className="flex items-start gap-3 w-full">
											<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
												<RiRobot2Line className="size-4" />
											</div>
											<div className="bg-blue-50/80 text-zinc-950 p-4 rounded-md text-sm w-full border border-blue-100 flex flex-col gap-3">
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
										className={`flex flex-col w-full ${messages[0].role === "user" ? "items-end" : "items-start"}`}
									>
										{title !== undefined && onChangeTitle && messages[0].role === "assistant" && (
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
											messages[0].role === "assistant" &&
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
										{messages[0].attachmentName && (
											<div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-100 border border-zinc-200 rounded-md text-xs font-medium text-zinc-800 w-fit mb-2 shadow-none">
												<RiFileTextLine className="size-3.5 text-blue-600 shrink-0" />
												<span className="truncate max-w-xs">{messages[0].attachmentName}</span>
											</div>
										)}
										{preHeaderNode}
										<div
											className={`flex items-start gap-3 w-full ${messages[0].role === "user" ? "flex-row-reverse" : ""}`}
										>
											<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
												{messages[0].role === "user" ? (
													<RiUser3Line className="size-4" />
												) : (
													<RiRobot2Line className="size-4" />
												)}
											</div>
											<div
												className={`${messages[0].role === "user" ? "bg-blue-500 text-white" : "bg-transparent border border-zinc-200 text-zinc-950"} p-3.5 rounded-md text-sm w-full prose prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-zinc-800 prose-pre:text-zinc-100 prose-p:my-1.5 prose-ul:my-1.5 prose-ul:pl-4 prose-ol:my-1.5 prose-ol:pl-4 prose-li:my-0.5 prose-headings:my-2.5 prose-table:w-full prose-table:border prose-table:border-blue-200/60 prose-table:rounded-md prose-table:overflow-hidden prose-table:my-3 prose-table:bg-white prose-th:bg-blue-100/50 prose-th:px-3 prose-th:py-2.5 prose-th:text-left prose-th:font-semibold prose-th:text-blue-900 prose-th:border-b prose-th:border-blue-200/60 prose-td:px-3 prose-td:py-2.5 prose-td:border-b prose-td:border-blue-100/60 last:prose-td:border-0 whitespace-pre-wrap`}
											>
												{messages[0].role === "assistant" ? (
													<>
														{headerNode}
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
											className={`flex flex-col w-full ${msg.role === "user" ? "items-end" : "items-start"}`}
										>
											{msg.attachmentName && (
												<div className="flex items-center gap-2 px-3 py-1.5 bg-zinc-100 border border-zinc-200 rounded-md text-xs font-medium text-zinc-800 w-fit mb-2 shadow-none">
													<RiFileTextLine className="size-3.5 text-blue-600 shrink-0" />
													<span className="truncate max-w-xs">{msg.attachmentName}</span>
												</div>
											)}
											<div
												className={`flex items-start gap-3 w-full ${msg.role === "user" ? "flex-row-reverse" : ""}`}
											>
												<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
													{msg.role === "user" ? (
														<RiUser3Line className="size-4" />
													) : (
														<RiRobot2Line className="size-4" />
													)}
												</div>
												<div
													className={`${msg.role === "user" ? "bg-blue-500 text-white" : "bg-transparent border border-zinc-200 text-zinc-950"} p-3.5 rounded-md text-sm w-full prose prose-sm max-w-none prose-p:leading-relaxed prose-pre:bg-zinc-800 prose-pre:text-zinc-100 prose-p:my-1.5 prose-ul:my-1.5 prose-ul:pl-4 prose-ol:my-1.5 prose-ol:pl-4 prose-li:my-0.5 prose-headings:my-2.5 prose-table:w-full prose-table:border prose-table:border-blue-200/60 prose-table:rounded-md prose-table:overflow-hidden prose-table:my-3 prose-table:bg-white prose-th:bg-blue-100/50 prose-th:px-3 prose-th:py-2.5 prose-th:text-left prose-th:font-semibold prose-th:text-blue-900 prose-th:border-b prose-th:border-blue-200/60 prose-td:px-3 prose-td:py-2.5 prose-td:border-b prose-td:border-blue-100/60 last:prose-td:border-0 whitespace-pre-wrap`}
												>
													{msg.role === "assistant" ? (
														<ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
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
					<MessageScrollerButton />
				</MessageScroller>
			</MessageScrollerProvider>

			{/* Chatbox Input */}
			<div className="px-8 py-4 shrink-0">
				<div className="bg-white rounded-md p-4 flex flex-col gap-3 border border-black/10 shadow-xs">
					{/* File Attachment Pill Preview in Input */}
					{attachedFile && (
						<div className="flex items-center gap-2 px-3 py-1.5 bg-blue-50 border border-blue-200 text-blue-800 rounded-md text-xs font-medium w-fit">
							<RiFileTextLine className="size-3.5 text-blue-600 shrink-0" />
							<span className="truncate max-w-xs">{attachedFile.name}</span>
							<button
								type="button"
								onClick={() => setAttachedFile(null)}
								className="text-blue-600 hover:text-blue-900 ml-1 p-0.5 rounded-full hover:bg-blue-100"
							>
								<RiCloseLine className="size-3.5" />
							</button>
						</div>
					)}

					<Input
						value={input}
						onChange={(e) => setInput(e.target.value)}
						onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && handleSend()}
						placeholder={
							knowledgeStatus === "PROCESSING"
								? "Waiting for ingestion to complete..."
								: knowledgeStatus === "APPROVED" && !isEditMode
									? "Click 'Edit Knowledge' to refine summary..."
									: "Ask questions or request adjustments..."
						}
						disabled={isInputDisabled}
						className="w-full bg-transparent border-none shadow-none focus-visible:ring-0 px-0 outline-none text-sm text-gray-700 placeholder:text-gray-500"
					/>

					<input type="file" ref={fileInputRef} onChange={handleFileSelect} className="hidden" />

					<div className="flex items-center justify-between pt-1">
						<Button
							type="button"
							variant="ghost"
							size="icon-sm"
							onClick={() => fileInputRef.current?.click()}
							disabled={isInputDisabled}
							className="text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100"
							title="Attach a file"
						>
							<RiAttachment2 className="size-4" />
						</Button>
						<Button
							onClick={handleSend}
							disabled={isInputDisabled || (!input.trim() && !attachedFile)}
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
