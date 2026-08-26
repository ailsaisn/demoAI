"use client";

import { Suspense, useEffect, useState, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { RiArrowLeftLine, RiRefreshLine } from "@remixicon/react";
import { ChatPreview } from "@/components/shared/knowledge/ChatPreview";
import { useCreateGeneralChatSession } from "@/app/dashboard/knowledge/hooks/use-knowledge";

function GeneralChatContent() {
	const router = useRouter();
	const searchParams = useSearchParams();
	const sessionId = searchParams.get("session_id");
	const initialPrompt = searchParams.get("q") || searchParams.get("initialPrompt") || "";
	const [sessionKey, setSessionKey] = useState(0);

	const createSession = useCreateGeneralChatSession();
	const isInitializingRef = useRef(false);

	useEffect(() => {
		// If user visits /dashboard/ingest/chat directly without a session_id, create one once
		if (!sessionId && !isInitializingRef.current) {
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
					isInitializingRef.current = false;
				}
			};
			void initSession();
		}
	}, [sessionId, initialPrompt, createSession, router]);

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
			<div className="flex items-center justify-between gap-4 p-4 border-b border-gray-200 shrink-0 bg-white">
				<div className="flex items-center gap-4">
					<Button
						variant="ghost"
						size="icon"
						onClick={() => router.push("/dashboard/ingest")}
						className="text-gray-500 hover:text-gray-900"
						title="Back to Ingest"
					>
						<RiArrowLeftLine className="size-5" />
					</Button>
					<div>
						<h1 className="text-lg font-semibold text-gray-900">General Knowledge Assistant</h1>
						<p className="text-sm text-gray-500">Ask questions about your knowledge base</p>
					</div>
				</div>

				<div className="flex items-center gap-2">
					<Button
						variant="outline"
						size="sm"
						onClick={handleNewSession}
						disabled={createSession.isPending}
						className="gap-2 text-zinc-700 hover:text-zinc-900"
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
