"use client";

import { MarkdownContent } from "@/components/shared/markdown-content";
import {
	Attachment,
	AttachmentContent,
	AttachmentDescription,
	AttachmentMedia,
	AttachmentTitle,
} from "@/components/ui/attachment";
import { Button } from "@/components/ui/button";
import {
	MessageScroller,
	MessageScrollerContent,
	MessageScrollerItem,
	MessageScrollerProvider,
	MessageScrollerSmartButton,
	MessageScrollerViewport,
} from "@/components/ui/message-scroller";
import { useEffect } from "react";
import { useCurrentUser } from "@/hooks/use-current-user";
import { useChatMessages } from "@/hooks/use-chat-messages";
import { useChatHistoryDetail } from "../hooks/use-chat-history";
import {
	RiArrowLeftLine,
	RiFileExcel2Line,
	RiFilePdf2Line,
	RiFilePpt2Line,
	RiFileTextLine,
	RiFileWord2Line,
	RiImage2Line,
	RiLoader4Line,
	RiMessage3Line,
	RiRobot2Line,
	RiThumbDownLine,
	RiThumbUpLine,
	RiUser3Line,
} from "@remixicon/react";
import { useParams, useRouter } from "next/navigation";
import { useSafeBack } from "@/hooks/use-safe-back";

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
		case "ppt":
		case "pptx":
		case "pps":
		case "ppsx":
		case "pot":
		case "potx":
		case "odp":
			return { Icon: RiFilePpt2Line, bgColor: "bg-orange-50", textColor: "text-orange-600" };
		case "jpg":
		case "jpeg":
		case "png":
		case "webp":
			return { Icon: RiImage2Line, bgColor: "bg-purple-50", textColor: "text-purple-600" };
		default:
			return { Icon: RiFileTextLine, bgColor: "bg-blue-50", textColor: "text-blue-600" };
	}
};

const IGNORED_METADATA_KEYS = new Set([
	"page",
	"score",
	"relevance",
	"similarity",
	"distance",
	"rank",
	"type",
	"source",
	"category",
	"doc_id",
	"knowledge_id",
	"id",
	"status",
	"timestamp",
	"created_at",
	"updated_at",
]);

const getAttachmentNames = (
	attachments?: Record<string, unknown> | null,
	role?: string,
): string[] => {
	if (role?.toUpperCase() === "ASSISTANT") {
		return [];
	}
	if (!attachments) return [];
	if (Array.isArray(attachments)) {
		return attachments
			.map((item) => (typeof item === "string" ? item : String(item?.name || item?.filename || "")))
			.filter((name) => Boolean(name) && !IGNORED_METADATA_KEYS.has(name.toLowerCase()));
	}
	if (typeof attachments === "object") {
		if (Array.isArray(attachments.names)) {
			return (attachments.names as string[]).filter(
				(name) => Boolean(name) && !IGNORED_METADATA_KEYS.has(name.toLowerCase()),
			);
		}
		return Object.keys(attachments).filter(
			(key) => Boolean(key) && !IGNORED_METADATA_KEYS.has(key.toLowerCase()),
		);
	}
	return [];
};

export default function ChatHistoryDetailPage() {
	const params = useParams();
	const router = useRouter();
	const handleBack = useSafeBack("/dashboard/chat-history");
	const sessionId = params.id as string;

	const { data: currentUser } = useCurrentUser();
	const { data: session } = useChatHistoryDetail(sessionId);
	const { data: messages, isLoading } = useChatMessages(sessionId);

	const isOwner = Boolean(currentUser?.id && session?.user_id && currentUser.id === session.user_id);
	const isStaffOrAdmin = currentUser?.type === "STAFF" || currentUser?.type === "ADMIN";
	const isGeneralChat =
		session?.session_type === "GENERAL_ASSISTANT" ||
		(!session?.branch_id && session?.branch === "General Assistant") ||
		session?.user_type === "STAFF";

	useEffect(() => {
		if (isOwner && isStaffOrAdmin && isGeneralChat && sessionId) {
			router.replace(`/dashboard/ingest/chat?session_id=${sessionId}`);
		}
	}, [isOwner, isStaffOrAdmin, isGeneralChat, sessionId, router]);

	const sessionTitle = session?.user_name || session?.doctor || "Chat Session Details";

	return (
		<div className="flex flex-col absolute inset-0 bg-white overflow-hidden">
			{/* Header matching GeneralChatContent */}
			<div className="flex items-center justify-between gap-4 px-4 py-3 border-b border-gray-200 shrink-0 bg-white z-10">
				<div className="flex items-center gap-3 min-w-0">
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
					<div className="min-w-0">
						<h1 className="text-base font-semibold text-gray-900 truncate">
							{sessionTitle}
						</h1>
					</div>
				</div>

				<div className="flex items-center gap-2 shrink-0">
					{isOwner && isStaffOrAdmin && isGeneralChat && (
						<Button
							variant="outline"
							size="sm"
							onClick={() => router.push(`/dashboard/ingest/chat?session_id=${sessionId}`)}
							className="gap-1.5 border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100 text-xs font-medium h-7 px-2.5 rounded-md cursor-pointer"
						>
							<RiMessage3Line className="size-3.5" />
							Continue Chat
						</Button>
					)}
					{session?.rating && (
						<span
							className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border ${
								session.rating === "GOOD"
									? "bg-emerald-50 text-emerald-700 border-emerald-200"
									: "bg-red-50 text-red-700 border-red-200"
							}`}
						>
							{session.rating === "GOOD" ? (
								<RiThumbUpLine className="size-3.5" />
							) : (
								<RiThumbDownLine className="size-3.5" />
							)}
							<span>{session.rating === "GOOD" ? "Helpful" : "Needs Improvement"}</span>
						</span>
					)}
					<span className="bg-zinc-50 text-zinc-600 border border-zinc-200 px-2.5 py-1 rounded-md text-xs font-medium">
						Read-only Archive
					</span>
				</div>
			</div>

			{/* Main Chat Area matching ChatPreview */}
			<div className="flex flex-1 overflow-hidden min-h-0">
				<div className="flex flex-col flex-1 bg-white overflow-hidden min-h-0 h-full">
					<MessageScrollerProvider>
						<MessageScroller className="flex-1 min-h-0">
							<MessageScrollerViewport className="px-6 sm:px-8">
								<MessageScrollerContent className="py-8 gap-6 w-full max-w-5xl mx-auto min-w-0">
									{isLoading && (
										<MessageScrollerItem>
											<div className="flex items-start gap-3 w-full min-w-0 max-w-full">
												<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
													<RiRobot2Line className="size-4 animate-pulse text-blue-500" />
												</div>
												<div className="bg-blue-50/70 text-zinc-950 p-3 rounded-md text-sm w-full min-w-0 max-w-full flex items-center gap-2 border border-blue-100/50">
													<RiLoader4Line className="size-4 animate-spin text-blue-600" />
													<span className="text-zinc-700 font-medium">
														Fetching conversation messages...
													</span>
												</div>
											</div>
										</MessageScrollerItem>
									)}

									{!isLoading && (!messages || messages.length === 0) && (
										<MessageScrollerItem>
											<div className="flex flex-col items-center justify-center text-center py-16 px-4 max-w-lg mx-auto space-y-3">
												<div className="size-12 rounded-xl bg-blue-50 text-blue-500 flex items-center justify-center">
													<RiRobot2Line className="size-6" />
												</div>
												<h2 className="text-base font-semibold text-zinc-950">
													No Messages
												</h2>
												<p className="text-xs text-zinc-500 leading-relaxed">
													There are no messages recorded for this conversation session.
												</p>
											</div>
										</MessageScrollerItem>
									)}

									{!isLoading &&
										messages?.map((msg, index) => {
											const isUser = msg.role?.toUpperCase() === "USER";
											const attachmentNames = getAttachmentNames(msg.attachments, msg.role);

											return (
												<MessageScrollerItem
													key={msg.id || `msg-${index}`}
													scrollAnchor={index === messages.length - 1}
												>
													<div
														className={`flex flex-col w-full min-w-0 max-w-full ${isUser ? "items-end" : "items-start"}`}
													>
														{attachmentNames.length > 0 && (
															<div
																className={`flex flex-wrap gap-2 mb-2 ${isUser ? "justify-end" : "justify-start"}`}
															>
																{attachmentNames.map((name, i) => {
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
														)}

														<div
															className={`flex items-start gap-3 w-full min-w-0 max-w-full ${isUser ? "flex-row-reverse" : ""}`}
														>
															<div className="bg-zinc-100 rounded text-zinc-950 flex items-center justify-center p-1.5 mt-0.5 shrink-0">
																{isUser ? (
																	<RiUser3Line className="size-4" />
																) : (
																	<RiRobot2Line className="size-4" />
																)}
															</div>
															<div
																className={`${
																	isUser
																		? "bg-primary text-primary-foreground whitespace-pre-wrap max-w-[85%] sm:max-w-[75%] rounded-md"
																		: "bg-transparent border border-zinc-200 text-zinc-950 w-full rounded-md"
																} p-3.5 text-sm min-w-0 overflow-hidden`}
															>
																{isUser ? (
																	msg.content
																) : (
																	<MarkdownContent content={msg.content} />
																)}
															</div>
														</div>
													</div>
												</MessageScrollerItem>
											);
										})}
								</MessageScrollerContent>
							</MessageScrollerViewport>
							<MessageScrollerSmartButton />
						</MessageScroller>
					</MessageScrollerProvider>
				</div>
			</div>
		</div>
	);
}

