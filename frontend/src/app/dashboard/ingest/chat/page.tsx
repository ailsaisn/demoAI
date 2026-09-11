"use client";

import { Suspense, useEffect, useState, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useSafeBack } from "@/hooks/use-safe-back";
import { Button } from "@/components/ui/button";
import { RiArrowLeftLine, RiRefreshLine } from "@remixicon/react";
import { ChatPreview } from "@/app/dashboard/knowledge/components/preview/chat-preview";
import { useCreateGeneralChatSession, useGeneralChatSession } from "@/app/dashboard/knowledge/hooks/use-knowledge";

function GeneralChatContent() {
	const router = useRouter();
	const handleBack = useSafeBack("/dashboard/ingest");
	const searchParams = useSearchParams();
	const sessionId = searchParams.get("session_id");
	const initialPrompt = searchParams.get("q") || searchParams.get("initialPrompt") || "";
	const [sessionKey, setSessionKey] = useState(0);

	const createSession = useCreateGeneralChatSession();
	const { isError: isSessionError } = useGeneralChatSession(sessionId);
	const isInitializingRef = useRef(false);

	useEffect(() => {
		// If user visits /dashboard/ingest/chat directly without a session_id, or with an invalid/unauthorized session_id, create a new one
		if ((!sessionId || isSessionError) && !isInitializingRef.current) {
			isInitializingRef.current = true;
			const initSession = async () => {
				try {
					const newSession = await createSession.mutateAsync();
					if (initialPrompt) {
						router.replace(
							`/dashboard/ingest/chat?session_id=${newSession.id}&q=${encodeURIComponent(initialPrompt)}`
						);
					} else {
						router.replace(`/dashboard/ingest/chat?session_id=${newSession.id}`);
					}
				} catch {
					// Silent fail
				} finally {
					isInitializingRef.current = false;
				}
			};
			void initSession();
		}
	}, [sessionId, isSessionError, initialPrompt, createSession, router]);

	const handleNewSession = async () => {
		try {
			const newSession = await createSession.mutateAsync();
			setSessionKey((prev) => prev + 1);
			router.replace(`/dashboard/ingest/chat?session_id=${newSession.id}`);
		} catch {
			setSessionKey((prev) => prev + 1);
			router.replace("/dashboard/ingest/chat");
		}
	};

	return (
		<div className="flex flex-col absolute inset-0">
			{/* Header matching KnowledgeDetailPage */}
			<div className="flex items-center justify-between gap-4 px-4 py-3 border-b border-gray-200 shrink-0 bg-white">
				<div className="flex items-center gap-3">
					<Button
						variant="ghost"
						size="icon"
						onClick={handleBack}
						className="size-9 rounded-lg text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100"
						title="Back"
						aria-label="Back"
					>
						<RiArrowLeftLine className="size-5" />
					</Button>
					<h1 className="text-base font-semibold text-gray-900">General Knowledge Assistant</h1>
				</div>

				<div className="flex items-center gap-2">
					<Button
						variant="outline"
						onClick={handleNewSession}
						disabled={createSession.isPending}
						className="gap-2 border-gray-200 bg-white text-zinc-700 hover:bg-zinc-50 rounded-lg px-4 h-10 font-medium text-sm transition-colors cursor-pointer shadow-none"
					>
						<RiRefreshLine className="size-4" />
						New Session
					</Button>
				</div>
			</div>

			{/* Main Content Area rendering ChatPreview component directly */}
			<div className="flex flex-1 overflow-hidden">
				<ChatPreview
					key={`${sessionId || "new"}_${sessionKey}`}
					mode="general"
					sessionId={sessionId}
					initialPrompt={initialPrompt}
				/>
			</div>
		</div>
	);
}

export default function GeneralChatPage() {
	return (
		<Suspense fallback={<div className="p-8 text-center text-sm text-zinc-500">Loading chat session...</div>}>
			<GeneralChatContent />
		</Suspense>
	);
}
